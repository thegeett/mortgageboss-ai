"""Stage-B correlation tag production (LP-314) — the sourcing tag via candidate-then-judge.

Cross-entity correlation is where fraud-catching becomes real: is a deposit SOURCED, or is it an
unexplained inflow? The naive approach (ask the AI to search the whole file for a matching source)
does not scale and degrades. §3D's answer is **candidate-then-judge**:

1. **Deterministic candidate-search (this module, pure code, no AI).** For each money-in deposit,
   mechanically find candidate sources across ALL transactions in ALL accounts — an own-account
   transfer debit of the same amount within a date window, plus a payroll self-source when the
   deposit's own Stage-A category says so. This is the whole-file scan, and it scales.
2. **AI judgment on the SMALL set (``ai/tag_correlation.py``).** The AI sees ONE deposit + its few
   candidates and judges yes/no/unknown — it never searches, never sees the whole file.

DAG-ordered after Stage A (LP-313): it CONSUMES ``txn.is_money_in``. A deposit is judged only when
``is_money_in == "in"``; ``"unknown"`` propagates to an ``"unknown"`` sourcing tag (no more confident
than its input); ``"out"`` is not a sourcing subject. Fail-closed like Stage A: an AI failure /
timeout / truncation / malformed response yields ``unknown``-with-reason, never a defaulted ``"yes"``.

The critical honesty rule: a deposit with NO candidate and no income signal is a real ``"no"``
(looked, found nothing — the unexplained-deposit signal AS-1 fires on), NOT ``"unknown"``.

This ticket produces the sourcing tag only; the candidate/judge structure is the PATTERN every
future correlation tag (undisclosed liability, retained REO, …) will follow.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

import structlog

from app.ai.cost import estimate_cost
from app.ai.extraction.parsing import coerce_decimal
from app.ai.tag_correlation import (
    HAS_IDENTIFIED_SOURCE_VALUES,
    AIClientError,
    SourcingResult,
    reason_stage_b_sourcing,
)
from app.core.stage_timing import StageTiming
from app.verification.snapshot.content_id import content_fingerprint
from app.verification.snapshot.model import Snapshot, TagsSection, TransactionRecord
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_transactions as _all_transactions
from app.verification.snapshot.traversal import field_value as _val
from app.verification.tag_materialization.breaker import AiInfraBreaker
from app.verification.tag_materialization.derived import (
    txn_is_recurring,
    txn_stated_liability_match,
)

logger = structlog.get_logger(__name__)

# Injected so a keyless test supplies a deterministic stub (mirrors the cross-source seam).
Reasoner = Callable[[str], Awaitable[SourcingResult]]

# Candidate-match criteria — PRIYA-CONFIRMABLE thresholds (defaults here). Transfers move an
# exact amount and clear within a few days; the AI judges genuineness, so the code net is tight.
#
# The window is DIRECTIONAL: a source transfer's debit must post AT OR BEFORE the deposit it
# funds (money leaves one account, then arrives) — so a debit is a candidate from
# ``_DATE_WINDOW_DAYS`` before the deposit up to only ``_SOURCE_LOOKAHEAD_DAYS`` after (a small
# allowance for bank posting lag). A debit well AFTER the deposit is temporally impossible as its
# source; surfacing it would let the judge accept a coincidental later same-amount debit and flip
# a genuinely unexplained deposit to "sourced" — the AS-1 signal we must not hide.
_DATE_WINDOW_DAYS = 5
_SOURCE_LOOKAHEAD_DAYS = 2
_AMOUNT_TOLERANCE = Decimal("0.00")

# Tag ids (vocabulary keys) — Stage-A inputs this pass consumes + the Stage-B tags it writes.
_TAG_IS_MONEY_IN = "txn.is_money_in"
_TAG_APPARENT_CATEGORY = "txn.apparent_category"
_TAG_HAS_SOURCE = "txn.has_identified_source"
# Companion to has_identified_source: how STRONG the source evidence is (LP-314a). NOTE: this tag
# is produced here but is not yet registered in the fact-tag vocabulary (snapshot-fact-tags.xlsx);
# adding it to the vocabulary source of truth is a documented follow-up (see docs/tickets/LP-314.md).
_TAG_SOURCE_STRENGTH = "txn.source_strength"
_TAG_VERSION = 1

_CATEGORY_PAYROLL = "payroll"
_CATEGORY_TRANSFER = "own_account_transfer"  # the candidate kind that constitutes a matched debit
# Categories sourced by their own NATURE — legitimately need no matching debit to be strong.
_INTRINSIC_CATEGORIES = frozenset({"payroll", "interest", "dividend"})


class SourceStrength(StrEnum):
    """How strong a deposit's identified source is (LP-314a) — paper-trail vs claim vs nature.

    A fraud-catching system must distinguish a PROVEN paper trail from the borrower's CLAIM: a
    description saying "transfer from my brokerage" is not the same as a matching withdrawal.
    """

    VERIFIED = (
        "verified"  # a matching debit / paper-trail candidate was found (amount+date+account)
    )
    INTRINSIC = "intrinsic"  # sourced by nature (payroll / interest / dividend) — no debit needed
    SELF_ASSERTED = (
        "self_asserted"  # the description claims a source but NO matching debit was found
    )
    NONE = "none"  # no source found — not intrinsic, no credible matched trail


# Reasons attached to an unknown-with-reason tag so a human sees WHY it is unknown.
_REASON_FAILED = "sourcing judgment failed"
_REASON_TRUNCATED = "sourcing response truncated"
_REASON_MALFORMED = "sourcing response malformed"
_REASON_OFF_VOCAB = "model returned an out-of-vocabulary value; coerced to unknown"
_REASON_BAD_INDEX = "model cited an invalid candidate; failed closed"
_REASON_MONEY_IN_UNKNOWN = "money-in direction is unknown, so its source cannot be determined"

_STRENGTH_REASONING = {
    "verified": "a matching own-account debit was found — a verified paper trail",
    "intrinsic": "sourced by its own nature (payroll / interest / dividend) — no matching debit needed",
    "self_asserted": "the description claims a source but NO matching debit was found — a claim, not a paper trail",
    "none": "no source found",
}


@dataclass(frozen=True)
class SourceCandidate:
    """One candidate source for a deposit, found deterministically (no AI)."""

    kind: str  # "own_account_transfer" | "payroll"
    source_content_id: str  # the source transaction's content_id (the deposit's own id for payroll)
    amount: object
    txn_date: object
    description: object


@dataclass(frozen=True)
class _Sourced:
    """A resolved sourcing verdict (the cache value). ``cacheable`` gates cross-run reuse."""

    value: str  # yes | no | unknown
    source_content_id: str | None
    confidence: float | None
    reasoning: str | None
    cacheable: bool
    strength: SourceStrength | None  # None on the unknown/failed paths (no strength tag produced)


SourcingCache = dict[str, _Sourced]


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def _stage_a_tag(subject_tags: dict[str, Tag], tag_id: str) -> Tag | None:
    return subject_tags.get(tag_id)


def _stage_a_value(subject_tags: dict[str, Tag], tag_id: str) -> object:
    tag = subject_tags.get(tag_id)
    return tag.value if tag is not None else None


def find_source_candidates(
    deposit: TransactionRecord,
    deposit_tags: dict[str, Tag],
    debits: list[tuple[TransactionRecord, Decimal | None, date | None]],
    *,
    date_window_days: int = _DATE_WINDOW_DAYS,
    source_lookahead_days: int = _SOURCE_LOOKAHEAD_DAYS,
    amount_tolerance: Decimal = _AMOUNT_TOLERANCE,
) -> list[SourceCandidate]:
    """Deterministically find candidate sources for one money-in deposit (pure; no AI).

    Two kinds today: a PAYROLL self-source (the deposit's own Stage-A category is payroll — its
    own line is the evidence), and OWN-ACCOUNT TRANSFER debits (a money-out of matching amount
    within the date window, in any account). Extensible: gift / liquidation / other-account kinds
    slot in here later. Deterministic order (payroll first, then debits by content_id).
    """
    candidates: list[SourceCandidate] = []

    if _stage_a_value(deposit_tags, _TAG_APPARENT_CATEGORY) == _CATEGORY_PAYROLL:
        candidates.append(
            SourceCandidate(
                _CATEGORY_PAYROLL,
                deposit.content_id,
                _val(deposit.amount),
                _val(deposit.date),
                _val(deposit.description),
            )
        )

    deposit_amount = coerce_decimal(_val(deposit.amount))
    deposit_date = _parse_date(_val(deposit.date))
    if deposit_amount is not None and deposit_date is not None:
        matches = [
            txn
            for txn, amount, txn_date in debits
            if amount is not None
            and txn_date is not None
            and abs(amount - deposit_amount) <= amount_tolerance
            # Directional: the debit posts from date_window_days BEFORE the deposit up to only
            # source_lookahead_days AFTER (posting lag). ``(deposit - debit).days`` is positive
            # when the debit precedes the deposit — a source cannot post well after what it funds.
            and -source_lookahead_days <= (deposit_date - txn_date).days <= date_window_days
        ]
        for txn in sorted(matches, key=lambda t: t.content_id):
            candidates.append(
                SourceCandidate(
                    "own_account_transfer",
                    txn.content_id,
                    _val(txn.amount),
                    _val(txn.date),
                    _val(txn.description),
                )
            )
    return candidates


def _build_judge_context(
    deposit: TransactionRecord, deposit_tags: dict[str, Tag], candidates: list[SourceCandidate]
) -> dict[str, object]:
    """The bounded judge context — ONE deposit + its candidates (never the whole file).

    Candidates are numbered 1..N; the model returns a ``source_index`` and the content_id is
    reattached here (content_ids never reach the AI). Descriptions are already redacted at
    snapshot-build (LP-302a), so nothing raw-PII leaves in the prompt.
    """
    return {
        "deposit": {
            "amount": _val(deposit.amount),
            "date": _val(deposit.date),
            "description": _val(deposit.description),
            "apparent_category": _stage_a_value(deposit_tags, _TAG_APPARENT_CATEGORY),
        },
        "candidates": [
            {
                "index": i,
                "kind": candidate.kind,
                "amount": candidate.amount,
                "date": candidate.txn_date,
                "description": candidate.description,
            }
            for i, candidate in enumerate(candidates, start=1)
        ],
    }


def _cache_key(judge_context: dict[str, object]) -> str:
    """Key a judgment by the EXACT context the judge is shown.

    Fingerprinting the whole context (the deposit's facts INCLUDING its Stage-A
    ``apparent_category``, plus the ordered candidate set) means every input the judgment can
    depend on is in the key — so a changed input forces a re-judge and an unchanged input is a
    cache hit across runs. Keying on content_ids alone missed ``apparent_category`` (a derived
    tag, not part of the raw content_id), which could reuse a stale verdict.
    """
    return content_fingerprint(judge_context)


def _derive_strength(cited_kind: str | None, apparent_category: object) -> SourceStrength:
    """The AUTHORITATIVE source strength for a "yes" verdict, from hard evidence — not the AI's word.

    A matched own-account transfer debit is a paper trail (VERIFIED) regardless of how the model
    phrased it; income by nature (payroll/interest/dividend) is INTRINSIC and needs no debit;
    anything else answered "yes" rests on the description alone → SELF_ASSERTED (a claim). This is
    exactly the distinction a fraudster exploits, so it is derived deterministically, conservatively.
    """
    if cited_kind == _CATEGORY_TRANSFER:
        return SourceStrength.VERIFIED
    if apparent_category in _INTRINSIC_CATEGORIES or cited_kind == _CATEGORY_PAYROLL:
        return SourceStrength.INTRINSIC
    return SourceStrength.SELF_ASSERTED


def _resolve(
    result: SourcingResult, candidates: list[SourceCandidate], apparent_category: object
) -> _Sourced:
    """Turn the judge's response into a resolved verdict, honestly + fail-closed.

    Derives the source STRENGTH (LP-314a) for a "yes": a cited own-account-transfer candidate is a
    matched paper trail (verified); an intrinsic-income category is intrinsic; a "yes" with no
    matched debit and no intrinsic nature is a description-only claim (self_asserted).
    """
    if result.truncated:
        return _Sourced("unknown", None, None, _REASON_TRUNCATED, cacheable=False, strength=None)
    judgment = result.judgment
    if judgment is None:
        return _Sourced("unknown", None, None, _REASON_MALFORMED, cacheable=False, strength=None)
    if judgment.value not in HAS_IDENTIFIED_SOURCE_VALUES:
        return _Sourced(
            "unknown", None, None, judgment.reasoning or _REASON_OFF_VOCAB, False, strength=None
        )
    if judgment.value == "yes":
        source_content_id: str | None = None
        cited_kind: str | None = None
        if judgment.source_index is not None:
            if not 1 <= judgment.source_index <= len(candidates):
                # A "yes" citing a candidate that does not exist is untrustworthy — fail closed.
                return _Sourced(
                    "unknown", None, None, _REASON_BAD_INDEX, cacheable=False, strength=None
                )
            cited = candidates[judgment.source_index - 1]
            source_content_id = cited.source_content_id
            cited_kind = cited.kind
        strength = _derive_strength(cited_kind, apparent_category)
        return _Sourced(
            "yes",
            source_content_id,
            judgment.confidence,
            judgment.reasoning,
            True,
            strength=strength,
        )
    # "no" / "unknown" — any cited source is ignored (a non-sourced deposit has no source).
    if judgment.value == "no":
        return _Sourced(
            "no", None, judgment.confidence, judgment.reasoning, True, strength=SourceStrength.NONE
        )
    return _Sourced("unknown", None, judgment.confidence, judgment.reasoning, True, strength=None)


def _propagate(judge_confidence: float | None, input_confidence: float | None) -> float | None:
    """Confidence propagation (DAG): no more confident than the ``is_money_in`` it depends on."""
    if judge_confidence is None:
        return None
    if input_confidence is None:
        return judge_confidence
    return min(judge_confidence, input_confidence)


def _sourcing_tag(
    *,
    value: str,
    source_content_id: str | None,
    confidence: float | None,
    reasoning: str | None,
    deposit_content_id: str,
    produced_by: TagProducedBy,
) -> Tag:
    """Build the has_identified_source tag, citing the deposit and (if sourced) the source."""
    source_facts = [deposit_content_id]
    if source_content_id is not None and source_content_id != deposit_content_id:
        source_facts.append(source_content_id)
    return Tag(
        value=value,
        confidence=confidence,
        reasoning=reasoning,
        source_facts=tuple(source_facts),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        tag_version=_TAG_VERSION,
        stage=TagStage.B,
    )


_TAG_IS_RECURRING = "txn.is_recurring"
_TAG_LIABILITY_MATCH = "txn.stated_liability_match"


def produce_recurrence_tags(snapshot: Snapshot) -> Snapshot:
    """Produce ``txn.is_recurring`` for every transaction — DETERMINISTIC, no model, no reasoner.

    WHY THIS IS A STAGE AND NOT A DECLARATION. `txn.is_recurring` has been declared in the vocabulary
    since it was written, with FR-5 and CR-1 as consumers, and produced by nothing. The generic
    materialization pass SKIPS the `transaction` subject, and Stage A/B only produces the tags it names
    — so a `mode: derived` declaration alone materializes in tests and never on a real run, which is the
    exact trap `test_declared_subjects_are_all_materialized` was written to catch. Its docstring names
    the two ways out; this is the first ("produce it in Stage A/B"). The second — adding `transaction`
    to `_MATERIALIZED_SUBJECTS` — would re-run the txn_stage_a model on every transaction, so it is not
    free and is not the right trade for a tag that needs no model at all.

    AND WHY IT NEEDED NO MODEL. `activation_bars` records FR-5 as blocked because "its declared
    'pattern across statements' is unanswerable from a context that shows one transaction". That is
    true of an AI group — the transaction context builder sends one transaction — and simply not true
    here: this sees the whole snapshot. Recurrence is a COUNT, decidable from the text, identical on
    every run, with no calibration round. The JUDGMENT that count feeds stays with the rule.

    Runs AFTER Stage A so it sits with the other transaction tags, though it consumes none of them.
    """
    if snapshot.tags.absent:
        return snapshot  # Stage A never ran; a tags layer that is absent stays absent.
    by_subject = {cid: dict(tags) for cid, tags in snapshot.tags.by_subject.items()}
    for txn in _all_transactions(snapshot):
        for tag_id, produce in (
            (_TAG_IS_RECURRING, txn_is_recurring),
            (_TAG_LIABILITY_MATCH, txn_stated_liability_match),
        ):
            value, reasoning = produce(snapshot, txn.content_id, None)
            by_subject.setdefault(txn.content_id, {})[tag_id] = Tag(
                value=value,
                # derived: a count and a name comparison are not probabilities, and a fabricated
                # confidence would read as one.
                confidence=None,
                reasoning=reasoning,
                source_facts=(txn.content_id,),
                produced_by=TagProducedBy.DERIVED,
                tag_role=TagRole.STRUCTURAL_FACT,
                tag_version=_TAG_VERSION,
                stage=TagStage.B,
            )
    return snapshot.model_copy(update={"tags": TagsSection.present(by_subject)})


#: How many sourcing judgements may be in flight at once (LP-635).
#:
#: The pass was fully sequential, so its wall-clock was the sum of its model latencies. This is the
#: only thing standing between that and the provider's own pacing — `RateLimiter` already enforces a
#: minimum interval between acquisitions, so it, not this number, is the real ceiling; this bounds
#: how many coroutines can be waiting on it, and therefore memory and in-flight token exposure.
#:
#: Eight rather than "as many as there are deposits": staging's environment budget is 2,000 RPM
#: divided across worker slots, a REJECTED request still counts against the Bedrock quota (so pacing
#: at the ceiling turns one throttle into a self-sustaining one), and `bedrock_rpm_budget` records
#: that TOKENS per minute — unmeasured — is expected to bind before requests do on document-heavy
#: work. A modest number takes most of the available win without being the thing that discovers the
#: TPM ceiling.
_MAX_CONCURRENT_JUDGMENTS = 8

#: What a deposit's ``error_detail`` says when the dispatch gate stopped before its call was made.
#: Fixed text, no interpolation: it reaches a processor through the same path as any other sourcing
#: failure reason, and there is nothing about THIS deposit worth saying — the backend had already
#: stopped answering for everyone.
_NOT_ATTEMPTED_DETAIL = (
    "the AI backend had already stopped answering, so this judgment was not attempted"
)


@dataclass(frozen=True)
class _Planned:
    """One deposit that needs a sourcing judgement, and everything needed to ask for it.

    Built before any call is made, so the questions are settled as a set — which is what lets them
    be asked concurrently and still applied in a fixed order.
    """

    txn: TransactionRecord
    subject: dict[str, Tag]
    candidates: list[SourceCandidate]
    context: dict[str, object]
    key: str
    is_money_in: Tag


class _NotAttempted(AIClientError):
    """The dispatch gate refused to spend a call on this judgement (LP-635 review).

    A real failure and a call never made are both ``unknown`` to the deposit, but they are not the
    same event, and the distinction has to survive into the log line and the breaker's reasoning.
    Carries no cause, so ``infra_failure_kind`` returns ``INFRA_FAILED`` and the breaker COUNTS it —
    which is the intent: the gate closes only when the backend has already stopped answering, and
    the pass must end rather than quietly resolve its remaining deposits to ``unknown``.
    """


async def _judge_concurrently(
    contexts: dict[str, dict[str, object]],
    reason_fn: Reasoner,
    *,
    concurrency: int,
    stop_after_failures: int | None = None,
    timing: StageTiming | None = None,
) -> dict[str, SourcingResult | AIClientError]:
    """Run every outstanding judgement at once, bounded, returning ``{cache key: outcome}``.

    An ``AIClientError`` is RETURNED rather than raised, so one unreachable call cannot cancel the
    siblings that were about to succeed — the caller decides what each failure means, in deposit
    order.

    THE DISPATCH GATE (``stop_after_failures``) IS WHAT KEEPS THE BREAKER MEANINGFUL HERE, and
    without it concurrency quietly disarmed it. The breaker is fed in the caller's apply loop, which
    does not begin until this function has returned — so every outstanding judgement was dispatched
    before the first failure could be counted. On the outage the breaker was written for, that is
    the whole of Stage B, the stage with the most calls, each exhausting ``ai_max_retries`` with
    backoff: the "release the slot in under a minute instead of grinding through the file's whole
    budget" benefit was gone for the case it was built for. The gate restores the abort by stopping
    DISPATCH once the backend has failed ``stop_after_failures`` times with no success between,
    while the authoritative counting stays where it is deterministic. Calls already in flight are
    allowed to finish; the bound on what an outage can cost is therefore the threshold plus one
    semaphore's worth, not the stage.

    It is opt-in because only a caller holding a breaker can ACT on a closed gate. With no breaker
    the pass would run to completion and resolve the skipped deposits to ``unknown`` — cheaper than
    grinding, and silent, which is the worse half of the two failures this stage can have.

    A non-``AIClientError`` — a bug rather than an outage — closes the gate and propagates unchanged,
    but only after the siblings have been collected. Bare ``gather`` propagates the first exception
    WITHOUT cancelling the rest, so returning immediately would leave model calls running against a
    caller that has already unwound: billed, unawaited, and surfacing later as "Task exception was
    never retrieved". The previous docstring claimed this matched the sequential version; in the
    loop the next call was simply never started, which is what the gate now provides.
    """
    if not contexts:
        return {}
    # Never below 1. A zero or negative bound makes ``Semaphore`` block forever, so a misconfigured
    # value would hang the pass until the Celery soft limit rather than fail — and the wrong shape
    # of failure here is exactly what LP-635 was opened to diagnose. Degrading to sequential is slow
    # and correct.
    semaphore = asyncio.Semaphore(max(1, concurrency))
    consecutive_failures = 0
    gate_closed = False

    async def judge(
        key: str, context: dict[str, object]
    ) -> tuple[str, SourcingResult | AIClientError]:
        nonlocal consecutive_failures, gate_closed
        # Checked again after acquiring: a coroutine can wait a long time for its slot, and the
        # gate may well have closed while it did.
        if gate_closed:
            return key, _NotAttempted(_NOT_ATTEMPTED_DETAIL)
        async with semaphore:
            if gate_closed:
                return key, _NotAttempted(_NOT_ATTEMPTED_DETAIL)
            # LP-644 §1 review — HERE, past both gate checks, is where a call is actually issued.
            # The first version counted in the APPLY loop on the success path, which misses two
            # cases in opposite directions: a failed call costs wall clock and went uncounted, and
            # a `_NotAttempted` from the closed breaker gate never reaches the model at all. Past
            # the gate and before the try counts exactly the calls that were made.
            if timing is not None:
                timing.record_call()
            try:
                result = await reason_fn(json.dumps(context))
            except AIClientError as err:
                consecutive_failures += 1
                if stop_after_failures is not None and consecutive_failures >= stop_after_failures:
                    gate_closed = True
                return key, err
            except Exception:
                gate_closed = True  # a bug, not an outage — stop spending on a discarded result
                raise
            consecutive_failures = 0
            return key, result

    collected = await asyncio.gather(
        *(judge(k, c) for k, c in contexts.items()), return_exceptions=True
    )
    judged: dict[str, SourcingResult | AIClientError] = {}
    for item in collected:
        if isinstance(item, BaseException):
            raise item
        key, outcome = item
        judged[key] = outcome
    return judged


async def produce_stage_b_sourcing_tags(
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    cache: SourcingCache | None = None,
    breaker: AiInfraBreaker | None = None,
    date_window_days: int = _DATE_WINDOW_DAYS,
    source_lookahead_days: int = _SOURCE_LOOKAHEAD_DAYS,
    amount_tolerance: Decimal = _AMOUNT_TOLERANCE,
    concurrency: int = _MAX_CONCURRENT_JUDGMENTS,
) -> Snapshot:
    """Produce ``txn.has_identified_source`` for each money-in deposit (candidate-then-judge).

    Runs AFTER Stage A (consumes ``txn.is_money_in`` from the tags layer) and EXTENDS the tags
    layer in place. Returns a new frozen snapshot; the raw layer is untouched. ``cache`` (optional,
    mutated in place) reuses judgments across runs by (deposit + candidate-set) content — only
    successful judgments are stored, so a failed/truncated deposit retries next run.
    """
    if snapshot.tags.absent:
        # Stage A never ran / failed — there is no is_money_in to consume; leave it absent.
        return snapshot

    reason_fn = reasoner if reasoner is not None else reason_stage_b_sourcing
    persistent = cache if cache is not None else {}
    transactions = _all_transactions(snapshot)

    # Index the money-out debits once (the candidate pool), parsed for matching.
    debits: list[tuple[TransactionRecord, Decimal | None, date | None]] = []
    for txn in transactions:
        subject = snapshot.tags.by_subject.get(txn.content_id, {})
        if _stage_a_value(subject, _TAG_IS_MONEY_IN) == "out":
            debits.append((txn, coerce_decimal(_val(txn.amount)), _parse_date(_val(txn.date))))

    by_subject = {cid: dict(tags) for cid, tags in snapshot.tags.by_subject.items()}
    input_tokens = output_tokens = deposits_judged = 0
    timing = StageTiming()  # LP-644 §1 — starts the clock for this stage
    # Pricing must be keyed on the model that ACTUALLY ran — under Bedrock the inference-
    # profile id, not the tier value read from settings. SourcingResult.model carries the
    # completion's own resolved id. See the matching note in services/tag_production.py.
    invoked_model: str | None = None

    # PHASE 1 — PLAN. Pure: decide what needs judging and build each context. No model call here, so
    # the set of questions is settled before any of them is asked (LP-635).
    plan: list[_Planned] = []
    for txn in transactions:
        subject = snapshot.tags.by_subject.get(txn.content_id, {})
        is_money_in = _stage_a_tag(subject, _TAG_IS_MONEY_IN)
        if is_money_in is None or is_money_in.value == "out":
            continue  # not a sourcing subject (money-out, or Stage A did not tag it)
        if is_money_in.value == "unknown":
            # DAG propagation: can't source what we can't confirm is money-in. Derived, not AI.
            by_subject[txn.content_id][_TAG_HAS_SOURCE] = _sourcing_tag(
                value="unknown",
                source_content_id=None,
                confidence=is_money_in.confidence,
                reasoning=_REASON_MONEY_IN_UNKNOWN,
                deposit_content_id=txn.content_id,
                produced_by=TagProducedBy.DERIVED,
            )
            continue
        if is_money_in.value != "in":
            continue  # defensive — any other value is not a sourcing subject

        candidates = find_source_candidates(
            txn,
            subject,
            debits,
            date_window_days=date_window_days,
            source_lookahead_days=source_lookahead_days,
            amount_tolerance=amount_tolerance,
        )
        # Key the judgment on the EXACT context the judge sees (incl. the deposit's
        # apparent_category), so a changed judge input can never reuse a stale verdict.
        context = _build_judge_context(txn, subject, candidates)
        plan.append(
            _Planned(
                txn=txn,
                subject=subject,
                candidates=candidates,
                context=context,
                key=_cache_key(context),
                is_money_in=is_money_in,
            )
        )

    # PHASE 2 — JUDGE, CONCURRENTLY. THE CHANGE THAT MATTERS, and it changes no prompt.
    #
    # Every call this stage makes was awaited one after the next, so the pass's wall-clock was the
    # SUM of its model latencies — 591 calls at a 4.3s mean is 2,542 seconds of waiting, and this is
    # the stage that makes the most of them (one per money-in deposit; Stage A and the tag groups
    # both batch fifteen). That sum is what did not fit in the window, and it is why LF-ZE9N could
    # not be verified.
    #
    # Concurrency does not reduce the call count or the token bill. It overlaps the WAITING, which
    # is the part that was failing. The prompts, the contexts and the resolution logic are
    # untouched, so a verdict cannot move: this is the same set of questions, asked at the same
    # time as each other rather than one after another.
    #
    # Deduplicated by cache key BEFORE dispatch, which the sequential version got for free by
    # writing the cache between iterations. Without that, identical contexts already in flight
    # would each spend a call.
    outstanding: dict[str, dict[str, object]] = {}
    for item in plan:
        if item.key not in persistent and item.key not in outstanding:
            outstanding[item.key] = item.context
    #
    # The gate is the breaker's OWN threshold, handed down rather than chosen again here: this is
    # not a second policy about when to give up, it is the same one applied where the calls are
    # actually made. Without a breaker there is nothing that could act on a closed gate, so no gate.
    judged = await _judge_concurrently(
        outstanding,
        reason_fn,
        concurrency=concurrency,
        stop_after_failures=None if breaker is None else breaker.threshold,
        timing=timing,  # LP-644 §1 — counted at dispatch, inside
    )

    # PHASE 3 — APPLY, IN THE ORIGINAL ORDER. Deterministic on purpose: the tags, the token totals
    # and the BREAKER all see the deposits in the same sequence they had before, so "five
    # consecutive failures" keeps the meaning it was given rather than depending on which coroutine
    # happened to finish first.
    #
    # AN OUTCOME IS APPLIED ONCE PER CALL, NOT ONCE PER DEPOSIT (LP-635 review). Deposits with
    # identical contexts share a cache key and so share one judgement — but `persistent` only ever
    # holds CACHEABLE outcomes, so for a failed, truncated or malformed one it stayed empty and
    # every duplicate deposit re-entered the branch below and replayed that single call's side
    # effects. Five identical deposits (the judge context carries no content_id, so they collide by
    # construction) turned ONE transport blip into five breaker failures — tripping a breaker whose
    # threshold is five, off a single flaky call, against a module that promises "a single flaky
    # call never reaches two". The same replay multiplied the token and cost figures for a truncated
    # judgement by the number of deposits sharing it. This map is pass-local on purpose: it dedupes
    # the side effects without writing an uncacheable verdict anywhere durable, so such a deposit
    # still retries on the next run.
    applied: dict[str, _Sourced] = {}
    for item in plan:
        txn, subject, candidates = item.txn, item.subject, item.candidates
        is_money_in = item.is_money_in
        resolved = persistent.get(item.key)
        if resolved is None:
            resolved = applied.get(item.key)
        if resolved is None:
            outcome = judged[item.key]
            if not isinstance(outcome, _NotAttempted):
                # Counts judgments the backend was actually ASKED for. A gated-out one is a
                # deposit the pass declined to spend on, not one it judged, and the name has to
                # keep meaning that — it is read next to the token totals.
                deposits_judged += 1
            if isinstance(outcome, AIClientError):
                logger.warning("stage_b_judge_failed", candidates=len(candidates))
                # LP-635 REVIEW — Stage B was left out of the breaker, and it is the stage with the
                # most calls: one judgement per money-in deposit. The per-deposit tolerance here is
                # unchanged (a failure still resolves to `unknown`), but an outage beginning in this
                # stage used to be invisible to the counter, so the pass ground through the whole of
                # it — the exact behaviour the breaker was added to stop, still reachable by the
                # commonest route.
                if breaker is not None:
                    breaker.record_failure(outcome)
                resolved = _Sourced(
                    "unknown", None, None, _REASON_FAILED, cacheable=False, strength=None
                )
            else:
                if breaker is not None:
                    breaker.record_success()
                input_tokens += outcome.input_tokens
                output_tokens += outcome.output_tokens
                invoked_model = outcome.model
                resolved = _resolve(
                    outcome, candidates, _stage_a_value(subject, _TAG_APPARENT_CATEGORY)
                )
            applied[item.key] = resolved
            if resolved.cacheable:
                persistent[item.key] = resolved

        confidence = _propagate(resolved.confidence, is_money_in.confidence)
        by_subject[txn.content_id][_TAG_HAS_SOURCE] = _sourcing_tag(
            value=resolved.value,
            source_content_id=resolved.source_content_id,
            confidence=confidence,
            reasoning=resolved.reasoning,
            deposit_content_id=txn.content_id,
            produced_by=TagProducedBy.AI,
        )
        # The companion strength tag (LP-314a): how STRONG the source evidence is. Derived
        # deterministically from the matched candidate + category — a claim is not a paper trail.
        if resolved.strength is not None:
            by_subject[txn.content_id][_TAG_SOURCE_STRENGTH] = _sourcing_tag(
                value=resolved.strength.value,
                source_content_id=resolved.source_content_id,
                confidence=confidence,
                reasoning=_STRENGTH_REASONING[resolved.strength.value],
                deposit_content_id=txn.content_id,
                produced_by=TagProducedBy.DERIVED,
            )

    # LP-644 §1 review — see the twin in `tag_production`: a stage whose every call failed used to
    # log nothing, which is the run this measurement most needs.
    if timing.calls:
        logger.info(
            "stage_b_production_done",
            **timing.as_log_fields(),  # LP-644 §1
            deposits_judged=deposits_judged,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # None when every judgment failed — a $0 estimate would read as a free stage.
            cost_estimate=(
                estimate_cost(
                    model=invoked_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if invoked_model is not None
                else None
            ),
        )
    return snapshot.model_copy(update={"tags": TagsSection.present(by_subject)})


__all__ = [
    "Reasoner",
    "SourceCandidate",
    "SourceStrength",
    "SourcingCache",
    "find_source_candidates",
    "produce_stage_b_sourcing_tags",
]
