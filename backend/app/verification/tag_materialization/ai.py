"""The generic AI producer (LP-326) — materialize an AI GROUP's tags for its subjects.

The perceiver half (§3D) generalized from LP-313's transaction Stage-A: given an :class:`AiGroup`
declaration (a subject, the tags it co-produces, a prompt), this structures each subject's raw facts
into clean tags via the SAME machinery — bounded batches, index-echo integrity, honest/fail-closed
parse ("unknown" always legal, never coerced away; off-vocabulary → unknown; failure/truncation/
omission → unknown-with-reason), and cache-by-content-fingerprint. It reuses the Reasoner stub seam so
a keyless test is deterministic. A new AI family = a group declaration; ZERO new producer Python.

The group co-locates its tags on ONE subject (the LP-325 gather contract: id.address_normalized +
id.current_address_type land on the same document subject), so a downstream gather + filter work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from app.ai.client import complete
from app.ai.concurrency import dispatch_bounded
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_int, opt_str
from app.ai.stage_metrics import StageMetrics
from app.core.config import settings
from app.core.logging import get_logger
from app.verification.snapshot.content_id import content_fingerprint
from app.verification.snapshot.model import DocumentEntry, Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.breaker import AiInfraBreaker
from app.verification.tag_materialization.declarations import AiGroup
from app.verification.tag_materialization.subjects import (
    ContextOptions,
    loan_borrower_roster,
    subject_type,
)

logger = get_logger(__name__)

_MAX_TOKENS = 8192
_BATCH_SIZE = (
    15  # §3D bounded batches — a long file can't degrade the model's attention over its tail
)

#: LP-644 §2 — batches of ONE group in flight at once (the inner level). Eight, matching Stage A and
#: Stage B rather than inventing a third number; §4 raises them together on measured TPM. Note this
#: multiplies with the producer's OUTER group bound, which is why that one is deliberately smaller.
_MAX_CONCURRENT_BATCHES = 8

_REASON_FAILED = "tag production failed"
_REASON_TRUNCATED = "structuring response truncated"
_REASON_NOT_RETURNED = "not returned by structuring pass"
_REASON_MALFORMED = "tag value missing or malformed in structuring response"
_REASON_BAD_INDEX = "structuring pass returned unrecognized subject indices"
_REASON_OFF_VOCAB = "model returned an out-of-vocabulary value; coerced to unknown"

# The unknown-tag reasons that mean the AI CALL itself did not deliver a usable answer (a transport
# failure, or a truncated response) — as opposed to a completed response that genuinely abstained or
# omitted a tag. A caller inspecting produced tags (e.g. the dormant-probe diagnostic, LP-378) uses this
# to tell "the producer ran and abstained" from "the AI call failed", so an outage is never misread as a
# producer gap.
AI_CALL_FAILURE_REASONS = frozenset({_REASON_FAILED, _REASON_TRUNCATED})

_UNKNOWN = "unknown"


@dataclass(frozen=True)
class AiTagJudgment:
    value: str
    confidence: float | None
    reasoning: str | None


@dataclass(frozen=True)
class AiSubjectJudgment:
    """One subject's per-tag judgments, addressed by the batch ``index`` it was given."""

    index: int
    tags: dict[str, AiTagJudgment | None]  # keyed by the tag's short name (last id segment)


@dataclass(frozen=True)
class AiGroupResult:
    judgments: list[AiSubjectJudgment]
    input_tokens: int
    output_tokens: int
    model: str
    truncated: bool


# The injected AI seam — a keyless test supplies a deterministic stub; None → the real model.
Reasoner = Callable[[str], Awaitable[AiGroupResult]]

# group_key -> { content fingerprint -> resolved per-tag judgments (+ the reason to attach on None) }.
AiTagCache = dict[str, dict[str, "_Resolved"]]


@dataclass(frozen=True)
class _Resolved:
    tags: dict[str, AiTagJudgment | None]
    reason: str


def _short(tag_id: str) -> str:
    """The response key for a tag id — its last dotted segment (``id.address_normalized`` → ...)."""
    return tag_id.rsplit(".", 1)[-1]


async def reason_ai_group(system_prompt: str, context_json: str) -> AiGroupResult:
    """Run one structuring pass over a bounded batch. Opus, temperature 0, truncation-guarded,
    defensively parsed. Raises :class:`AIClientError` on transport failure/timeout. Never logs the
    context or the response — counts only."""
    # NOT wrapped in asyncio.wait_for: complete() bounds every attempt itself (B1), and an
    # outer wrapper would also bill the rate limiter's queueing time to this call's budget.
    result = await complete(
        model=settings.anthropic_model_reasoning,
        system=system_prompt,
        messages=[{"role": "user", "content": context_json}],
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
    )

    truncated = result.stop_reason == "max_tokens"
    if truncated:
        logger.warning("ai_group_response_truncated", output_tokens=result.output_tokens)
    judgments = _parse_group(result.text)
    logger.info(
        "ai_group_reasoning_done",
        judgments=len(judgments),
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return AiGroupResult(
        judgments=judgments,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        truncated=truncated,
    )


def _parse_group(text: str) -> list[AiSubjectJudgment]:
    raw_list = _load_list(text)
    if raw_list is None:
        logger.warning("ai_group_parse_no_json_array")
        return []
    return [j for item in raw_list if (j := _coerce_subject(item)) is not None]


def _load_list(text: str) -> list[Any] | None:
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("subjects", "judgments", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    return None


def _json_candidates(text: str) -> list[str]:
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced is not None:
        candidates.append(fenced.group(1).strip())
    array = _extract_balanced(text, "[", "]")
    if array is not None:
        candidates.append(array)
    obj = extract_json_object(text)
    if obj is not None:
        candidates.append(obj)
    return candidates


def _extract_balanced(text: str, opener: str, closer: str) -> str | None:
    """The first balanced ``opener…closer`` span (depth-aware, string-literal-safe), or None."""
    start = text.find(opener)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_subject(item: Any) -> AiSubjectJudgment | None:
    if not isinstance(item, dict):
        return None
    index = opt_int(item.get("index"))
    if index is None:
        return None
    tags: dict[str, AiTagJudgment | None] = {}
    for key, raw in item.items():
        if key == "index":
            continue
        tags[key] = _coerce_tag(raw)
    return AiSubjectJudgment(index=index, tags=tags)


def _coerce_tag(item: Any) -> AiTagJudgment | None:
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return AiTagJudgment(
        value=value.strip(),
        confidence=coerce_optional_confidence(item.get("confidence")),
        reasoning=opt_str(item.get("reasoning")),
    )


def _chunks(items: list[tuple[str, object]], size: int) -> list[list[tuple[str, object]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


_DOCUMENT_SUBJECT = "document"
_UNKNOWN_DOC_TYPE = "unknown"


def _gate_subjects(group: AiGroup, subjects: list[tuple[str, object]]) -> list[tuple[str, object]]:
    """LP-377-D: drop the documents a group's declared ``applies_to`` excludes — the redundant call the
    group would only abstain on (and, for income_amounts, over-produce a value on a non-income document).

    FAILS OPEN, always, toward RUNNING the group: the gate is off (``GATE_AI_GROUPS=0`` — reversibility),
    the group is not document-subject, or ``applies_to`` is None ("all"), or a document's type is
    ``None`` / ``"unknown"`` (the classifier abstained or is unsure — LP-377-A's untyped documents), or the
    type IS in ``applies_to`` → the document is kept. It ONLY removes a document whose KNOWN, confident type
    the group's ``applies_to`` does not list. Generic — keyed on ``group.applies_to`` + the document's type,
    with NO group-id or doc-type branch. The prompt's own "not my document" abstention remains the backstop
    on every kept document (this gate never removes that safety — it only skips redundant calls).

    Residual (reported, LP-377-D): the snapshot carries no per-document classification CONFIDENCE, so a
    document CONFIDENTLY mis-typed (e.g. a title document typed ``w2``) is gated by its wrong type and its
    group is skipped. Mitigated by the unknown fail-open + deliberately wide ``applies_to`` lists; a
    reported residual, not silently absorbed."""
    # LP-606 — SOURCE SCOPING, checked before the document gate and NOT behind `gate_ai_groups`.
    #
    # That flag exists to make the document gate reversible: gating there only skips a redundant call,
    # and the prompt's own abstention is the backstop. This is a different thing. A group asked about a
    # subject it has no data for does not abstain — `credit_derogatory` answered "no" for four
    # MISMO-stated liabilities with no credit history at all — so leaving it switchable would leave the
    # false all-clear switchable with it.
    if group.subject_source is not None:
        subjects = [
            (sid, raw)
            for sid, raw in subjects
            if getattr(raw, "source", None) == group.subject_source
        ]

    if (
        not settings.gate_ai_groups
        or group.subject != _DOCUMENT_SUBJECT
        or group.applies_to is None
    ):
        return subjects
    kept: list[tuple[str, object]] = []
    for subject_id, raw in subjects:
        doc_type = raw.document_type if isinstance(raw, DocumentEntry) else None
        if doc_type in (None, _UNKNOWN_DOC_TYPE) or doc_type in group.applies_to:
            kept.append((subject_id, raw))
    return kept


async def produce_ai_group_tags(
    snapshot: Snapshot,
    group: AiGroup,
    allowed_by_tag: dict[str, tuple[str, ...] | None],
    *,
    reasoner: Reasoner | None = None,
    cache: AiTagCache | None = None,
    breaker: AiInfraBreaker | None = None,
    metrics: StageMetrics | None = None,
) -> dict[str, dict[str, Tag]]:
    """Materialize ``group``'s tags for its subjects → ``{subject_id: {tag_id: Tag}}``.

    Fail-closed: an AI failure/truncation/omission/off-vocabulary value → an ``"unknown"`` tag WITH a
    reason (never a fabricated value); a genuine AI ``"unknown"`` is preserved with its confidence.
    Cache-by-content-fingerprint: identical subjects share one call; an unchanged subject reuses its
    judgment on a re-run (only complete judgments are cached)."""
    reason_fn = reasoner if reasoner is not None else _bind_prompt(group.system_prompt)
    group_cache = cache.setdefault(group.key, {}) if cache is not None else {}
    st = subject_type(group.subject)

    # LP-390-8a — a group that DECLARES it gets the loan's borrower roster added to each subject's context (a
    # document group comparing its stated party against the borrowers, owner_matches_borrower). Computed ONCE
    # per run (per-loan), merged per subject so it is part of the fingerprint (a roster change re-judges). A
    # group that does not declare it is byte-unchanged. Reuses the LP-332 borrower resolution — no second path.
    roster = loan_borrower_roster(snapshot) if group.include_borrower_roster else None

    opts = ContextOptions(
        include_lists=group.include_lists,
        list_row_cap=group.list_row_cap,
        include_stated_liabilities=group.include_stated_liabilities,
        include_unattributed_documents=group.include_unattributed_documents,
        include_transactions=group.include_transactions,
        include_documents=group.include_documents,
    )

    def _context(raw: object) -> dict[str, object]:
        ctx = st.build_context(raw, group.applies_to, opts)
        return {**ctx, "loan_borrowers": roster} if roster is not None else ctx

    subjects = _gate_subjects(
        group, st.enumerate(snapshot)
    )  # LP-377-D: skip inapplicable docs (fail-open)
    if not subjects:
        return {}

    fingerprinted: list[tuple[str, str, object]] = [
        (content_fingerprint(_context(raw)), sid, raw) for sid, raw in subjects
    ]

    representatives: list[tuple[str, object]] = []
    seen: set[str] = set()
    for fp, _sid, raw in fingerprinted:
        if fp in group_cache or fp in seen:
            continue
        seen.add(fp)
        representatives.append((fp, raw))
    representatives.sort(key=lambda pair: pair[0])

    resolved: dict[str, _Resolved] = dict(group_cache)
    shorts = tuple(_short(t) for t in group.tag_ids)

    # LP-644 §2, the INNER of the two levels — this group's batches, asked concurrently. The outer
    # level (across groups) is in `producer.py`. Contexts are built eagerly and bound with `partial`
    # so no closure can capture the loop variable and send every call the last batch's subjects.
    batches = _chunks(representatives, _BATCH_SIZE)
    contexts = [
        json.dumps(
            {"subjects": [{"index": i, **_context(raw)} for i, (_fp, raw) in enumerate(batch, 1)]}
        )
        for batch in batches
    ]
    outcomes = await dispatch_bounded(
        [partial(reason_fn, context) for context in contexts],
        concurrency=_MAX_CONCURRENT_BATCHES,
        stop_after_failures=None if breaker is None else breaker.threshold,
    )

    # APPLY, IN THE ORIGINAL ORDER, so `resolved`, the group cache and the breaker see the batches in
    # the sequence they had when this loop was serial.
    for batch, outcome in zip(batches, outcomes, strict=True):
        if outcome.not_attempted:
            # The gate closed before this batch was asked: same fail-closed resolution as a failure,
            # but the breaker is NOT fed — no call was made, so there is no failure to count.
            for fp, _ in batch:
                resolved[fp] = _Resolved({}, _REASON_FAILED)
            continue
        if outcome.error is not None:
            logger.warning("ai_group_batch_failed", group=group.key, size=len(batch))
            for fp, _ in batch:
                resolved[fp] = _Resolved({}, _REASON_FAILED)
            # LP-635 — the per-batch tolerance above is unchanged; this only asks whether the NEXT
            # call could land. `record_failure` raises `AiBackendUnavailable` once enough
            # INFRASTRUCTURE failures stack up consecutively, ending the pass instead of spending the
            # rest of the run's clock on calls that cannot reach the backend. A content failure
            # resets the counter there rather than counting.
            if breaker is not None:
                breaker.record_failure(outcome.error)
            continue
        result = outcome.result
        assert result is not None  # attempted, no error → a result (CallOutcome's contract)
        if breaker is not None:
            breaker.record_success()
        # LP-644 §1 — one accumulator shared across all 23 groups, so the stage's totals come out
        # whole rather than per-group. This is the stage the ticket calls "doubly sequential" and
        # the least-known fact in it, so its measured call count is the one to compare against the
        # projected 26.
        if metrics is not None:
            metrics.record_call(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                seconds=outcome.seconds,
            )
        by_index = {j.index: j for j in result.judgments}
        expected = set(range(1, len(batch) + 1))
        if not set(by_index) <= expected:
            logger.warning("ai_group_batch_bad_indices", group=group.key, size=len(batch))
            for fp, _ in batch:
                resolved[fp] = _Resolved({}, _REASON_BAD_INDEX)
            continue
        for index, (fp, _raw) in enumerate(batch, start=1):
            judgment = by_index.get(index)
            if judgment is None:
                reason = _REASON_TRUNCATED if result.truncated else _REASON_NOT_RETURNED
                resolved[fp] = _Resolved({}, reason)
                continue
            entry = _Resolved({s: judgment.tags.get(s) for s in shorts}, _REASON_MALFORMED)
            resolved[fp] = entry
            if all(entry.tags.get(s) is not None for s in shorts):
                group_cache[fp] = entry  # cache only a COMPLETE judgment

    by_subject: dict[str, dict[str, Tag]] = {}
    for fp, sid, _raw in fingerprinted:
        entry = resolved[fp]
        by_subject[sid] = {
            tag_id: _build_tag(entry.tags.get(short), allowed_by_tag.get(tag_id), sid, entry.reason)
            for tag_id, short in zip(group.tag_ids, shorts, strict=True)
        }
    return by_subject


def _build_tag(
    judgment: AiTagJudgment | None,
    allowed: tuple[str, ...] | None,
    subject_id: str,
    absent_reason: str,
) -> Tag:
    """One AI tag — the model's value/confidence/reasoning, or unknown-with-reason. An off-vocabulary
    value (when the tag declares allowed values) is coerced to ``"unknown"``; a free-string tag
    (no allowed set) accepts any value verbatim. A genuine ``"unknown"`` keeps its confidence."""
    if judgment is None:
        return _unknown_tag(subject_id, absent_reason)
    if allowed is not None and judgment.value not in allowed:
        return _unknown_tag(subject_id, judgment.reasoning or _REASON_OFF_VOCAB)
    return Tag(
        value=judgment.value,
        confidence=judgment.confidence,
        reasoning=judgment.reasoning,
        source_facts=(subject_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _unknown_tag(subject_id: str, reason: str) -> Tag:
    return Tag(
        value=_UNKNOWN,
        confidence=None,
        reasoning=reason,
        source_facts=(subject_id,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _bind_prompt(system_prompt: str) -> Reasoner:
    async def _call(context_json: str) -> AiGroupResult:
        return await reason_ai_group(system_prompt, context_json)

    return _call


__all__ = [
    "AI_CALL_FAILURE_REASONS",
    "AiGroupResult",
    "AiSubjectJudgment",
    "AiTagCache",
    "AiTagJudgment",
    "Reasoner",
    "produce_ai_group_tags",
    "reason_ai_group",
]
