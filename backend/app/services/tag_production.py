"""Stage-A tag production orchestrator (LP-313) — transactions.

The deterministic half of Stage-A production (the "assembler + judge wiring", cloned from
``services/cross_source.py``): it reads the raw transactions from a frozen snapshot, drives
the AI structuring pass in BOUNDED batches, and writes the produced fact-tags into the
snapshot's tags layer (LP-312) — each tag citing its transaction's stable ``content_id``.
The raw layer is never touched; a new frozen snapshot is returned.

Design (§3D + the ticket):

* **Passthrough vs AI-judged.** ``txn.amount`` / ``txn.date`` are already parsed — they are
  carried through verbatim (``produced_by="parsed"``, ``confidence=None``); the AI never
  re-reads a number (which would invite hallucinated digits). ``txn.is_money_in`` /
  ``txn.apparent_category`` are AI-judged (``produced_by="ai"``, the model's confidence).
* **Every transaction is tagged.** There is NO ``direction=="credit"`` filter anywhere — the
  original AS-1 bug is structurally impossible; a "transfer"/"ACH"/unlabelled deposit still
  gets an ``is_money_in`` from the AI's judgment of meaning.
* **Bounded batches** (``_BATCH_SIZE``) so position-degradation can't creep in on long files.
* **Fail-closed honesty.** An AI failure/timeout, a truncated response, or an omitted/off-
  vocabulary value all yield ``value="unknown"`` WITH a reason — never a fabricated value.
  A genuine AI ``"unknown"`` is preserved as-is (distinct from the fallback).
* **Cache-by-content.** AI judgments are keyed by the transaction's content fingerprint, so
  identical transactions share one call and an unchanged transaction reuses its judgment on a
  re-run; only successes are cached (a failure retries next run). content_ids never reach the
  AI — the batch addresses transactions by a 1-based index and the id is attached here.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from time import perf_counter

import structlog

from app.ai.concurrency import dispatch_bounded
from app.ai.cost import estimate_cost
from app.ai.stage_metrics import StageMetrics
from app.ai.tag_production import (
    APPARENT_CATEGORY_VALUES,
    IS_MONEY_IN_VALUES,
    StageAResult,
    TagJudgment,
    reason_stage_a_transactions,
)
from app.core.config import resolve_model, settings
from app.verification.snapshot.content_id import content_fingerprint
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import Snapshot, TagsSection, TransactionRecord
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_transactions as _all_transactions
from app.verification.snapshot.traversal import field_value as _raw
from app.verification.tag_materialization.breaker import AiInfraBreaker

logger = structlog.get_logger(__name__)

# Injected so a keyless test supplies a deterministic stub (mirrors the cross-source seam).
Reasoner = Callable[[str], Awaitable[StageAResult]]

# The largest batch sent to one AI call. Kept small so a long statement can't degrade the
# model's attention over its tail (§3D bounded batches). Within the ticket's 15-20 bound.
_BATCH_SIZE = 15

#: LP-644 §2 — how many of this stage's batches may be in flight at once. EIGHT, matching Stage B's
#: `_MAX_CONCURRENT_JUDGMENTS` rather than picking a second number: the two stages draw on the same
#: environment budget, they never overlap (Stage A completes before Stage B starts), and LP-644 §4
#: is where the bound gets raised — for both at once, on measured TPM rather than on arithmetic.
#: A stage inventing its own bound is how the ceiling stops being knowable.
_MAX_CONCURRENT_BATCHES = 8

# Tag ids (the vocabulary keys these tags are stored under in the tags layer).
_TAG_AMOUNT = "txn.amount"
_TAG_DATE = "txn.date"
_TAG_IS_MONEY_IN = "txn.is_money_in"
_TAG_APPARENT_CATEGORY = "txn.apparent_category"
_TAG_COUNTERPARTY = "txn.counterparty"
_TAG_VERSION = 1

# Reasons attached to an unknown-with-reason tag so a human sees WHY it is unknown.
_REASON_FAILED = "tag production failed"
_REASON_TRUNCATED = "structuring response truncated"
_REASON_NOT_RETURNED = "not returned by structuring pass"
_REASON_MALFORMED = "tag value missing or malformed in structuring response"
_REASON_BAD_INDEX = "structuring pass returned unrecognized transaction indices"
_REASON_OFF_VOCAB = "model returned an out-of-vocabulary value; coerced to unknown"

# The AI-judged tags and their allowed value sets (from the fact-tag vocabulary).
_AI_TAG_ALLOWED = {
    _TAG_IS_MONEY_IN: frozenset(IS_MONEY_IN_VALUES),
    _TAG_APPARENT_CATEGORY: frozenset(APPARENT_CATEGORY_VALUES),
}


@dataclass(frozen=True)
class _Judged:
    """One transaction's resolved AI judgments (either tag may be ``None`` = unresolved)."""

    is_money_in: TagJudgment | None
    apparent_category: TagJudgment | None
    reason: str  # the reason to attach when a tag is None (why it is unknown)
    # bug-001 — LAST and defaulted, deliberately: the failure paths construct this POSITIONALLY as
    # `_Judged(None, None, reason)`, so a field inserted before `reason` silently rebinds it.
    counterparty: TagJudgment | None = None


TransactionTagCache = dict[str, _Judged]


def _fingerprint(txn: TransactionRecord) -> str:
    """A content fingerprint of a transaction's raw facts (the cache key).

    Keyed on the four raw Fields (not the content_id), so identical-content transactions
    share one AI judgment and an unchanged transaction is a cache hit across re-runs.
    """
    return content_fingerprint(
        {
            "date": _raw(txn.date),
            "amount": _raw(txn.amount),
            "direction": _raw(txn.direction),
            "description": _raw(txn.description),
        }
    )


def _build_context(batch: list[TransactionRecord]) -> dict[str, object]:
    """The deterministic batch context sent to the reasoner — transactions by 1-based index.

    content_ids are NOT sent; the model addresses transactions by ``index`` and the id is
    reattached here (robust to the model mangling opaque ids). The description is already
    redacted at snapshot-build (LP-302a), so nothing raw-PII leaves in the prompt.
    """
    return {
        "transactions": [
            {
                "index": i,
                "date": _raw(txn.date),
                "amount": _raw(txn.amount),
                "direction": _raw(txn.direction),
                "description": _raw(txn.description),
            }
            for i, txn in enumerate(batch, start=1)
        ]
    }


def _chunks(
    items: list[tuple[str, TransactionRecord]], size: int
) -> list[list[tuple[str, TransactionRecord]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def produce_stage_a_transaction_tags(
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    cache: TransactionTagCache | None = None,
    breaker: AiInfraBreaker | None = None,
    metrics: StageMetrics | None = None,
) -> Snapshot:
    """Produce Stage-A transaction tags and write them into the snapshot's tags layer.

    Returns a NEW frozen snapshot with ``tags`` populated (the raw layer untouched). ``cache``
    (optional, mutated in place) reuses AI judgments across runs by content fingerprint — only
    successful judgments are stored, so a failed/truncated transaction retries next run.

    ``metrics`` (LP-644 §1, optional, mutated in place) records call count, tokens and latency.
    Instrumentation only — nothing here reads it back, so a caller passing None gets byte-identical
    behaviour.
    """
    reason_fn = reasoner if reasoner is not None else reason_stage_a_transactions
    persistent = cache if cache is not None else {}
    stage_started = perf_counter()

    transactions = _all_transactions(snapshot)
    if not transactions:
        # Present-empty tags layer — there is nothing to structure (not absent/failed).
        return snapshot.model_copy(update={"tags": TagsSection.present({})})

    # Fingerprint each transaction ONCE (json.dumps + sha256); reused for batching AND final
    # assembly, so a row's raw facts are never hashed twice per run.
    fingerprinted: list[tuple[str, TransactionRecord]] = [
        (_fingerprint(txn), txn) for txn in transactions
    ]

    # Unique content fingerprints not already cached — one representative each, sorted for a
    # deterministic batch composition (reproducibility is load-bearing).
    representatives: list[tuple[str, TransactionRecord]] = []
    seen: set[str] = set()
    for fp, txn in fingerprinted:
        if fp in persistent or fp in seen:
            continue
        seen.add(fp)
        representatives.append((fp, txn))
    representatives.sort(key=lambda pair: pair[0])

    resolved: TransactionTagCache = dict(persistent)
    input_tokens = output_tokens = 0
    # Pricing must be keyed on the model that ACTUALLY ran. Under Bedrock that is the
    # cross-region inference-profile id, not the tier value this module asks for, so
    # reading the tier setting here would price the call against the wrong key the moment
    # the Bedrock rows in cost.py stop matching the direct-API rates. StageAResult.model
    # carries the completion's own resolved id — the authoritative answer.
    invoked_model: str | None = None

    # LP-644 §2 — PLAN → DISPATCH → APPLY. The batches are settled as a set first, which is what
    # lets them be asked concurrently and still applied in a fixed order below. The prompt, the
    # context and the resolution logic are untouched, so a verdict cannot move (LP-644 §0); a test
    # pins the serial and concurrent paths tag-for-tag.
    batches = _chunks(representatives, _BATCH_SIZE)
    # Contexts are built EAGERLY, before anything is dispatched, and bound with `partial` rather than
    # captured in a lambda. A closure over the loop variable would hand every call the LAST batch's
    # context — the classic way this refactor breaks silently, because the calls all succeed and
    # every tag is simply attributed to the wrong transaction. `partial` makes that unexpressible.
    contexts = [json.dumps(_build_context([txn for _, txn in batch])) for batch in batches]
    outcomes = await dispatch_bounded(
        [partial(reason_fn, context) for context in contexts],
        concurrency=_MAX_CONCURRENT_BATCHES,
        # The gate is the breaker's OWN threshold, handed down rather than chosen again here: not a
        # second policy about when to give up, the same one applied where the calls are made.
        stop_after_failures=None if breaker is None else breaker.threshold,
        # The breaker's failure POLICY as well as its number: an oversized payload resets its
        # counter, so it must not close this gate either (LP-644 §2 review).
        counts_as_failure=None if breaker is None else breaker.counts_toward_trip,
    )

    # APPLY, IN THE ORIGINAL ORDER — deterministic on purpose. The cache, the token totals, the
    # model attribution and the BREAKER all see the batches in the sequence they had when this loop
    # was serial, so "consecutive failures" keeps the meaning it was given.
    for batch, outcome in zip(batches, outcomes, strict=True):
        if outcome.not_attempted:
            # The gate closed before this batch was asked. Same fail-closed resolution as a failure
            # — unknown-with-reason, uncached, retried next run — but the breaker is NOT fed: no
            # call was made, so there is no failure to count, and counting one would let a single
            # outage close the breaker twice as fast as its threshold says.
            for fp, _ in batch:
                resolved[fp] = _Judged(None, None, _REASON_FAILED)
            continue
        if outcome.error is not None:
            # Fail-closed: the whole batch's AI tags become unknown-with-reason (the
            # passthroughs still succeed). Not cached → retried on the next run.
            logger.warning("stage_a_batch_failed", size=len(batch))
            for fp, _ in batch:
                resolved[fp] = _Judged(None, None, _REASON_FAILED)
            # LP-635 — see the identical guard in `tag_materialization.ai`. Stage A shares the run's
            # breaker, so an outage that starts here is counted with the ones that follow it rather
            # than each stage forgiving the backend separately.
            if breaker is not None:
                breaker.record_failure(outcome.error)
            continue
        result = outcome.result
        assert result is not None  # attempted, no error → a result (CallOutcome's contract)
        if breaker is not None:
            breaker.record_success()

        input_tokens += result.input_tokens
        output_tokens += result.output_tokens
        invoked_model = result.model
        if metrics is not None:
            metrics.record_call(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                seconds=outcome.seconds,
            )
        by_index = {j.index: j for j in result.judgments}
        # The batch addresses transactions by 1-based index (1..len(batch)); the model must
        # echo those. A returned index OUTSIDE that set (e.g. a 0-based echo) means the model
        # did not honor the mapping — its index→transaction correspondence is untrustworthy,
        # so trust NONE of it and fail closed. A tag mis-attributed to the wrong transaction is
        # far worse than an honest unknown. A partial (truncated) response is still a SUBSET of
        # the expected set and is handled normally below.
        expected = set(range(1, len(batch) + 1))
        if not set(by_index) <= expected:
            logger.warning(
                "stage_a_batch_bad_indices", size=len(batch), returned=len(result.judgments)
            )
            for fp, _ in batch:
                resolved[fp] = _Judged(None, None, _REASON_BAD_INDEX)
            continue
        for index, (fp, _) in enumerate(batch, start=1):
            judgment = by_index.get(index)
            if judgment is None:
                # Omitted — truncated tail vs a plain omission (both honest, distinct reason).
                reason = _REASON_TRUNCATED if result.truncated else _REASON_NOT_RETURNED
                resolved[fp] = _Judged(None, None, reason)
                continue
            # Returned, but a tag value may still be missing/malformed — record that (not
            # "not returned"), so a human triaging the unknown tag sees the accurate cause.
            entry = _Judged(
                judgment.is_money_in,
                judgment.apparent_category,
                _REASON_MALFORMED,
                counterparty=judgment.counterparty,
            )
            resolved[fp] = entry
            # Cache only a COMPLETE judgment, so a partial retries next run.
            if entry.is_money_in is not None and entry.apparent_category is not None:
                persistent[fp] = entry

    # LP-644 §1 — set BEFORE the log line, so the stage's own wall time (fingerprinting and tag
    # building included, not just the calls) is what gets reported and what the run subtracts.
    if metrics is not None:
        metrics.wall_seconds = perf_counter() - stage_started

    if input_tokens or output_tokens:
        # invoked_model is set whenever a batch succeeded, and tokens are only accumulated
        # on success — so the fallback is unreachable, and resolves rather than guessing.
        logger.info(
            "stage_a_production_done",
            transactions=len(transactions),
            unique=len(representatives),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=estimate_cost(
                model=invoked_model or resolve_model(settings.anthropic_model_reasoning),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            # LP-644 §1 — the measured stand-ins for the ticket's projected 12 calls at a 4.3s mean.
            **(metrics.as_log_fields() if metrics is not None else {}),
        )

    by_subject = {
        txn.content_id: _build_transaction_tags(txn, resolved[fp]) for fp, txn in fingerprinted
    }
    return snapshot.model_copy(update={"tags": TagsSection.present(by_subject)})


def _build_transaction_tags(txn: TransactionRecord, judged: _Judged) -> dict[str, Tag]:
    """The four Stage-A tags for one transaction, each citing its content_id."""
    return {
        _TAG_AMOUNT: _passthrough_tag(txn.amount, txn.content_id),
        _TAG_DATE: _passthrough_tag(txn.date, txn.content_id),
        _TAG_IS_MONEY_IN: _ai_tag(
            _TAG_IS_MONEY_IN, judged.is_money_in, txn.content_id, judged.reason
        ),
        _TAG_APPARENT_CATEGORY: _ai_tag(
            _TAG_APPARENT_CATEGORY, judged.apparent_category, txn.content_id, judged.reason
        ),
        # bug-001 — a FREE STRING, so it takes the open-vocabulary path: there is no value set to
        # check a creditor's name against, and inventing one would reject real names.
        _TAG_COUNTERPARTY: _ai_string_tag(judged.counterparty, txn.content_id, judged.reason),
    }


def _passthrough_tag(field: Field, content_id: str) -> Tag:
    """A parsed passthrough tag — the raw value carried verbatim; the AI never re-typed it.

    An absent raw field → ``value="unknown"`` (honest); a present-but-null value stays null.

    The value is carried EXACTLY as the snapshot holds it, which for money (``txn.amount``) is
    the exact decimal STRING (e.g. ``"50.00"``), never a JSON float — the whole system stores
    money as strings to avoid float precision loss (``Field.value`` rejects ``Decimal`` for this
    reason). The fact-tag vocabulary's ``number`` type is the SEMANTIC type; a numeric consumer
    coerces the string to ``Decimal`` (as everywhere money is handled), rather than us emitting a
    lossy float here. Re-typing the value would be the exact hallucination-of-digits risk the
    passthrough exists to avoid.
    """
    value = field.value if field.is_present else "unknown"
    return Tag(
        value=value,
        confidence=None,
        reasoning=None,
        source_facts=(content_id,),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=_TAG_VERSION,
        stage=TagStage.A,
    )


def _ai_tag(tag_id: str, judgment: TagJudgment | None, content_id: str, absent_reason: str) -> Tag:
    """An AI-judged tag — the model's value/confidence/reasoning, or unknown-with-reason.

    Omitted/failed → ``value="unknown"`` + ``absent_reason``. An off-vocabulary value → coerced
    to ``"unknown"`` (never accepted verbatim). A genuine AI ``"unknown"`` is preserved WITH its
    confidence + reasoning (an honest judgment, not a fallback).
    """
    allowed = _AI_TAG_ALLOWED[tag_id]
    if judgment is None:
        return _unknown_ai_tag(content_id, absent_reason)
    if judgment.value not in allowed:
        return _unknown_ai_tag(content_id, judgment.reasoning or _REASON_OFF_VOCAB)
    return Tag(
        value=judgment.value,
        confidence=judgment.confidence,
        reasoning=judgment.reasoning,
        source_facts=(content_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=_TAG_VERSION,
        stage=TagStage.A,
    )


def _ai_string_tag(judgment: TagJudgment | None, content_id: str, absent_reason: str) -> Tag:
    """An AI-judged FREE-STRING tag — no value set to check against (bug-001).

    `_ai_tag` coerces anything outside its vocabulary to unknown, which is right for an enum and
    impossible for a name: there is no list of every creditor. So the only checks here are the ones
    that do not need a vocabulary — a missing judgment, and a blank or "null"/"none"/"unknown"
    string, all of which become an honest unknown-with-reason rather than a name nobody wrote.

    A name is NOT trimmed to a house style beyond whitespace. The prompt asks the model to strip the
    bank's reference numbers; second-guessing what remains here would be this layer deciding what a
    creditor is called.
    """
    if judgment is None:
        # OMITTED by the model — a fail-closed fallback, confidence None, which the orchestrator's
        # structural scan correctly reports as a degradation.
        return _unknown_ai_tag(content_id, absent_reason)
    name = (judgment.value or "").strip()
    if not name or name.casefold() in {"null", "none", "unknown", "n/a"}:
        # JUDGED to have no other party, which is an ordinary fact about a bank fee, a cash
        # withdrawal or an interest credit — NOT a production failure. So the model's own confidence
        # is kept, exactly as `_ai_tag` keeps it for a genuine AI "unknown".
        #
        # This is load-bearing, and a test caught it: `_scan_tag_degradations` marks a run degraded
        # on `value=="unknown"` + AI + `confidence is None`, and a degraded run MUST NOT RETIRE
        # findings (LP-322). Emitting a confidence-less fallback here would have made almost every
        # real file degrade itself over a transaction that simply names nobody.
        return Tag(
            value="unknown",
            confidence=judgment.confidence,
            reasoning=judgment.reasoning or "the description names no other party",
            source_facts=(content_id,),
            produced_by=TagProducedBy.AI,
            tag_role=TagRole.STRUCTURAL_FACT,
            tag_version=_TAG_VERSION,
            stage=TagStage.A,
        )
    return Tag(
        value=name,
        confidence=judgment.confidence,
        reasoning=judgment.reasoning,
        source_facts=(content_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=_TAG_VERSION,
        stage=TagStage.A,
    )


def _unknown_ai_tag(content_id: str, reason: str) -> Tag:
    """An honest fallback: value 'unknown', no fabricated confidence, the reason recorded."""
    return Tag(
        value="unknown",
        confidence=None,
        reasoning=reason,
        source_facts=(content_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=_TAG_VERSION,
        stage=TagStage.A,
    )


__all__ = [
    "Reasoner",
    "TransactionTagCache",
    "produce_stage_a_transaction_tags",
]


# --------------------------------------------------------------------------- #
# LP-644 §3 — cross-run persistence of this stage's cache
# --------------------------------------------------------------------------- #
# The SHAPE is owned here, by the module that produces it, rather than by the store: `_Judged` and
# `TagJudgment` are this stage's business, and a store reaching into them would have to be edited
# every time either changes. The store handles the row; these handle the value.
#
# Round-tripping is what makes persistence safe to add, so it is pinned by a test rather than
# asserted: a value that does not survive dump→load is a wrong answer served from cache, which is
# strictly worse than no cache at all.


def _dump_judgment(judgment: TagJudgment | None) -> dict[str, object] | None:
    if judgment is None:
        return None
    return {
        "value": judgment.value,
        "confidence": judgment.confidence,
        "reasoning": judgment.reasoning,
    }


def _load_judgment(raw: object) -> TagJudgment | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    if not isinstance(value, str):
        return None
    confidence = raw.get("confidence")
    reasoning = raw.get("reasoning")
    return TagJudgment(
        value=value,
        confidence=confidence if isinstance(confidence, int | float) else None,
        reasoning=reasoning if isinstance(reasoning, str) else None,
    )


def dump_stage_a_entry(entry: _Judged) -> dict[str, object]:
    """One Stage-A cache value as JSON."""
    return {
        "is_money_in": _dump_judgment(entry.is_money_in),
        "apparent_category": _dump_judgment(entry.apparent_category),
        "counterparty": _dump_judgment(entry.counterparty),
        "reason": entry.reason,
    }


def load_stage_a_entry(raw: dict[str, object]) -> _Judged | None:
    """A Stage-A cache value from JSON, or None if the row cannot be trusted.

    DEFENSIVE ON PURPOSE, and it returns None rather than raising. A cache is an optimisation: a row
    written by an older shape, or corrupted, must cost a re-ask and nothing more. Raising here would
    let a stale cache row fail a verification, which is the one outcome a cache must never cause.

    ⚠️ Only a COMPLETE judgment is accepted, matching the in-memory rule at the write site: Stage A
    caches an entry only when both AI tags resolved, so a partial retries next run. Accepting a
    partial here would freeze a degraded answer into the file permanently.
    """
    is_money_in = _load_judgment(raw.get("is_money_in"))
    apparent_category = _load_judgment(raw.get("apparent_category"))
    if is_money_in is None or apparent_category is None:
        return None
    reason = raw.get("reason")
    return _Judged(
        is_money_in=is_money_in,
        apparent_category=apparent_category,
        reason=reason if isinstance(reason, str) else _REASON_MALFORMED,
        counterparty=_load_judgment(raw.get("counterparty")),
    )
