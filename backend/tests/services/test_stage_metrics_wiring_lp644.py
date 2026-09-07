"""LP-644 §1 — the instrumentation is actually WIRED to the stages, not just correct in isolation.

`tests/ai/test_stage_metrics_lp644.py` pins the arithmetic. These pin the part that would otherwise
fail silently: a metrics object that no stage ever writes to reports a flawless zero, and a zero is
exactly what "this stage is cheap" looks like. The whole point of §1 is that the ticket's numbers
stop being projections — instrumentation that quietly measures nothing would leave §2-§5 sized off
the same guesses, with more confidence and no more evidence.

Keyless throughout: the stubs are the existing injected Reasoner seams.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.ai.stage_metrics import StageMetrics
from app.ai.tag_production import StageAResult, TagJudgment, TransactionJudgment
from app.services.tag_production import produce_stage_a_transaction_tags
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot

pytestmark = pytest.mark.anyio

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class _Reasoner:
    """Answers every subject in the batch, reporting fixed token counts."""

    def __init__(self, *, input_tokens: int = 120, output_tokens: int = 40) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    async def __call__(self, context_json: str) -> StageAResult:
        self.calls += 1
        ctx = json.loads(context_json)
        return StageAResult(
            judgments=[
                TransactionJudgment(
                    index=t["index"],
                    is_money_in=TagJudgment("in", 0.9, "stub"),
                    apparent_category=TagJudgment("payroll", 0.9, "stub"),
                )
                for t in ctx["transactions"]
            ],
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model="stub",
            truncated=False,
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


def _snapshot(raw_txns: list[dict[str, Any]]) -> Snapshot:
    field_sets = transaction_field_sets(
        {"transactions": raw_txns},
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    txns = build_transactions(field_sets, document_content_id="docstmt0000000000")
    entry = DocumentEntry(
        content_id="docstmt0000000000", document_type="bank_statement", transactions=txns
    )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present([entry]),
    )


async def test_stage_a_records_one_call_per_batch_with_its_tokens() -> None:
    # 20 distinct transactions at a batch size of 15 → two calls. The count is what LP-644's
    # "12 Stage A calls" claim gets checked against.
    snapshot = _snapshot([_txn(amount=f"{i + 1}.00") for i in range(20)])
    reasoner = _Reasoner()
    metrics = StageMetrics()

    await produce_stage_a_transaction_tags(snapshot, reasoner=reasoner, metrics=metrics)

    assert reasoner.calls == 2
    assert metrics.calls == 2
    assert metrics.input_tokens == 240
    assert metrics.output_tokens == 80
    assert metrics.latency_seconds > 0
    assert metrics.wall_seconds >= metrics.latency_seconds  # the stage contains its own calls


async def test_a_cache_hit_records_no_call() -> None:
    # §3's entire premise is that a re-run should not re-pay. If a cached subject still counted as a
    # call, §3's measured saving would read as zero and the ticket's biggest item would look dead.
    snapshot = _snapshot([_txn(amount="10.00")])
    cache: dict[str, Any] = {}
    first = _Reasoner()
    await produce_stage_a_transaction_tags(snapshot, reasoner=first, cache=cache)

    second = _Reasoner()
    metrics = StageMetrics()
    await produce_stage_a_transaction_tags(snapshot, reasoner=second, cache=cache, metrics=metrics)

    assert second.calls == 0
    assert metrics.calls == 0
    assert metrics.latency_seconds == 0.0


async def test_metrics_are_optional_and_change_nothing_when_omitted() -> None:
    # Every stage takes `metrics` as an optional keyword. A caller that passes none — every existing
    # test, and any path not yet threaded — must get byte-identical tags.
    snapshot = _snapshot([_txn(amount="10.00"), _txn(amount="20.00")])

    without = await produce_stage_a_transaction_tags(snapshot, reasoner=_Reasoner())
    with_metrics = await produce_stage_a_transaction_tags(
        snapshot, reasoner=_Reasoner(), metrics=StageMetrics()
    )

    assert without.tags.by_subject == with_metrics.tags.by_subject


async def test_a_stage_with_nothing_to_do_reports_zero_rather_than_stale_numbers() -> None:
    snapshot = _snapshot([])
    metrics = StageMetrics()

    await produce_stage_a_transaction_tags(snapshot, reasoner=_Reasoner(), metrics=metrics)

    assert metrics.calls == 0
    assert metrics.wall_seconds == 0.0
