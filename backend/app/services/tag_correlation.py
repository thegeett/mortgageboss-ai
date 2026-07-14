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
from app.core.config import settings
from app.verification.snapshot.content_id import content_fingerprint
from app.verification.snapshot.model import Snapshot, TagsSection, TransactionRecord
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.snapshot.traversal import all_transactions as _all_transactions
from app.verification.snapshot.traversal import field_value as _val

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


async def produce_stage_b_sourcing_tags(
    snapshot: Snapshot,
    *,
    reasoner: Reasoner | None = None,
    cache: SourcingCache | None = None,
    date_window_days: int = _DATE_WINDOW_DAYS,
    source_lookahead_days: int = _SOURCE_LOOKAHEAD_DAYS,
    amount_tolerance: Decimal = _AMOUNT_TOLERANCE,
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
        key = _cache_key(context)
        resolved = persistent.get(key)
        if resolved is None:
            deposits_judged += 1
            try:
                result = await reason_fn(json.dumps(context))
            except AIClientError:
                logger.warning("stage_b_judge_failed", candidates=len(candidates))
                resolved = _Sourced(
                    "unknown", None, None, _REASON_FAILED, cacheable=False, strength=None
                )
            else:
                input_tokens += result.input_tokens
                output_tokens += result.output_tokens
                resolved = _resolve(
                    result, candidates, _stage_a_value(subject, _TAG_APPARENT_CATEGORY)
                )
            if resolved.cacheable:
                persistent[key] = resolved

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

    if input_tokens or output_tokens:
        logger.info(
            "stage_b_production_done",
            deposits_judged=deposits_judged,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate=estimate_cost(
                model=settings.anthropic_model_extraction,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
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
