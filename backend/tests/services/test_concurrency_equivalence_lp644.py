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
from app.ai.client import AIClientError
from app.ai.concurrency import dispatch_bounded
from app.ai.tag_production import StageAResult, TagJudgment, TransactionJudgment
from app.services import tag_production
from app.services.tag_production import produce_stage_a_transaction_tags
from app.verification.snapshot.documents_section import build_transactions, transaction_field_sets
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Field,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.tag_materialization import ai as ai_module
from app.verification.tag_materialization import producer
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
)
from app.verification.tag_materialization.producer import materialize_tags

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


# --------------------------------------------------------------------------- #
# `dispatch_bounded` itself — the helper all three call sites now rest on.
#
# The Stage-A tests above exercise it only through the happy path. These pin the
# three properties its callers actually depend on and that a stub reasoner never
# reaches: input-order outcomes, a gate that stops DISPATCH rather than counting,
# and siblings collected before a bug is re-raised.
# --------------------------------------------------------------------------- #
async def test_dispatch_bounded_returns_outcomes_in_input_order() -> None:
    # The stubs finish BACKWARDS, so completion order and input order disagree on every run.
    async def _call(i: int) -> int:
        await asyncio.sleep(0.02 / (i + 1))
        return i

    outcomes = await dispatch_bounded(
        [lambda i=i: _call(i) for i in range(6)],  # type: ignore[misc]
        concurrency=6,
    )

    assert [o.result for o in outcomes] == list(range(6))
    assert all(o.attempted and o.error is None for o in outcomes)


async def test_the_gate_stops_dispatch_rather_than_only_counting() -> None:
    # THE PROPERTY LP-635 PAID FOR: the breaker is fed in the caller's apply loop, which cannot begin
    # until every call has returned. Without a gate an outage pays for the whole stage. At
    # concurrency 1 the ordering is deterministic, so the count is exact rather than a bound.
    attempts = 0

    async def _fail() -> int:
        nonlocal attempts
        attempts += 1
        raise AIClientError("backend down")

    outcomes = await dispatch_bounded([_fail] * 6, concurrency=1, stop_after_failures=3)

    assert attempts == 3  # the remaining three were never MADE, not merely not counted
    assert [o.attempted for o in outcomes] == [True, True, True, False, False, False]
    assert all(isinstance(o.error, AIClientError) for o in outcomes[:3])
    assert all(o.error is None and o.result is None for o in outcomes[3:])


async def test_a_success_resets_the_gates_consecutive_count() -> None:
    # "Consecutive", not "total" — a stage that fails, recovers and fails again must run to the end.
    calls: list[str] = []

    async def _fail() -> int:
        calls.append("fail")
        raise AIClientError("transient")

    async def _ok() -> int:
        calls.append("ok")
        return 1

    plan = [_fail, _fail, _ok, _fail, _fail]
    outcomes = await dispatch_bounded(plan, concurrency=1, stop_after_failures=3)

    assert calls == ["fail", "fail", "ok", "fail", "fail"]
    assert all(o.attempted for o in outcomes)


async def test_a_bug_is_raised_only_after_every_sibling_has_been_collected() -> None:
    # A bare `gather` propagates the first exception WITHOUT cancelling its siblings, leaving model
    # calls running against a caller that has already unwound — billed, unawaited, and surfacing
    # later as "Task exception was never retrieved". Every call already IN FLIGHT must finish before
    # we unwind. (Calls not yet dispatched are a different matter: the bug closes the gate, so they
    # are skipped rather than made — which is the point of raising on a bug at all.)
    finished: list[int] = []

    async def _ok(i: int) -> int:
        await asyncio.sleep(0.02)
        finished.append(i)
        return i

    async def _bug() -> int:
        await asyncio.sleep(0.005)  # every sibling is dispatched and still running when this raises
        raise ValueError("a bug, not an outage")

    with pytest.raises(ValueError, match="a bug"):
        await dispatch_bounded(
            [lambda: _ok(0), lambda: _ok(1), lambda: _ok(2), _bug],  # type: ignore[list-item]
            concurrency=4,
        )

    assert sorted(finished) == [0, 1, 2]


async def test_the_raised_bug_is_the_input_order_first_one_not_the_fastest() -> None:
    # A serial loop would have stopped at the FIRST call, so that is the exception the caller sees —
    # not whichever coroutine happened to raise soonest.
    async def _slow_bug() -> int:
        await asyncio.sleep(0.02)
        raise ValueError("first in input order")

    async def _fast_bug() -> int:
        raise ValueError("first in completion order")

    with pytest.raises(ValueError, match="first in input order"):
        await dispatch_bounded([_slow_bug, _fast_bug], concurrency=2)


# --------------------------------------------------------------------------- #
# Materialization — BOTH levels, which the Stage-A tests above do not reach.
#
# The commit parallelises three places and pins one. These pin the other two: the
# OUTER loop over AI groups (`producer._MAX_CONCURRENT_GROUPS`) and the INNER loop
# over a group's batches (`ai._MAX_CONCURRENT_BATCHES`), which multiply. Each
# document's tags are coded from its OWN context, so a crossed batch or a merge in
# completion order shows up as a tag on the wrong subject rather than as a crash.
# --------------------------------------------------------------------------- #


class _SubjectCodedGroupReasoner:
    """Answers each subject from its own ``employer_name``, so mis-attribution is visible."""

    def __init__(
        self, prefix: str, shorts: tuple[str, ...], *, reverse_delay: bool = False
    ) -> None:
        self.prefix = prefix
        self.shorts = shorts
        self.reverse_delay = reverse_delay
        self.calls = 0

    async def __call__(self, context_json: str) -> AiGroupResult:
        self.calls += 1
        if self.reverse_delay:
            await asyncio.sleep(0.02 / self.calls)  # the first-dispatched batch returns last
        subjects = json.loads(context_json)["subjects"]
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        short: AiTagJudgment(
                            "residence"  # `id.current_address_type` has a closed vocabulary
                            if short == "current_address_type"
                            else f"{self.prefix}-{s['employer_name']}",
                            0.9,
                            "stub",
                        )
                        for short in self.shorts
                    },
                )
                for s in subjects
            ],
            1,
            1,
            "stub",
            False,
        )


_MATERIALIZATION_GROUPS = {
    # Both declare `applies_to: all`, so both enumerate EVERY document — two groups over the same
    # subjects is what makes the outer level's merge order observable.
    "id_name": ("name_normalized",),
    "id_address": ("address_normalized", "current_address_type"),
}


def _document_snapshot(count: int) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=_WHEN,
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    content_id=f"doc{i:04d}",
                    document_type="w2",
                    fields={"employer_name": Field(value=f"E{i}", source="extracted")},
                )
                for i in range(count)
            ]
        ),
        mismo=MismoSection.present({}),
        tags=TagsSection.present({}),
    )


async def _materialized(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: Snapshot,
    *,
    groups: int,
    batches: int,
    reverse: bool = False,
) -> dict[str, dict[str, Any]]:
    monkeypatch.setattr(producer, "_MAX_CONCURRENT_GROUPS", groups)
    monkeypatch.setattr(ai_module, "_MAX_CONCURRENT_BATCHES", batches)
    out = await materialize_tags(
        snapshot,
        ai_reasoners={
            key: _SubjectCodedGroupReasoner(key, shorts, reverse_delay=reverse)
            for key, shorts in _MATERIALIZATION_GROUPS.items()
        },
        only_subjects=frozenset({"document"}),
        only_groups=frozenset(_MATERIALIZATION_GROUPS),
    )
    return {
        sid: {tag_id: tag.value for tag_id, tag in tags.items()}
        for sid, tags in out.tags.by_subject.items()
    }


async def test_materialization_serial_and_concurrent_produce_identical_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 40 documents at a batch size of 15 → three batches per group, two groups: both levels engage.
    snapshot = _document_snapshot(40)

    serial = await _materialized(monkeypatch, snapshot, groups=1, batches=1)
    concurrent = await _materialized(monkeypatch, snapshot, groups=4, batches=8)

    assert serial == concurrent
    assert len(serial) == 40


async def test_materialization_tags_survive_calls_finishing_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE ONE THAT CATCHES APPLY- OR MERGE-IN-COMPLETION-ORDER at both levels at once.
    snapshot = _document_snapshot(40)

    serial = await _materialized(monkeypatch, snapshot, groups=1, batches=1)
    reversed_completion = await _materialized(
        monkeypatch, snapshot, groups=4, batches=8, reverse=True
    )

    assert serial == reversed_completion


async def test_every_document_keeps_the_tags_coded_from_its_own_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE ONE THAT CATCHES A LATE-BOUND CLOSURE at either level: every call still succeeds and every
    # tag is still well-formed, only attributed to the wrong document.
    snapshot = _document_snapshot(40)

    tags = await _materialized(monkeypatch, snapshot, groups=4, batches=8)

    for i in range(40):
        subject = tags[f"doc{i:04d}"]
        assert subject["id.name_normalized"] == f"id_name-E{i}"
        assert subject["id.address_normalized"] == f"id_address-E{i}"


async def test_an_oversized_payload_does_not_close_the_dispatch_gate() -> None:
    """LP-644 §2 review — the gate must borrow the breaker's POLICY, not just its number.

    `AiInfraBreaker` RESETS its counter on an oversized payload: the backend answered and refused
    that call's shape, and "one oversized document is not an outage". The dispatch gate reads its
    threshold from that same breaker, so it has to agree about what advances the count. Counting
    oversized errors here closed the gate on a CONTENT problem — and a closed gate is not a failed
    call, it is a call never made: every remaining batch resolved unknown-with-reason without
    reaching the model, without the breaker tripping and without a log line, where serially those
    subjects would have been judged normally. That is a verdict moving on a content problem, which
    is the one thing LP-644 §0 promises concurrency cannot do.
    """
    import httpx
    from anthropic import BadRequestError
    from app.ai.client import AIClientError
    from app.ai.concurrency import dispatch_bounded
    from app.verification.tag_materialization.breaker import AiInfraBreaker

    request = httpx.Request("POST", "https://x/y")

    def _oversized() -> AIClientError:
        err = AIClientError("too big")
        err.__cause__ = BadRequestError(
            "too big", response=httpx.Response(400, request=request, json={}), body=None
        )
        return err

    breaker = AiInfraBreaker()

    async def always_oversized() -> str:
        raise _oversized()

    # Serially, ten oversized batches are ten judged-and-refused calls: the breaker's counter never
    # advances, so nothing is skipped. The gate must reach the same conclusion.
    outcomes = await dispatch_bounded(
        [always_oversized] * 10,
        concurrency=1,
        stop_after_failures=breaker.threshold,
        counts_as_failure=breaker.counts_toward_trip,
    )

    assert all(o.attempted for o in outcomes), (
        "an oversized payload is a content problem, not an outage — every call must still be made"
    )
    assert all(o.error is not None for o in outcomes)


async def test_a_real_outage_still_closes_the_gate_with_the_policy_applied() -> None:
    """The other side of the boundary: passing a policy must not disarm the gate.

    Connection failures are exactly what the breaker counts, so the gate must still stop dispatch —
    otherwise the fix above would have bought a verdict at the cost of the outage protection LP-635
    was opened to add.
    """
    import httpx
    from app.ai.client import AIClientError
    from app.ai.concurrency import dispatch_bounded
    from app.verification.tag_materialization.breaker import AiInfraBreaker

    request = httpx.Request("POST", "https://x/y")
    breaker = AiInfraBreaker()

    async def always_down() -> str:
        err = AIClientError("conn")
        err.__cause__ = httpx.ConnectError("boom", request=request)
        raise err

    outcomes = await dispatch_bounded(
        [always_down] * 20,
        concurrency=1,
        stop_after_failures=breaker.threshold,
        counts_as_failure=breaker.counts_toward_trip,
    )

    attempted = [o for o in outcomes if o.attempted]
    assert len(attempted) == breaker.threshold, (
        "dispatch must stop at the breaker's threshold, not grind the whole stage"
    )
    assert all(o.not_attempted for o in outcomes[breaker.threshold :])
