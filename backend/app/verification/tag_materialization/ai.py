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

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_int, opt_str
from app.core.config import settings
from app.core.logging import get_logger
from app.verification.snapshot.content_id import content_fingerprint
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.declarations import AiGroup
from app.verification.tag_materialization.subjects import subject_type

logger = get_logger(__name__)

_MAX_TOKENS = 8192
_BATCH_SIZE = (
    15  # §3D bounded batches — a long file can't degrade the model's attention over its tail
)

_REASON_FAILED = "tag production failed"
_REASON_TRUNCATED = "structuring response truncated"
_REASON_NOT_RETURNED = "not returned by structuring pass"
_REASON_MALFORMED = "tag value missing or malformed in structuring response"
_REASON_BAD_INDEX = "structuring pass returned unrecognized subject indices"
_REASON_OFF_VOCAB = "model returned an out-of-vocabulary value; coerced to unknown"

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
    try:
        result = await asyncio.wait_for(
            complete(
                model=settings.anthropic_model_extraction,
                system=system_prompt,
                messages=[{"role": "user", "content": context_json}],
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
            ),
            timeout=settings.ai_request_timeout_seconds,
        )
    except TimeoutError as exc:
        logger.warning("ai_group_reason_timeout", timeout_s=settings.ai_request_timeout_seconds)
        raise AIClientError("AI group structuring timed out") from exc

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


async def produce_ai_group_tags(
    snapshot: Snapshot,
    group: AiGroup,
    allowed_by_tag: dict[str, tuple[str, ...] | None],
    *,
    reasoner: Reasoner | None = None,
    cache: AiTagCache | None = None,
) -> dict[str, dict[str, Tag]]:
    """Materialize ``group``'s tags for its subjects → ``{subject_id: {tag_id: Tag}}``.

    Fail-closed: an AI failure/truncation/omission/off-vocabulary value → an ``"unknown"`` tag WITH a
    reason (never a fabricated value); a genuine AI ``"unknown"`` is preserved with its confidence.
    Cache-by-content-fingerprint: identical subjects share one call; an unchanged subject reuses its
    judgment on a re-run (only complete judgments are cached)."""
    reason_fn = reasoner if reasoner is not None else _bind_prompt(group.system_prompt)
    group_cache = cache.setdefault(group.key, {}) if cache is not None else {}
    st = subject_type(group.subject)

    subjects = st.enumerate(snapshot)
    if not subjects:
        return {}

    fingerprinted: list[tuple[str, str, object]] = [
        (content_fingerprint(st.build_context(raw)), sid, raw) for sid, raw in subjects
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

    for batch in _chunks(representatives, _BATCH_SIZE):
        context = {
            "subjects": [
                {"index": i, **st.build_context(raw)} for i, (_fp, raw) in enumerate(batch, 1)
            ]
        }
        try:
            result = await reason_fn(json.dumps(context))
        except AIClientError:
            logger.warning("ai_group_batch_failed", group=group.key, size=len(batch))
            for fp, _ in batch:
                resolved[fp] = _Resolved({}, _REASON_FAILED)
            continue
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
    "AiGroupResult",
    "AiSubjectJudgment",
    "AiTagCache",
    "AiTagJudgment",
    "Reasoner",
    "produce_ai_group_tags",
    "reason_ai_group",
]
