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

import structlog

from app.ai.cost import estimate_cost
from app.ai.tag_production import (
    APPARENT_CATEGORY_VALUES,
    IS_MONEY_IN_VALUES,
    AIClientError,
    StageAResult,
    TagJudgment,
    reason_stage_a_transactions,
)
from app.core.config import resolve_model, settings
from app.core.stage_timing import StageTiming
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
) -> Snapshot:
    """Produce Stage-A transaction tags and write them into the snapshot's tags layer.

    Returns a NEW frozen snapshot with ``tags`` populated (the raw layer untouched). ``cache``
    (optional, mutated in place) reuses AI judgments across runs by content fingerprint — only
    successful judgments are stored, so a failed/truncated transaction retries next run.
    """
    reason_fn = reasoner if reasoner is not None else reason_stage_a_transactions
    persistent = cache if cache is not None else {}

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
    timing = StageTiming()  # LP-644 §1 — starts the clock for this stage
    # Pricing must be keyed on the model that ACTUALLY ran. Under Bedrock that is the
    # cross-region inference-profile id, not the tier value this module asks for, so
    # reading the tier setting here would price the call against the wrong key the moment
    # the Bedrock rows in cost.py stop matching the direct-API rates. StageAResult.model
    # carries the completion's own resolved id — the authoritative answer.
    invoked_model: str | None = None

    for batch in _chunks(representatives, _BATCH_SIZE):
        # LP-644 §1 review — AT THE ISSUE POINT, not on the success path. `StageTiming.calls` is
        # documented as counting failed calls too, because a failure costs the same wall clock and
        # the baseline this replaces was measured on a FAILING run — but the first version recorded
        # after the tokens accumulated, which only happens on success. A comment describing a
        # distinction the code does not make; the run it most needed to measure counted zero.
        timing.record_call(subjects=len(batch))
        context_json = json.dumps(_build_context([txn for _, txn in batch]))
        try:
            result = await reason_fn(context_json)
        except AIClientError as err:
            # Fail-closed: the whole batch's AI tags become unknown-with-reason (the
            # passthroughs still succeed). Not cached → retried on the next run.
            logger.warning("stage_a_batch_failed", size=len(batch))
            for fp, _ in batch:
                resolved[fp] = _Judged(None, None, _REASON_FAILED)
            # LP-635 — see the identical guard in `tag_materialization.ai`. Stage A shares the run's
            # breaker, so an outage that starts here is counted with the ones that follow it rather
            # than each stage forgiving the backend separately.
            if breaker is not None:
                breaker.record_failure(err)
            continue
        if breaker is not None:
            breaker.record_success()

        input_tokens += result.input_tokens
        output_tokens += result.output_tokens
        invoked_model = result.model
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

    # LP-644 §1 review — LOGGED WHENEVER A CALL WAS ISSUED, not only when one succeeded.
    #
    # The guard used to be `if input_tokens or output_tokens`, so a stage whose every call FAILED
    # logged nothing at all. That is precisely the run the 4.3s baseline was measured on, and the
    # run whose wall clock this instrumentation most needs to describe — a stage can spend its whole
    # budget on retries and, under the old guard, report that it never ran.
    if timing.calls:
        # invoked_model is set whenever a batch succeeded, and tokens are only accumulated
        # on success — so the fallback is unreachable, and resolves rather than guessing.
        logger.info(
            "stage_a_production_done",
            **timing.as_log_fields(),  # LP-644 §1
            transactions=len(transactions),
            unique=len(representatives),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # None when every call failed: there is no model to attribute a cost to, and a $0
            # estimate would read as a free stage rather than an unsuccessful one.
            cost_estimate=(
                estimate_cost(
                    model=invoked_model or resolve_model(settings.anthropic_model_reasoning),
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if invoked_model is not None
                else None
            ),
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
