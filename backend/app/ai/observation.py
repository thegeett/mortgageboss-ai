"""The observation channel's AI step (LP-320) — structure the UNMAPPED, never invent a tag.

When the AI meets a document or fact that does NOT map to a known vocabulary tag, this produces a
STRUCTURED OBSERVATION envelope: what the thing IS (natural language), a schemaless structured read,
the type the AI would call it, whether it looks like it should become a formal tag, and what it
bears on. It NEVER invents a formal governed tag (that is a human/Priya decision) and its output
only INFORMS — it cannot resolve a finding. Same clone as the Stage-B judge: injected Reasoner seam,
temperature 0, truncation guard, honest defensive parse, never logs the context/response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_str
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 1024

OBSERVATION_SYSTEM_PROMPT = """\
You are a senior mortgage underwriter recording a STRUCTURED OBSERVATION about a document or fact
that does NOT fit the system's known tag vocabulary — a gift letter, a divorce decree, a trust
agreement, an unusual credit, anything the enumerated tags do not already cover.

Your job is to CAPTURE it, not to resolve anything. Do NOT invent a formal tag. Do NOT decide any
rule's outcome. You are handing a human the structured context so nothing is silently dropped.

Describe what the thing IS, plainly, and give:
- a short "type" you would call it (snake_case, e.g. "gift_letter_asserted", "document_purpose",
  "unusual_credit") — a free label, not from a fixed list;
- "value": one or two sentences of what it is / what it asserts;
- "structured": a small JSON object with the key facts you can read (amounts, dates, parties,
  relationships) — schemaless, only what is actually present;
- "needs_tag": true if this recurs often enough or matters enough that it SHOULD become a formal
  tag+rule (a human will decide), else false;
- "relates_to_subject": the id of the transaction/entity it bears on if any, else null;
- a confidence and reasoning.

Be honest: capture only what the document supports; never fabricate parties or amounts.

STRICT OUTPUT — return ONLY a JSON OBJECT (no markdown fences, no prose before or after):
{
  "type": "<snake_case label>",
  "value": "<what it is / asserts>",
  "structured": { ... },
  "needs_tag": true|false,
  "relates_to_subject": "<content_id or null>",
  "confidence": <0.0-1.0>,
  "reasoning": "<why>"
}
"""


@dataclass(frozen=True)
class ObservationRead:
    """The AI's structured read of one unmapped document/fact (the observation envelope's core)."""

    observation_type: str
    value: str
    structured: dict[str, Any] = field(default_factory=dict)
    needs_tag: bool = False
    relates_to_subject: str | None = None
    confidence: float | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class ObservationResult:
    """The result of one observation call — the read (or None if unparseable) + cost/flags."""

    read: ObservationRead | None
    input_tokens: int
    output_tokens: int
    model: str
    truncated: bool


async def reason_observation(context_json: str) -> ObservationResult:
    """Structure ONE unmapped document/fact into an observation envelope.

    ``context_json`` is the deterministically-assembled context (what little is known about the
    unmapped thing). Calls the extraction/reasoning tier (Sonnet by default, env-overridable) at
    temperature 0, guards truncation, parses defensively (a malformed
    response → ``read=None`` → the caller still records a minimal fallback observation, never drops
    the info). Raises :class:`~app.ai.client.AIClientError` on a transport failure OR a timeout.
    NEVER logs the context or the response — only counts + the chosen type.
    """
    # NOT wrapped in asyncio.wait_for: complete() bounds every attempt itself (B1), and an
    # outer wrapper would also bill the rate limiter's queueing time to this call's budget.
    result = await complete(
        model=settings.anthropic_model_reasoning,
        system=OBSERVATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_json}],
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
    )

    truncated = result.stop_reason == "max_tokens"
    if truncated:
        logger.warning("observation_response_truncated", output_tokens=result.output_tokens)
    read = _parse_read(result.text)
    logger.info(
        "observation_reasoning_done",
        observation_type=read.observation_type if read is not None else None,  # a label, not PII
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return ObservationResult(
        read=read,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        truncated=truncated,
    )


def _parse_read(text: str) -> ObservationRead | None:
    """Defensively parse the response into an ObservationRead (never raises)."""
    candidate = extract_json_object(text)
    if candidate is None:
        logger.warning("observation_parse_no_json_object")
        return None
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        logger.warning("observation_parse_bad_json")
        return None
    if not isinstance(data, dict):
        return None
    observation_type = opt_str(data.get("type"))
    value = opt_str(data.get("value"))
    if not observation_type or not value:
        return None  # a type + a value are the minimum for a usable observation
    structured = data.get("structured")
    return ObservationRead(
        observation_type=observation_type,
        value=value,
        structured=structured if isinstance(structured, dict) else {},
        needs_tag=bool(data.get("needs_tag")),
        relates_to_subject=opt_str(data.get("relates_to_subject")),
        confidence=coerce_optional_confidence(data.get("confidence")),
        reasoning=opt_str(data.get("reasoning")),
    )


__all__ = [
    "OBSERVATION_SYSTEM_PROMPT",
    "AIClientError",
    "ObservationRead",
    "ObservationResult",
    "reason_observation",
]
