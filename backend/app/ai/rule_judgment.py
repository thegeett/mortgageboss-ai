"""The GENERIC AI-at-rule-time judge (LP-324, generalizing LP-319's OC-2 judge).

One reusable call any judgment rule uses: the rule's spec supplies the system prompt (the
underwriter question) as DATA; this reasons over the structured-tag context the evaluator assembled
(never raw documents) and returns a value/confidence/reasoning. Same clone as the Stage-B judge:
injected Reasoner seam, temperature 0, truncation guard, honest defensive parse, never logs the
context/response. The procedural armor (mandatory ratification, confidence-gating, fail-closed) lives
in the evaluator, not here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.ai.client import AIClientError, complete
from app.ai.parsing import coerce_optional_confidence, extract_json_object, opt_str
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_TOKENS = 1024


@dataclass(frozen=True)
class RuleJudgment:
    """The judge's verdict for one subject (value drawn from the rule's declared value domain)."""

    value: str
    confidence: float | None
    reasoning: str | None


@dataclass(frozen=True)
class RuleJudgmentResult:
    """One judgment call's result — the verdict (or None if unparseable) + cost/honesty flags."""

    judgment: RuleJudgment | None
    input_tokens: int
    output_tokens: int
    model: str
    truncated: bool


# The AI-at-rule-time seam, shared by every rule evaluator that consults the model (judgment,
# consistency). Keyless tests inject a stub; None → the real model with the spec's prompt bound.
# One canonical alias so a change to the reasoner contract lands in exactly one place.
Reasoner = Callable[[str], Awaitable[RuleJudgmentResult]]


async def reason_rule_judgment(system_prompt: str, context_json: str) -> RuleJudgmentResult:
    """Ask ONE judgment question (``system_prompt``) over the structured-tag ``context_json``.

    Calls the extraction/reasoning tier (Sonnet by default, env-overridable) at temperature 0,
    guards truncation, parses defensively (a malformed response →
    ``judgment=None`` → the evaluator falls back to unknown/needs_review). Raises
    :class:`~app.ai.client.AIClientError` on a transport failure OR a timeout. NEVER logs the context
    or the response — only counts + the single verdict.
    """
    try:
        result = await asyncio.wait_for(
            complete(
                model=settings.anthropic_model_extraction,  # Sonnet by default — real judgment over the facts
                system=system_prompt,
                messages=[{"role": "user", "content": context_json}],
                max_tokens=_MAX_TOKENS,
                temperature=0.0,
            ),
            timeout=settings.ai_request_timeout_seconds,
        )
    except TimeoutError as exc:
        logger.warning("rule_judgment_timeout", timeout_s=settings.ai_request_timeout_seconds)
        raise AIClientError("rule judgment timed out") from exc

    truncated = result.stop_reason == "max_tokens"
    if truncated:
        logger.warning("rule_judgment_truncated", output_tokens=result.output_tokens)
    judgment = _parse_judgment(result.text)
    logger.info(
        "rule_judgment_done",
        value=judgment.value if judgment is not None else None,  # a single enum, not PII
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        stop_reason=result.stop_reason,
    )
    return RuleJudgmentResult(
        judgment=judgment,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        model=result.model,
        truncated=truncated,
    )


def _parse_judgment(text: str) -> RuleJudgment | None:
    """Defensively parse the response into a RuleJudgment (never raises)."""
    candidate = extract_json_object(text)
    if candidate is None:
        logger.warning("rule_judgment_parse_no_json_object")
        return None
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        logger.warning("rule_judgment_parse_bad_json")
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return RuleJudgment(
        value=value.strip(),
        confidence=coerce_optional_confidence(data.get("confidence")),
        reasoning=opt_str(data.get("reasoning")),
    )


__all__ = [
    "AIClientError",
    "Reasoner",
    "RuleJudgment",
    "RuleJudgmentResult",
    "reason_rule_judgment",
]
