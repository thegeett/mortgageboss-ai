"""LP-644 §3 — the cache codecs, where a wrong answer is worse than no cache at all.

Persisting an AI judgment is safe only if it comes back as the same judgment. A value that does not
survive dump→load is served from cache as fact, on a later run, with no call to check it against —
strictly worse than re-asking. So these pin round-tripping, and they pin the two REJECTION rules that
keep a degraded answer from being frozen into a file permanently.

Keyless and DB-free: the codecs are pure functions.
"""

from __future__ import annotations

from app.ai.tag_production import TagJudgment
from app.services.tag_correlation import (
    SourceStrength,
    _Sourced,
    dump_stage_b_entry,
    load_stage_b_entry,
)
from app.services.tag_production import _Judged, dump_stage_a_entry, load_stage_a_entry
from app.verification.tag_materialization.ai import (
    AiTagJudgment,
    _Resolved,
    dump_ai_group_entry,
    load_ai_group_entry,
)


# --------------------------------------------------------------------------- #
# Stage A
# --------------------------------------------------------------------------- #
def test_stage_a_entry_round_trips() -> None:
    entry = _Judged(
        is_money_in=TagJudgment("in", 0.91, "a deposit"),
        apparent_category=TagJudgment("payroll", 0.8, "employer name"),
        reason="tag production failed",
        counterparty=TagJudgment("Ally Bank", 0.7, "from the description"),
    )

    restored = load_stage_a_entry(dump_stage_a_entry(entry))

    assert restored == entry


def test_stage_a_entry_round_trips_without_a_counterparty() -> None:
    # bug-001 added `counterparty` last and defaulted; a null must survive as a null rather than
    # becoming an empty judgment, which would put a blank name on a finding.
    entry = _Judged(
        is_money_in=TagJudgment("in", 0.9, "x"),
        apparent_category=TagJudgment("transfer", 0.9, "y"),
        reason="r",
    )

    restored = load_stage_a_entry(dump_stage_a_entry(entry))

    assert restored == entry
    assert restored is not None and restored.counterparty is None


def test_a_partial_stage_a_entry_is_rejected() -> None:
    # THE RULE THAT MATTERS. Stage A caches in memory only when BOTH AI tags resolved, so a partial
    # retries next run. Accepting one here would freeze a degraded answer into the file forever.
    assert load_stage_a_entry({"is_money_in": {"value": "in"}, "reason": "r"}) is None
    assert load_stage_a_entry({"apparent_category": {"value": "payroll"}, "reason": "r"}) is None


def test_a_corrupt_stage_a_row_returns_none_rather_than_raising() -> None:
    # A cache must never fail a run: the worst it may cost is a re-ask.
    assert load_stage_a_entry({}) is None
    assert load_stage_a_entry({"is_money_in": "not-a-dict", "apparent_category": 7}) is None


# --------------------------------------------------------------------------- #
# Stage B
# --------------------------------------------------------------------------- #
def test_stage_b_entry_round_trips() -> None:
    entry = _Sourced(
        value="yes",
        source_content_id="txn123",
        confidence=0.88,
        reasoning="matching debit",
        cacheable=True,
        strength=SourceStrength.VERIFIED,
    )

    restored = load_stage_b_entry(dump_stage_b_entry(entry))

    assert restored == entry


def test_stage_b_entry_round_trips_without_a_strength() -> None:
    entry = _Sourced(
        value="unknown",
        source_content_id=None,
        confidence=None,
        reasoning=None,
        cacheable=True,
        strength=None,
    )

    assert load_stage_b_entry(dump_stage_b_entry(entry)) == entry


def test_a_loaded_stage_b_entry_is_always_cacheable() -> None:
    # `cacheable` is not round-tripped by design: it decided whether the row was allowed to exist, so
    # every stored row was cacheable. A stored False would describe a row that should never have been
    # written, and reconstructing it would be a value that can only ever be wrong.
    entry = _Sourced("no", None, 0.5, "nothing found", cacheable=True, strength=SourceStrength.NONE)
    restored = load_stage_b_entry(dump_stage_b_entry(entry))

    assert restored is not None and restored.cacheable is True


def test_an_off_vocabulary_stage_b_value_is_rejected() -> None:
    assert load_stage_b_entry({"value": "probably", "strength": None}) is None


def test_an_unknown_strength_is_rejected_rather_than_guessed() -> None:
    # A strength the enum does not carry means a shape change. Re-asking costs one call; guessing
    # costs a wrong provenance label on a finding a processor reads.
    assert load_stage_b_entry({"value": "yes", "strength": "extremely"}) is None


# --------------------------------------------------------------------------- #
# Materialization
# --------------------------------------------------------------------------- #
def test_ai_group_entry_round_trips() -> None:
    entry = _Resolved(
        tags={
            "address_normalized": AiTagJudgment("12 High St", 0.9, "from the licence"),
            "current_address_type": AiTagJudgment("residential", 0.8, "looks residential"),
        },
        reason="tag value missing or malformed in structuring response",
    )

    restored = load_ai_group_entry(dump_ai_group_entry(entry))

    assert restored == entry


def test_an_ai_group_entry_with_a_hole_is_rejected() -> None:
    # The producer caches only when EVERY tag in the group resolved. A row with a hole would pin an
    # "unknown" onto a subject forever — the tag layer's worst failure, because it reads as an honest
    # abstention rather than as a stale cache.
    assert load_ai_group_entry({"tags": {"a": None}, "reason": "r"}) is None
    assert load_ai_group_entry({"tags": {}, "reason": "r"}) is None
    assert load_ai_group_entry({"reason": "r"}) is None


def test_a_corrupt_ai_group_row_returns_none_rather_than_raising() -> None:
    assert load_ai_group_entry({"tags": {"a": {"confidence": 0.5}}}) is None
    assert load_ai_group_entry({"tags": "not-a-dict"}) is None
