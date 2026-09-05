"""LP-644 §2 — concurrency must not move a verdict, pinned tag-for-tag.

The §0 argument is that asking the same questions at the same time as each other, rather than one
after the next, cannot change an answer. That is true of the PROMPTS — untouched — and false of the
plumbing if the refactor is careless. Three ways it breaks, each silent:

* a closure capturing the loop variable sends every call the LAST batch's context, so every call
  succeeds and every tag is attributed to the wrong subject;
* results applied in COMPLETION order instead of input order, so the caches, the token totals and the
  breaker see a sequence that depends on which coroutine finished first;
* a shared judgement applied once per subject instead of once per call.

LP-635 pinned the serial and concurrent Stage-B paths against each other for exactly this reason.
These do the same for Stage A and materialization, and go one further: the stubs finish in REVERSE
order, so completion order and input order disagree on every run rather than by luck.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.ai.tag_production import StageAResult, TagJudgment, TransactionJudgment
from app.services import tag_production
from app.services.tag_production import produce_stage_a_transaction_tags
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import DocumentEntry, DocumentsSection, Snapshot

pytestmark = pytest.mark.anyio

_WHEN = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class _AmountCodedReasoner:
    """Answers each subject from its OWN amount, so a crossed context is detectable.

    Every judged category is derived from the transaction's amount rather than fixed, which is what
    makes mis-attribution visible: if batch contexts get crossed, tags land on the wrong
    transactions and the amount→category mapping stops holding.

    ``reverse_delay`` makes later calls finish FIRST, so completion order and input order disagree.
    """

    def __init__(self, *, reverse_delay: bool = False) -> None:
        self.reverse_delay = reverse_delay
        self.contexts: list[list[str]] = []

    async def __call__(self, context_json: str) -> StageAResult:
        ctx = json.loads(context_json)
        amounts = [str(t["amount"]) for t in ctx["transactions"]]
        self.contexts.append(amounts)
        if self.reverse_delay:
            # The first-dispatched call sleeps longest, so it returns last.
            await asyncio.sleep(0.02 / (len(self.contexts)))
        return StageAResult(
            judgments=[
                TransactionJudgment(
                    index=t["index"],
                    is_money_in=TagJudgment("in", 0.9, "stub"),
                    apparent_category=TagJudgment("payroll", 0.9, "stub"),
                    # The COUNTERPARTY carries the amount, so a crossed context shows up immediately.
                    # It has to be this tag rather than the category: `apparent_category` is checked
                    # against the fact-tag vocabulary and an off-vocabulary value is coerced to
                    # "unknown" — correctly — which would hide the very mis-attribution being tested.
                    counterparty=TagJudgment(f"party-{t['amount']}", 0.9, "stub"),
                )
                for t in ctx["transactions"]
            ],
            input_tokens=10,
            output_tokens=5,
            model="stub",
            truncated=False,
        )


def _txn(amount: str) -> dict[str, Any]:
    return {
        "date": "2026-05-05",
        "description": "DEPOSIT",
        "amount": amount,
        "transaction_type": "deposit",
    }


def _snapshot(count: int) -> Snapshot:
    field_sets = transaction_field_sets(
        {"transactions": [_txn(f"{i + 1}.00") for i in range(count)]},
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


async def _tags_at_concurrency(
    monkeypatch: pytest.MonkeyPatch, snapshot: Snapshot, bound: int, *, reverse: bool = False
) -> dict[str, dict[str, Any]]:
    monkeypatch.setattr(tag_production, "_MAX_CONCURRENT_BATCHES", bound)
    result = await produce_stage_a_transaction_tags(
        snapshot, reasoner=_AmountCodedReasoner(reverse_delay=reverse)
    )
    return {
        sid: {tag_id: tag.value for tag_id, tag in tags.items()}
        for sid, tags in result.tags.by_subject.items()
    }


async def test_stage_a_serial_and_concurrent_produce_identical_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 40 transactions at a batch size of 15 → three batches, so concurrency has something to do.
    snapshot = _snapshot(40)

    serial = await _tags_at_concurrency(monkeypatch, snapshot, 1)
    concurrent = await _tags_at_concurrency(monkeypatch, snapshot, 8)

    assert serial == concurrent
    assert len(serial) == 40


async def test_tags_are_identical_even_when_calls_finish_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE ONE THAT CATCHES APPLY-IN-COMPLETION-ORDER. With the stub finishing backwards, a refactor
    # that merged results as they arrived would attribute batch 3's judgments to batch 1's subjects.
    snapshot = _snapshot(40)

    serial = await _tags_at_concurrency(monkeypatch, snapshot, 1)
    reversed_completion = await _tags_at_concurrency(monkeypatch, snapshot, 8, reverse=True)

    assert serial == reversed_completion


async def test_every_transaction_keeps_the_category_coded_from_its_own_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE ONE THAT CATCHES THE LATE-BOUND CLOSURE. If every call received the last batch's context,
    # all calls still succeed and the tags are still well-formed — only wrong. Checking the
    # amount→category correspondence per subject is what makes that visible.
    snapshot = _snapshot(40)
    monkeypatch.setattr(tag_production, "_MAX_CONCURRENT_BATCHES", 8)

    result = await produce_stage_a_transaction_tags(snapshot, reasoner=_AmountCodedReasoner())

    for tags in result.tags.by_subject.values():
        amount = str(tags["txn.amount"].value)
        assert tags["txn.counterparty"].value == f"party-{amount}"


async def test_each_batch_is_sent_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # A dispatch that double-sends is invisible in the tags (the second answer overwrites with the
    # same value) but doubles the spend — and would corrupt §1's call count, which is the number
    # §2's own saving gets measured against.
    snapshot = _snapshot(40)
    monkeypatch.setattr(tag_production, "_MAX_CONCURRENT_BATCHES", 8)
    reasoner = _AmountCodedReasoner()

    await produce_stage_a_transaction_tags(snapshot, reasoner=reasoner)

    assert len(reasoner.contexts) == 3  # 40 subjects / batch size 15
    sent = [amount for amounts in reasoner.contexts for amount in amounts]
    assert len(sent) == len(set(sent)) == 40
