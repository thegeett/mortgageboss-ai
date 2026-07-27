"""LP-340 — the `*_normalized` convention: strip entity suffixes (in the RULE, not the tag).

Geet's decision (ADR-281): a corporate entity suffix (Inc/LLC/Corp/Co/Ltd) is FORMAT, not content, for
employer matching. Implemented as a DECLARED normalizer `drop_entity_suffix` on IN-5's chain (the LP-325
registry's sanctioned extension) — the TAG still reports what the document states (LP-335). These tests pin
the convention BOTH DIRECTIONS, the IN-5 consequences (incl. the NAMED accepted trade-off), and the
equivalence of the LIVE rules whose chains were deliberately NOT touched.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import (
    _NORMALIZERS,
    _normalize,
    evaluate_consistency_rule,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import KNOWN_NORMALIZERS, load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_BORROWER = uuid4()
_IN5_CHAIN = ("casefold", "drop_punct", "collapse_ws", "strip", "drop_entity_suffix")


def _tag(value: object) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _emp(v: str) -> dict[str, Tag]:
    return {"income.employer_normalized": _tag(v)}


def _name(v: str) -> dict[str, Tag]:
    return {"id.name_normalized": _tag(v)}


def _snapshot(sources: list[tuple[str, dict[str, Tag]]]) -> Snapshot:
    entries = [
        DocumentEntry(
            content_id=sid,
            document_type="pay_stub",
            belongs_to=(BorrowerRef(borrower_id=_BORROWER, name="Sam Borrower"),),
            fields={},
        )
        for sid, _ in sources
    ]
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(dict(sources)),
    )


class _Reasoner:
    def __init__(self, value: str) -> None:
        self.value, self.calls = value, 0

    async def __call__(self, context_json: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "because"), 1, 1, "stub", False)


async def _eval_in5(snapshot: Snapshot, reasoner=None):
    return await evaluate_consistency_rule(load_rule_spec("IN-5"), snapshot, reasoner=reasoner)


# ================================================================================================= #
# THE NORMALIZER — both directions
# ================================================================================================= #
def test_drop_entity_suffix_strips_but_never_invents_or_empties() -> None:
    strip = _NORMALIZERS["drop_entity_suffix"]
    assert strip("acme logistics inc") == "acme logistics"  # suffix stripped
    assert strip("acme logistics llc") == "acme logistics"  # a DIFFERENT suffix -> same base
    assert strip("acme logistics") == "acme logistics"  # NO suffix -> not "corrected" into one
    assert strip("sterling retail") == "sterling retail"  # a real content word is not a suffix
    assert strip("inc") == "inc"  # never strips to empty (a firm literally named by one token)


def test_drop_entity_suffix_is_greedy_multi_token() -> None:
    # GREEDY on purpose: peel EVERY trailing suffix token so a full legal name and its short form collapse
    # to the same base (the W-2-legal-name vs paystub-short-form matching case). Documented cost: a real
    # name-word that is also a suffix word (Company / Co) is removed when trailing.
    strip = _NORMALIZERS["drop_entity_suffix"]
    assert strip("acme logistics company llc") == "acme logistics"  # both suffix tokens peeled
    assert strip("acme co ltd") == "acme"  # multiple entity tokens
    assert strip("the trading company") == "the trading"  # trailing suffix-WORD removed (the cost)
    assert strip("company") == "company"  # sole token preserved (never empty)


def test_drop_entity_suffix_requires_casefold_and_drop_punct_before_it() -> None:
    # LP-340 ordering guard: drop_entity_suffix matches lowercase, punctuation-free tokens, so a chain that
    # places it before casefold/drop_punct fails LOUD at LOAD — not as a silent mid-run under-strip.
    from app.verification.rules.specs import ConsistencyEval, ConsistencyOutcome

    ok = ConsistencyOutcome(verdict="satisfied", reasoning="ok")
    bad = ConsistencyOutcome(verdict="fired", reasoning="differ")
    with pytest.raises(ValueError, match="drop_entity_suffix"):
        ConsistencyEval(
            subject="loan",
            gather_tag="income.employer_normalized",
            source_scope="borrower_documents",
            compare_mode="exact",
            normalization=("drop_entity_suffix", "casefold"),  # casefold AFTER the strip → invalid
            on_agree=ok,
            on_disagree=bad,
        )


def test_full_in5_chain_collapses_suffix_variants() -> None:
    # Through the REAL declared chain the rule uses (casefold->punct->ws->strip->drop_entity_suffix).
    norm = lambda v: _normalize(v, _IN5_CHAIN)  # noqa: E731
    assert (
        norm("Acme Logistics, Inc.")
        == norm("Acme Logistics LLC")
        == norm("acme  logistics")
        == "acme logistics"
    )
    assert norm("Sterling Retail") != norm("Acme Logistics")  # genuine content difference survives


# ================================================================================================= #
# IN-5 END-TO-END — the exact bookend + the fuzzy residue (LP-325 cost property intact)
# ================================================================================================= #
async def test_in5_identical_employer_satisfied_no_ai() -> None:
    stub = _Reasoner("agree")
    results = await _eval_in5(
        _snapshot([("ps", _emp("Acme Logistics Inc")), ("w2", _emp("Acme Logistics Inc"))]),
        reasoner=stub,
    )
    assert results[0].verdict is Verdict.SATISFIED and stub.calls == 0  # exact bookend, no AI


async def test_in5_inc_vs_no_suffix_matches_no_ai() -> None:
    # THE case the decision optimises for: a benign Inc-vs-no-suffix FORMAT difference now collapses at the
    # exact bookend -> satisfied with NO AI call (no ratification-pending finding on a formatting diff).
    stub = _Reasoner("agree")
    results = await _eval_in5(
        _snapshot([("ps", _emp("Acme Logistics Inc")), ("w2", _emp("Acme Logistics"))]),
        reasoner=stub,
    )
    assert results[0].verdict is Verdict.SATISFIED and stub.calls == 0


async def test_in5_inc_vs_llc_matches_THE_ACCEPTED_TRADEOFF() -> None:
    # ACCEPTED TRADE-OFF / PRIYA ITEM (ADR-281): `Acme Logistics Inc` and `Acme Logistics LLC` are
    # DIFFERENT legal entities, but the suffix-strip makes them match at the exact bookend -> satisfied,
    # the fuzzy leg never runs. This is DELIBERATE (a suffix change is a restructuring, not an employer
    # change). If Priya reverses it, THIS is the test that must change — delete `drop_entity_suffix` from
    # IN-5's chain and this assertion flips to the fuzzy path. Named + findable, not hidden.
    stub = _Reasoner("agree")
    results = await _eval_in5(
        _snapshot([("ps", _emp("Acme Logistics Inc")), ("w2", _emp("Acme Logistics LLC"))]),
        reasoner=stub,
    )
    assert results[0].verdict is Verdict.SATISFIED and stub.calls == 0


async def test_in5_genuinely_different_employer_still_reaches_the_fuzzy_judge() -> None:
    # The real signal MUST survive: a genuinely different employer differs after normalization -> the
    # residue reaches the AI judge (stub called), which here disagrees -> fired.
    stub = _Reasoner("disagree")
    results = await _eval_in5(
        _snapshot([("ps", _emp("Acme Logistics Inc")), ("w2", _emp("Sterling Retail LLC"))]),
        reasoner=stub,
    )
    assert stub.calls == 1 and results[0].verdict in {Verdict.FIRED, Verdict.NEEDS_REVIEW}


# ================================================================================================= #
# EQUIVALENCE — the LIVE rules' chains were NOT touched (only inert IN-5 got the normalizer)
# ================================================================================================= #
def test_live_rule_chains_have_no_suffix_strip() -> None:
    for rid in ("ID-1", "ID-4"):  # LIVE — must be untouched
        chain = load_rule_spec(rid).consistency.normalization
        assert "drop_entity_suffix" not in chain, f"{rid} (LIVE) chain must not change"
        assert chain == ("casefold", "drop_punct", "collapse_ws", "strip")


async def test_id1_fuzzy_leg_still_reconciles_naming_variance() -> None:
    # D2 note: names carry no corporate suffix, so ID-1's behaviour is unchanged. A benign name variance
    # still differs at the exact bookend and reaches ID-1's fuzzy judge (the reconciliation ID-1 exists
    # for). Assert the fuzzy leg is intact (the AI is consulted; not short-circuited).
    stub = _Reasoner("agree")
    snap = _snapshot([("dl", _name("Robert J Smith")), ("app", _name("Bob Smith"))])
    results = await evaluate_consistency_rule(load_rule_spec("ID-1"), snap, reasoner=stub)
    assert stub.calls == 1 and results[0].verdict is Verdict.SATISFIED  # fuzzy judge reconciled it


def test_registry_drift_guard_and_activation_unchanged() -> None:
    assert set(_NORMALIZERS) == KNOWN_NORMALIZERS  # the new key is registered on both sides
    # LP-340 added IN-5's normalizer while IN-5 was inert; LP-389 later activated IN-5 (employer_normalized
    # measured 100% >= its 0.95 bar). IN-5 is now LIVE — the drift guard tracks the CURRENT active set.
    assert "IN-5" in ACTIVE_RULE_IDS
    assert ACTIVE_RULE_IDS == (
        "AS-1",
        "OC-2",
        "ID-2",
        "ID-4",
        "ID-1",
        "ID-3",
        "ID-6",
        "ID-7",
        "ID-9",
        "ID-8",
        "IN-2",
        # LP-389 — the first activation pass, via the eligibility gate (activation_bars.is_eligible)
        "IN-1",
        "IN-5",
        "ID-5",  # LP-389-A — the subject mismatch fixed (per-borrower), input now resolves
        # LP-384 — the second activation pass: the stuck deterministic rules, verified on build_lf6t3n_plus
        "AS-9",
        "IN-4",
        "AS-10",
        "AS-2",
        "AS-12",
        "IN-3",
        "IN-7",
        "IN-10",
        "IN-11",
        "AS-11",
        "AS-8",  # LP-406-2b — the first Bucket 2 rule live (statement chaining on stmt.continuity)
        "IN-6",  # LP-412 — Priya signed off the 0.95 bar (calibratable-now, same as IN-5)
        "PC-7",  # LP-412 — Priya signed off the closing window (no-ai-threshold-pending)
    )
