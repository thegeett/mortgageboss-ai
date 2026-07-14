"""Stage-A transaction tag production (LP-313) — keyless, via the injected Reasoner stub.

No live API key: every test injects a stub reasoner. Covers the tag contract, the direction
bug now being structurally impossible (all transactions tagged), fail-closed honesty
(omission / truncation / AI error → unknown-with-reason, never a fabricated value), the
passthrough-not-retyped rule, bounded batching, and cache-by-content.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.ai.tag_production import AIClientError, StageAResult, TagJudgment, TransactionJudgment
from app.services.tag_production import (
    TransactionTagCache,
    produce_stage_a_transaction_tags,
)
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot
from app.verification.snapshot.tag import TagProducedBy, TagRole, TagStage

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class StubReasoner:
    """A deterministic stand-in for the AI boundary. Records the batches it was asked about.

    ``per_index`` overrides the (is_money_in, apparent_category) values for a given 1-based
    index; ``omit`` drops those indices from the response; ``truncate`` sets the flag; ``error``
    raises AIClientError.
    """

    def __init__(
        self,
        *,
        is_money_in: str = "in",
        category: str = "payroll",
        confidence: float | None = 0.9,
        per_index: dict[int, tuple[str, str]] | None = None,
        omit: set[int] | None = None,
        truncate: bool = False,
        error: bool = False,
    ) -> None:
        self.is_money_in = is_money_in
        self.category = category
        self.confidence = confidence
        self.per_index = per_index or {}
        self.omit = omit or set()
        self.truncate = truncate
        self.error = error
        self.calls: list[list[int]] = []  # the indices seen per call

    async def __call__(self, context_json: str) -> StageAResult:
        ctx = json.loads(context_json)
        indices = [t["index"] for t in ctx["transactions"]]
        self.calls.append(indices)
        if self.error:
            raise AIClientError("stubbed transport failure")
        judgments: list[TransactionJudgment] = []
        for idx in indices:
            if idx in self.omit:
                continue
            mi, cat = self.per_index.get(idx, (self.is_money_in, self.category))
            judgments.append(
                TransactionJudgment(
                    index=idx,
                    is_money_in=TagJudgment(mi, self.confidence, "stub reason"),
                    apparent_category=TagJudgment(cat, self.confidence, "stub reason"),
                )
            )
        return StageAResult(
            judgments=judgments,
            input_tokens=10,
            output_tokens=5,
            model="stub",
            truncated=self.truncate,
        )


def _txn(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "date": "2026-05-05",
        "description": "PAYROLL DEPOSIT",
        "amount": "50.00",
        "transaction_type": "deposit",
    }
    base.update(kw)
    return base


def _snapshot(raw_txns: list[dict[str, Any]], *, doc_id: str = "docstmt0000000000") -> Snapshot:
    field_sets = transaction_field_sets({"transactions": raw_txns}, "bank_statement")
    txns = build_transactions(field_sets, document_content_id=doc_id)
    entry = DocumentEntry(content_id=doc_id, document_type="bank_statement", transactions=txns)
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present([entry]),
    )


def _tags_for(snap: Snapshot, txn_index: int) -> dict[str, Any]:
    entry = snap.documents.entries[0]
    assert entry.transactions is not None
    cid = entry.transactions[txn_index].content_id
    return snap.tags.by_subject[cid]


async def test_produces_the_stage_a_contract_per_transaction() -> None:
    snap = _snapshot([_txn(), _txn(amount="100.00", description="RENT")])
    out = await produce_stage_a_transaction_tags(snap, reasoner=StubReasoner())

    assert out.tags.is_present and len(out.tags.by_subject) == 2
    tags = _tags_for(out, 0)
    assert set(tags) == {"txn.amount", "txn.date", "txn.is_money_in", "txn.apparent_category"}

    mi = tags["txn.is_money_in"]
    assert mi.value == "in" and mi.produced_by is TagProducedBy.AI
    assert mi.tag_role is TagRole.STRUCTURAL_FACT and mi.stage is TagStage.A
    assert mi.confidence == 0.9 and mi.reasoning == "stub reason"
    # Each tag cites the transaction's content_id — never a position.
    cid = snap.documents.entries[0].transactions[0].content_id  # type: ignore[index]
    assert mi.source_facts == (cid,)
    assert tags["txn.apparent_category"].value == "payroll"

    # The raw layer is untouched.
    assert out.documents.entries[0].transactions == snap.documents.entries[0].transactions


async def test_every_transaction_is_tagged_no_direction_filter() -> None:
    """The AS-1 direction bug is gone: a 'transfer'/'ACH'/unlabelled deposit still gets an
    is_money_in from the AI's judgment — nothing is filtered out."""
    snap = _snapshot(
        [
            _txn(transaction_type="transfer", description="ONLINE TRANSFER"),
            _txn(transaction_type="ach", description="ACH CREDIT"),
            _txn(transaction_type=None, description="MOBILE DEPOSIT"),
        ]
    )
    # The stubbed judgment resolves each to "in" regardless of the messy raw label.
    out = await produce_stage_a_transaction_tags(snap, reasoner=StubReasoner(is_money_in="in"))

    assert len(out.tags.by_subject) == 3  # ALL tagged, none dropped
    for i in range(3):
        assert _tags_for(out, i)["txn.is_money_in"].value == "in"


async def test_passthrough_amount_and_date_are_parsed_not_retyped() -> None:
    snap = _snapshot([_txn(amount="8076.93", date="2026-05-05")])
    out = await produce_stage_a_transaction_tags(snap, reasoner=StubReasoner())
    tags = _tags_for(out, 0)

    amount = tags["txn.amount"]
    assert amount.value == "8076.93"  # the RAW value, verbatim
    assert amount.produced_by is TagProducedBy.PARSED and amount.confidence is None
    assert tags["txn.date"].value == "2026-05-05"
    assert tags["txn.date"].produced_by is TagProducedBy.PARSED


async def test_omitted_tag_becomes_unknown_with_reason_not_defaulted() -> None:
    snap = _snapshot([_txn()])
    out = await produce_stage_a_transaction_tags(snap, reasoner=StubReasoner(omit={1}))
    tags = _tags_for(out, 0)

    mi = tags["txn.is_money_in"]
    assert mi.value == "unknown"  # NOT defaulted to "in"
    assert mi.confidence is None  # no fabricated confidence
    assert mi.reasoning == "not returned by structuring pass"
    # Passthroughs still succeed even when the AI omits everything.
    assert tags["txn.amount"].value == "50.00"


async def test_ai_unknown_is_preserved_as_a_real_answer() -> None:
    """A genuine AI "unknown" (with its confidence/reasoning) is kept — distinct from the
    fallback unknown, which has a null confidence + a fallback reason."""
    snap = _snapshot([_txn()])
    stub = StubReasoner(per_index={1: ("unknown", "unknown")}, confidence=0.4)
    out = await produce_stage_a_transaction_tags(snap, reasoner=stub)
    mi = _tags_for(out, 0)["txn.is_money_in"]
    assert mi.value == "unknown" and mi.confidence == 0.4 and mi.reasoning == "stub reason"


async def test_off_vocabulary_value_is_coerced_to_unknown() -> None:
    snap = _snapshot([_txn()])
    stub = StubReasoner(per_index={1: ("inflow", "salary")})  # not in the allowed sets
    out = await produce_stage_a_transaction_tags(snap, reasoner=stub)
    tags = _tags_for(out, 0)
    assert tags["txn.is_money_in"].value == "unknown"
    assert tags["txn.apparent_category"].value == "unknown"


async def test_truncated_response_marks_missing_tags_unknown_with_reason() -> None:
    snap = _snapshot([_txn(), _txn(amount="9.00")])
    # One transaction (the batch's index 2) is cut off; the response is flagged truncated.
    # Batches sort by fingerprint, so we assert on the SET of outcomes, not input position.
    stub = StubReasoner(omit={2}, truncate=True)
    out = await produce_stage_a_transaction_tags(snap, reasoner=stub)

    outcomes = [_tags_for(out, i)["txn.is_money_in"] for i in range(2)]
    intact = [t for t in outcomes if t.value == "in"]
    truncated = [t for t in outcomes if t.value == "unknown"]
    assert len(intact) == 1  # the transaction that was returned
    assert len(truncated) == 1 and truncated[0].reasoning == "structuring response truncated"


async def test_ai_error_is_graceful_unknown_with_reason_no_crash() -> None:
    snap = _snapshot([_txn(), _txn(amount="12.00")])
    out = await produce_stage_a_transaction_tags(snap, reasoner=StubReasoner(error=True))

    for i in range(2):
        tags = _tags_for(out, i)
        assert tags["txn.is_money_in"].value == "unknown"
        assert tags["txn.is_money_in"].reasoning == "tag production failed"
        assert tags["txn.apparent_category"].value == "unknown"
        # Passthroughs are unaffected by the AI failure.
        assert tags["txn.amount"].value in {"50.00", "12.00"}


async def test_transactions_are_batched_in_bounded_groups() -> None:
    # 21 distinct-content transactions → 2 calls at a batch bound of 15.
    snap = _snapshot([_txn(amount=f"{i}.00", description=f"DEP {i}") for i in range(21)])
    stub = StubReasoner()
    await produce_stage_a_transaction_tags(snap, reasoner=stub)

    assert len(stub.calls) == 2
    assert sorted(len(c) for c in stub.calls) == [6, 15]  # 15 + 6 = 21 unique


async def test_identical_transactions_share_one_ai_call() -> None:
    # Three byte-identical deposits → one unique fingerprint → a single judged transaction.
    snap = _snapshot([_txn(), _txn(), _txn()])
    stub = StubReasoner()
    out = await produce_stage_a_transaction_tags(snap, reasoner=stub)

    assert len(stub.calls) == 1 and len(stub.calls[0]) == 1  # one representative judged
    assert len(out.tags.by_subject) == 3  # ...but all three transactions carry tags
    for i in range(3):
        assert _tags_for(out, i)["txn.is_money_in"].value == "in"


async def test_cache_reuses_unchanged_transaction_and_reproduces_changed_one() -> None:
    cache: TransactionTagCache = {}
    first_snap = _snapshot([_txn(amount="50.00"), _txn(amount="99.00")])
    stub1 = StubReasoner()
    await produce_stage_a_transaction_tags(first_snap, reasoner=stub1, cache=cache)
    assert len(stub1.calls) == 1 and len(cache) == 2  # both fingerprints cached

    # Re-run with the SAME two transactions plus one CHANGED amount; only the new fingerprint
    # is a miss, so the reasoner is called for exactly one transaction.
    second_snap = _snapshot([_txn(amount="50.00"), _txn(amount="99.00"), _txn(amount="123.00")])
    stub2 = StubReasoner()
    out = await produce_stage_a_transaction_tags(second_snap, reasoner=stub2, cache=cache)

    assert len(stub2.calls) == 1 and len(stub2.calls[0]) == 1  # only the changed one re-produced
    assert len(out.tags.by_subject) == 3
    assert len(cache) == 3


async def test_no_transactions_yields_present_empty_tags_layer() -> None:
    snap = Snapshot(loan_file_id=uuid4(), run_id=uuid4(), created_at=_WHEN)
    out = await produce_stage_a_transaction_tags(snap, reasoner=StubReasoner())
    assert out.tags.is_present and out.tags.by_subject == {}


async def test_out_of_range_indices_fail_closed_never_misattribute() -> None:
    """A model that ignores the 1-based indices it was given (e.g. echoes 0-based) must NOT
    have its judgments trusted — the whole batch fails closed to unknown-with-reason, because a
    tag bound to the WRONG transaction is worse than an honest unknown."""

    async def zero_based(context_json: str) -> StageAResult:
        ctx = json.loads(context_json)
        # Echo each transaction's index MINUS ONE — an out-of-range (0-based) mapping.
        judgments = [
            TransactionJudgment(
                index=t["index"] - 1,
                is_money_in=TagJudgment("in", 0.9, "shifted"),
                apparent_category=TagJudgment("payroll", 0.9, "shifted"),
            )
            for t in ctx["transactions"]
        ]
        return StageAResult(
            judgments=judgments, input_tokens=10, output_tokens=5, model="stub", truncated=False
        )

    snap = _snapshot([_txn(), _txn(amount="9.00")])
    out = await produce_stage_a_transaction_tags(snap, reasoner=zero_based)
    for i in range(2):
        tags = _tags_for(out, i)
        assert tags["txn.is_money_in"].value == "unknown"  # not the mis-mapped "in"
        assert (
            tags["txn.is_money_in"].reasoning
            == "structuring pass returned unrecognized transaction indices"
        )
        assert tags["txn.amount"].value in {"50.00", "9.00"}  # passthroughs unaffected


async def test_returned_but_malformed_tag_uses_the_accurate_reason() -> None:
    """A transaction that IS returned but with one tag value missing gets a 'malformed' reason,
    not the 'not returned' reason reserved for a wholly-omitted transaction."""

    async def half_returned(context_json: str) -> StageAResult:
        ctx = json.loads(context_json)
        idx = ctx["transactions"][0]["index"]
        return StageAResult(
            judgments=[
                TransactionJudgment(
                    index=idx,
                    is_money_in=TagJudgment("in", 0.9, "ok"),
                    apparent_category=None,  # this tag came back malformed / missing
                )
            ],
            input_tokens=10,
            output_tokens=5,
            model="stub",
            truncated=False,
        )

    snap = _snapshot([_txn()])
    out = await produce_stage_a_transaction_tags(snap, reasoner=half_returned)
    tags = _tags_for(out, 0)
    assert tags["txn.is_money_in"].value == "in"  # the returned tag survives
    cat = tags["txn.apparent_category"]
    assert cat.value == "unknown"
    assert cat.reasoning == "tag value missing or malformed in structuring response"
