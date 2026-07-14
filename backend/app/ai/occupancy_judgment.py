"""OC-2 occupancy-reasonableness JUDGMENT (LP-319) — an AI-at-rule-time rule.

The judgment slice of §3D: ~36 rules whose verdict CANNOT reduce to a deterministic tag query — the
AI IS the evaluator. OC-2 asks a senior-underwriter question ("is the stated occupancy plausible?")
and answers it by REASONING OVER THE STRUCTURED TAGS (occupancy.stated, address/consistency signals)
— never raw documents — so the judgment is grounded in the same clean facts everything else uses and
is reviewable. It concludes yes | no | unknown, cites the specific tags, and gives a confidence; it
NEVER guesses. This module is the raw AI call only — the same clone as Stage B (deterministic context
assembled by the caller, injected Reasoner seam, truncation guard, honest defensive parse, never logs
the context/response). The procedural armor (mandatory ratification, confidence-gating, fail-closed)
lives in the evaluator (:mod:`app.verification.rule_engine.oc2`).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_str
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 1024  # one loan's occupancy tags → a small reasoned judgment

# The judgment's value domain — ALWAYS includes "unknown" (never a fabricated certainty).
OCCUPANCY_REASONABLE_VALUES = ("yes", "no", "unknown")

OC2_OCCUPANCY_SYSTEM_PROMPT = """\
You are a senior mortgage underwriter making a REASONED JUDGMENT about ONE question: is the
borrower's STATED occupancy plausible for this loan?

You reason ONLY over the STRUCTURED TAGS handed to you below — never raw documents. The tags are
clean facts other checks already produced: what occupancy the borrower stated, whether address and
other signals are consistent with it, the type of the borrower's current address, and whether the
subject-property address is consistent across the file. Judge plausibility the way an underwriter
would: a stated PRIMARY residence that the signals contradict (e.g. the address signals point
elsewhere, or the subject looks like a second home / investment) is NOT reasonable; a stated
occupancy the signals support IS reasonable.

BE HONEST. If the tags do not support a judgment — they are missing, unknown, or genuinely
ambiguous — answer "unknown". NEVER guess, and NEVER treat a stated value as self-proving (the
borrower's claim is the thing under scrutiny, not the evidence).

Your reasoning MUST cite the SPECIFIC tags you relied on (by their tag id) and say what each
implied. Give a confidence that reflects genuine certainty.

STRICT OUTPUT — return ONLY a JSON OBJECT (no markdown fences, no prose before or after):
{
  "value": "yes|no|unknown",
  "confidence": <0.0-1.0>,
  "reasoning": "<why — cite the specific tags (occupancy.stated, occupancy.consistent_with_signals,
                 …) and what each implied>"
}
"""


@dataclass(frozen=True)
class OccupancyJudgment:
    """The underwriter-judge's verdict for one loan's occupancy reasonableness."""

    value: str  # yes | no | unknown
    confidence: float | None
    reasoning: str | None


@dataclass(frozen=True)
class OccupancyJudgmentResult:
    """The result of one OC-2 judgment — the verdict (or None if unparseable) + cost/flags."""

    judgment: OccupancyJudgment | None
    input_tokens: int
    output_tokens: int
    model: str
    truncated: bool


async def reason_oc2_occupancy(context_json: str) -> OccupancyJudgmentResult:
    """Judge whether ONE loan's stated occupancy is plausible, over its structured tags.

    ``context_json`` is ``{"occupancy_tags": {...}}`` — the structural-fact tags assembled
    deterministically by the evaluator (NEVER raw documents). Calls Opus at temperature 0, guards
    truncation, and parses defensively (a malformed response → ``judgment=None`` → the evaluator
    falls back to unknown/needs_review). Raises :class:`~app.ai.client.AIClientError` on a transport
    failure OR a timeout. NEVER logs the context or the response — only counts + the single verdict.
    """
    try:
        result = await asyncio.wait_for(
            complete(
                model=settings.anthropic_model_extraction,  # Opus — real judgment over the facts
                system=OC2_OCCUPANCY_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context_json}],
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
            ),
            timeout=settings.ai_request_timeout_seconds,
        )
    except TimeoutError as exc:
        logger.warning("oc2_reason_timeout", timeout_s=settings.ai_request_timeout_seconds)
        raise AIClientError("OC-2 occupancy judgment timed out") from exc

    truncated = result.stop_reason == "max_tokens"
    if truncated:
        logger.warning(
            "oc2_response_truncated", output_tokens=result.output_tokens, max_tokens=_MAX_TOKENS
        )
    judgment = _parse_judgment(result.text)
    logger.info(
        "oc2_reasoning_done",
        reasonable=judgment.value if judgment is not None else None,  # a single enum, not PII
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return OccupancyJudgmentResult(
        judgment=judgment,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        truncated=truncated,
    )


def _parse_judgment(text: str) -> OccupancyJudgment | None:
    """Defensively parse the response into an OccupancyJudgment (never raises)."""
    candidate = extract_json_object(text)
    if candidate is None:
        logger.warning("oc2_parse_no_json_object")
        return None
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        logger.warning("oc2_parse_bad_json")
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return OccupancyJudgment(
        value=value.strip(),
        confidence=coerce_optional_confidence(data.get("confidence")),
        reasoning=opt_str(data.get("reasoning")),
    )


__all__ = [
    "OC2_OCCUPANCY_SYSTEM_PROMPT",
    "OCCUPANCY_REASONABLE_VALUES",
    "AIClientError",
    "OccupancyJudgment",
    "OccupancyJudgmentResult",
    "reason_oc2_occupancy",
]
