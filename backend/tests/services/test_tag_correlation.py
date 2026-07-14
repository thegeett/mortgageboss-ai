"""Stage-B sourcing tag via candidate-then-judge (LP-314) — keyless, via the injected judge stub.

Covers: a sourced deposit (matching own-account transfer), the fraud case (no candidate → a real
"no", not "unknown"), the deterministic cross-account candidate-search (the AI sees only the small
candidate set), DAG propagation from Stage-A is_money_in, fail-closed honesty, content_id
cross-provenance, cache-by-content, and that AI calls scale with deposits (not transaction pairs).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.ai.tag_correlation import AIClientError, SourcingJudgment, SourcingResult
from app.services.tag_correlation import (
    SourcingCache,
    find_source_candidates,
    produce_stage_b_sourcing_tags,
)
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class StubJudge:
    """A deterministic stand-in for the sourcing judge. Records each judge context it saw."""

    def __init__(
        self,
        *,
        value: str = "no",
        source_index: int | None = None,
        confidence: float | None = 0.8,
        error: bool = False,
        truncate: bool = False,
        malformed: bool = False,
    ) -> None:
        self.value = value
        self.source_index = source_index
        self.confidence = confidence
        self.error = error
        self.truncate = truncate
        self.malformed = malformed
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, context_json: str) -> SourcingResult:
        self.calls.append(json.loads(context_json))
        if self.error:
            raise AIClientError("stubbed transport failure")
        judgment = (
            None
            if self.malformed
            else SourcingJudgment(self.value, self.source_index, self.confidence, "stub reason")
        )
        return SourcingResult(
            judgment=judgment,
            input_tokens=5,
            output_tokens=3,
            model="stub",
            truncated=self.truncate,
        )


def _txn(amount: str, description: str, date: str = "2026-05-05") -> dict[str, Any]:
    return {
        "date": date,
        "amount": amount,
        "description": description,
        "transaction_type": "deposit",
    }


def _snapshot(accounts: list[tuple[str, list[dict[str, Any]]]]) -> Snapshot:
    entries = [
        DocumentEntry(
            content_id=doc_id,
            document_type="bank_statement",
            transactions=build_transactions(
                transaction_field_sets({"transactions": raw}, "bank_statement"),
                document_content_id=doc_id,
            ),
        )
        for doc_id, raw in accounts
    ]
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present(entries),
    )


def _flatten(snap: Snapshot) -> list[Any]:
    return [txn for entry in snap.documents.entries for txn in (entry.transactions or ())]


def _stage_a_tag(value: str, confidence: float | None, content_id: str) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="stage a",
        source_facts=(content_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=1,
        stage=TagStage.A,
    )


def _with_stage_a(
    snap: Snapshot,
    spec: dict[str, tuple[str, str]],
    *,
    confidence: float | None = 0.9,
    default: tuple[str, str] = ("in", "vendor"),
) -> Snapshot:
    """Attach Stage-A is_money_in + apparent_category tags, keyed per transaction by its amount."""
    by_subject: dict[str, dict[str, Tag]] = {}
    for txn in _flatten(snap):
        money_in, category = spec.get(txn.amount.value, default)
        by_subject[txn.content_id] = {
            "txn.is_money_in": _stage_a_tag(money_in, confidence, txn.content_id),
            "txn.apparent_category": _stage_a_tag(category, confidence, txn.content_id),
        }
    return snap.model_copy(update={"tags": TagsSection.present(by_subject)})


def _source_tag(snap: Snapshot, txn: Any) -> Tag | None:
    return snap.tags.by_subject.get(txn.content_id, {}).get("txn.has_identified_source")


def _require_source_tag(snap: Snapshot, txn: Any) -> Tag:
    tag = _source_tag(snap, txn)
    assert tag is not None
    return tag


# --------------------------------------------------------------------------- #
# Sourced / unsourced
# --------------------------------------------------------------------------- #


async def test_sourced_deposit_cites_both_content_ids() -> None:
    # A $500 deposit and a matching $500 own-account debit in ANOTHER account.
    snap = _snapshot(
        [
            ("docchecking00000", [_txn("500.00", "ONLINE TRANSFER FROM SAVINGS", "2026-05-05")]),
            ("docsavings000000", [_txn("500.00", "ONLINE TRANSFER TO CHECKING", "2026-05-04")]),
        ]
    )
    snap = _with_stage_a(snap, {"500.00": ("in", "transfer_own")}, default=("out", "transfer_own"))
    # The savings debit is the "out"; the checking credit is the "in" deposit.
    snap = snap.model_copy(
        update={
            "tags": TagsSection.present(
                {
                    _flatten(snap)[0].content_id: {
                        "txn.is_money_in": _stage_a_tag("in", 0.9, _flatten(snap)[0].content_id),
                        "txn.apparent_category": _stage_a_tag(
                            "transfer_own", 0.9, _flatten(snap)[0].content_id
                        ),
                    },
                    _flatten(snap)[1].content_id: {
                        "txn.is_money_in": _stage_a_tag("out", 0.9, _flatten(snap)[1].content_id),
                        "txn.apparent_category": _stage_a_tag(
                            "transfer_own", 0.9, _flatten(snap)[1].content_id
                        ),
                    },
                }
            )
        }
    )
    deposit, debit = _flatten(snap)[0], _flatten(snap)[1]

    stub = StubJudge(value="yes", source_index=1, confidence=0.85)
    out = await produce_stage_b_sourcing_tags(snap, reasoner=stub)

    tag = _source_tag(out, deposit)
    assert tag is not None and tag.value == "yes"
    assert tag.stage is TagStage.B and tag.produced_by is TagProducedBy.AI
    assert set(tag.source_facts) == {deposit.content_id, debit.content_id}  # BOTH cited
    assert tag.reasoning == "stub reason"
    # confidence propagated: min(judge 0.85, is_money_in 0.9) = 0.85
    assert tag.confidence == 0.85
    # The debit itself is money-out → not a sourcing subject.
    assert _source_tag(out, debit) is None


async def test_unsourced_deposit_is_a_real_no_not_unknown() -> None:
    """The fraud case: a large deposit with NO candidate source → the judge is handed an empty
    candidate set and returns a real "no" — the signal AS-1 fires on, NOT "unknown"."""
    snap = _snapshot([("docchecking00000", [_txn("12000.00", "MOBILE DEPOSIT", "2026-05-05")])])
    snap = _with_stage_a(snap, {"12000.00": ("in", "vendor")})
    deposit = _flatten(snap)[0]

    stub = StubJudge(value="no")  # the judge, seeing no candidates, says "no"
    out = await produce_stage_b_sourcing_tags(snap, reasoner=stub)

    # The judge was handed an EMPTY candidate set (code found nothing).
    assert stub.calls[0]["candidates"] == []
    tag = _source_tag(out, deposit)
    assert tag is not None
    assert tag.value == "no"  # NOT "unknown" — looked and found nothing
    assert tag.source_facts == (deposit.content_id,)


# --------------------------------------------------------------------------- #
# Candidate search — deterministic, bounded, cross-account
# --------------------------------------------------------------------------- #


async def test_candidate_search_finds_cross_account_match_and_judge_sees_only_it() -> None:
    snap = _snapshot(
        [
            (
                "docchecking00000",
                [
                    _txn("2500.00", "TRANSFER IN", "2026-05-05"),
                    _txn("40.00", "COFFEE", "2026-05-06"),
                ],
            ),
            (
                "docsavings000000",
                [
                    _txn("2500.00", "TRANSFER OUT", "2026-05-03"),
                    _txn("999.00", "UNRELATED", "2026-05-05"),
                ],
            ),
        ]
    )
    snap = _with_stage_a(
        snap,
        {
            "2500.00": ("in", "transfer_own"),
            "40.00": ("out", "vendor"),
            "999.00": ("out", "vendor"),
        },
    )
    # Fix the two $2500 rows: the checking one is the deposit ("in"), the savings one the debit.
    deposit = _flatten(snap)[0]
    by = {cid: dict(t) for cid, t in snap.tags.by_subject.items()}
    by[deposit.content_id]["txn.is_money_in"] = _stage_a_tag("in", 0.9, deposit.content_id)
    savings_debit = _flatten(snap)[2]
    by[savings_debit.content_id]["txn.is_money_in"] = _stage_a_tag(
        "out", 0.9, savings_debit.content_id
    )
    snap = snap.model_copy(update={"tags": TagsSection.present(by)})

    stub = StubJudge(value="yes", source_index=1)
    out = await produce_stage_b_sourcing_tags(snap, reasoner=stub)

    # Exactly ONE deposit judged; the judge saw ONLY the matching $2500 debit — not the $999
    # unrelated debit, not the $40 purchase, and never the whole file.
    assert len(stub.calls) == 1
    candidates = stub.calls[0]["candidates"]
    assert len(candidates) == 1 and candidates[0]["amount"] == "2500.00"
    assert _require_source_tag(out, deposit).value == "yes"


def test_find_source_candidates_is_pure_and_matches_by_amount_and_date() -> None:
    snap = _snapshot(
        [
            ("docchecking00000", [_txn("300.00", "DEP", "2026-05-10")]),
            (
                "docsavings000000",
                [_txn("300.00", "WD NEAR", "2026-05-08"), _txn("300.00", "WD FAR", "2026-04-01")],
            ),
        ]
    )
    deposit = _flatten(snap)[0]
    near, far = _flatten(snap)[1], _flatten(snap)[2]
    debits: list[tuple[Any, Decimal | None, date | None]] = [
        (near, Decimal("300.00"), date(2026, 5, 8)),
        (far, Decimal("300.00"), date(2026, 4, 1)),
    ]
    candidates = find_source_candidates(deposit, {}, debits)  # no payroll tag → transfer only
    # Only the in-window debit matches; the April one is out of window.
    assert [c.source_content_id for c in candidates] == [near.content_id]


def test_debit_after_the_deposit_is_not_a_source_candidate() -> None:
    """A source must post ON OR BEFORE the deposit it funds (small posting-lag aside). A
    same-amount debit well AFTER the deposit is temporally impossible as its source and must not
    be surfaced — otherwise the judge could accept a coincidental later spend and flip a genuinely
    unexplained deposit to 'sourced'."""
    snap = _snapshot(
        [
            ("docchecking00000", [_txn("300.00", "DEP", "2026-05-10")]),
            (
                "docsavings000000",
                [
                    _txn("300.00", "WD LATER", "2026-05-14"),
                    _txn("300.00", "WD PRIOR", "2026-05-08"),
                ],
            ),
        ]
    )
    deposit = _flatten(snap)[0]
    later, prior = _flatten(snap)[1], _flatten(snap)[2]
    debits: list[tuple[Any, Decimal | None, date | None]] = [
        (later, Decimal("300.00"), date(2026, 5, 14)),  # 4 days AFTER the deposit — impossible
        (prior, Decimal("300.00"), date(2026, 5, 8)),  # 2 days before — a plausible source
    ]
    candidates = find_source_candidates(deposit, {}, debits)
    # Only the prior debit is a candidate; the later one is excluded (beyond the posting-lag).
    assert [c.source_content_id for c in candidates] == [prior.content_id]


# --------------------------------------------------------------------------- #
# DAG propagation from Stage-A is_money_in
# --------------------------------------------------------------------------- #


async def test_money_in_unknown_propagates_to_unknown_without_an_ai_call() -> None:
    snap = _snapshot([("docchecking00000", [_txn("77.00", "MYSTERY", "2026-05-05")])])
    snap = _with_stage_a(snap, {"77.00": ("unknown", "unknown")}, confidence=0.3)
    deposit = _flatten(snap)[0]

    stub = StubJudge()
    out = await produce_stage_b_sourcing_tags(snap, reasoner=stub)

    assert stub.calls == []  # DAG propagation is deterministic — no AI call
    tag = _source_tag(out, deposit)
    assert tag is not None
    assert tag.value == "unknown" and tag.produced_by is TagProducedBy.DERIVED
    assert tag.confidence == 0.3  # no more confident than the is_money_in it depends on


async def test_money_out_is_not_a_sourcing_subject() -> None:
    snap = _snapshot([("docchecking00000", [_txn("40.00", "CARD PURCHASE", "2026-05-05")])])
    snap = _with_stage_a(snap, {"40.00": ("out", "vendor")})
    deposit = _flatten(snap)[0]

    out = await produce_stage_b_sourcing_tags(snap, reasoner=StubJudge())
    assert _source_tag(out, deposit) is None  # money-out gets no has_identified_source


# --------------------------------------------------------------------------- #
# Honesty / fail-closed
# --------------------------------------------------------------------------- #


async def test_ai_error_is_graceful_unknown_with_reason() -> None:
    snap = _snapshot([("docchecking00000", [_txn("500.00", "DEP", "2026-05-05")])])
    snap = _with_stage_a(snap, {"500.00": ("in", "vendor")})
    deposit = _flatten(snap)[0]

    out = await produce_stage_b_sourcing_tags(snap, reasoner=StubJudge(error=True))
    tag = _source_tag(out, deposit)
    assert tag is not None and tag.value == "unknown"
    assert tag.reasoning == "sourcing judgment failed"


async def test_malformed_and_truncated_fail_closed_not_yes() -> None:
    snap = _snapshot([("docchecking00000", [_txn("500.00", "DEP", "2026-05-05")])])
    snap = _with_stage_a(snap, {"500.00": ("in", "vendor")})
    deposit = _flatten(snap)[0]

    malformed = await produce_stage_b_sourcing_tags(snap, reasoner=StubJudge(malformed=True))
    malformed_tag = _require_source_tag(malformed, deposit)
    assert malformed_tag.value == "unknown"  # never a defaulted "yes"
    assert malformed_tag.reasoning == "sourcing response malformed"

    truncated = await produce_stage_b_sourcing_tags(
        snap, reasoner=StubJudge(value="yes", truncate=True)
    )
    truncated_tag = _require_source_tag(truncated, deposit)
    assert truncated_tag.value == "unknown"
    assert truncated_tag.reasoning == "sourcing response truncated"


async def test_yes_citing_a_nonexistent_candidate_fails_closed() -> None:
    snap = _snapshot([("docchecking00000", [_txn("9000.00", "MOBILE DEPOSIT", "2026-05-05")])])
    snap = _with_stage_a(snap, {"9000.00": ("in", "vendor")})  # no candidates
    deposit = _flatten(snap)[0]

    # The stub claims "yes" and cites candidate #2 — but there are zero candidates.
    out = await produce_stage_b_sourcing_tags(snap, reasoner=StubJudge(value="yes", source_index=2))
    tag = _require_source_tag(out, deposit)
    assert tag.value == "unknown"
    assert tag.reasoning == "model cited an invalid candidate; failed closed"


# --------------------------------------------------------------------------- #
# Scaling + cache
# --------------------------------------------------------------------------- #


async def test_ai_calls_scale_with_deposits_not_transaction_pairs() -> None:
    # 2 money-in deposits + 2 money-out debits → 2 judge calls (not 4 pairs, not 4 transactions).
    snap = _snapshot(
        [
            (
                "docchecking00000",
                [_txn("100.00", "DEP A", "2026-05-05"), _txn("200.00", "DEP B", "2026-05-06")],
            ),
            (
                "docsavings000000",
                [_txn("100.00", "WD A", "2026-05-05"), _txn("200.00", "WD B", "2026-05-06")],
            ),
        ]
    )
    snap = _with_stage_a(
        snap,
        {"100.00": ("in", "transfer_own"), "200.00": ("in", "transfer_own")},
        default=("out", "transfer_own"),
    )
    # The savings rows are the debits.
    by = {cid: dict(t) for cid, t in snap.tags.by_subject.items()}
    for debit in _flatten(snap)[2:]:
        by[debit.content_id]["txn.is_money_in"] = _stage_a_tag("out", 0.9, debit.content_id)
    snap = snap.model_copy(update={"tags": TagsSection.present(by)})

    stub = StubJudge(value="yes", source_index=1)
    await produce_stage_b_sourcing_tags(snap, reasoner=stub)
    assert len(stub.calls) == 2  # one per money-in deposit


async def test_cache_reuses_unchanged_deposit_and_reproduces_changed_one() -> None:
    cache: SourcingCache = {}
    snap1 = _snapshot([("docchecking00000", [_txn("500.00", "DEP", "2026-05-05")])])
    snap1 = _with_stage_a(snap1, {"500.00": ("in", "vendor")})
    stub1 = StubJudge(value="no")
    await produce_stage_b_sourcing_tags(snap1, reasoner=stub1, cache=cache)
    assert len(stub1.calls) == 1 and len(cache) == 1

    # Same deposit again → cache hit, no new call.
    stub2 = StubJudge(value="no")
    await produce_stage_b_sourcing_tags(snap1, reasoner=stub2, cache=cache)
    assert stub2.calls == []

    # A changed deposit (different amount → different content_id + candidate key) → re-judged.
    snap3 = _snapshot([("docchecking00000", [_txn("777.00", "DEP", "2026-05-05")])])
    snap3 = _with_stage_a(snap3, {"777.00": ("in", "vendor")})
    stub3 = StubJudge(value="no")
    await produce_stage_b_sourcing_tags(snap3, reasoner=stub3, cache=cache)
    assert len(stub3.calls) == 1


async def test_cache_key_includes_apparent_category_not_just_content_ids() -> None:
    """The cache key covers the FULL judge context. The SAME raw deposit (same content_id, same
    empty candidate set) re-judged with a different NON-payroll apparent_category must NOT reuse
    the prior verdict — apparent_category is shown to the judge, so it belongs in the key."""
    cache: SourcingCache = {}
    snap = _snapshot([("docchecking00000", [_txn("250.00", "MYSTERY", "2026-05-05")])])

    run1 = _with_stage_a(snap, {"250.00": ("in", "vendor")})
    stub1 = StubJudge(value="no")
    await produce_stage_b_sourcing_tags(run1, reasoner=stub1, cache=cache)
    assert len(stub1.calls) == 1

    # Same raw deposit, a different non-payroll category (no candidates either way) → cache MISS.
    run2 = _with_stage_a(snap, {"250.00": ("in", "gift")})
    stub2 = StubJudge(value="no")
    await produce_stage_b_sourcing_tags(run2, reasoner=stub2, cache=cache)
    assert len(stub2.calls) == 1  # re-judged, not a stale content-id-only cache hit


async def test_absent_tags_layer_is_left_untouched() -> None:
    # Stage A never ran → tags absent → Stage B is a no-op (does not fabricate a layer).
    snap = _snapshot([("docchecking00000", [_txn("500.00", "DEP", "2026-05-05")])])
    snap = snap.model_copy(update={"tags": TagsSection.missing()})
    out = await produce_stage_b_sourcing_tags(snap, reasoner=StubJudge())
    assert out.tags.absent is True
