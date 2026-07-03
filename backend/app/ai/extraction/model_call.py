"""Shared truncation-guarded extraction model call (LP-102).

Every per-type extractor made the SAME model call — ``complete(...)`` at a fixed ``max_tokens`` —
then parsed the text. None checked ``stop_reason``, so a response the model TRUNCATED at the token
ceiling (``stop_reason == "max_tokens"``, cut off mid-JSON) silently failed to parse and was
misreported as ``"could not parse extraction"`` → an empty ``NEEDS_REVIEW`` extraction. A pay stub
(many earnings/deduction/tax line items, each with a verbatim snippet) overflowed 4096 tokens and
hit exactly this; ``investment_account`` hit it on its densest doc too. Under Opus 4.8's more
thorough transcription, any verbose type can.

This is the ONE shared place that guards against it, so all extractors benefit without duplicating
the logic. The guard:

* Attempt 1 runs at the type's own budget.
* If it TRUNCATED (``stop_reason == "max_tokens"``) → log it **distinctly** (not as a parse
  failure) and retry **exactly once** at a high ceiling (:data:`RETRY_MAX_TOKENS`, one decisive
  jump — not incremental bumps).
* If the retry STILL truncates → give up and surface the **honest** :data:`TRUNCATED_REASON`
  (never the misleading "could not parse"): a self-inflicted truncation is not an unreadable
  document, and a doc overflowing 16k output tokens genuinely warrants a human look.
* Retries fire **only** on truncation — never on other stop reasons, parse failures, or AI errors
  (more budget can't fix those). At most two attempts total.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.ai.client import AIClientError, AICompletion, complete
from app.core.config import settings

logger = structlog.get_logger(__name__)

# The single, decisive high-ceiling retry budget on truncation (matches ``tax_return``, the most
# verbose type). One jump, not incremental bumps.
RETRY_MAX_TOKENS = 16384

# The HONEST reason surfaced when even the high-ceiling retry truncates — deliberately NOT the
# misleading "could not parse extraction" (that mislabels a truncation as an unreadable document).
TRUNCATED_REASON = "response truncated - document too dense to extract in full"


@dataclass(frozen=True)
class ExtractionCall:
    """The outcome of a truncation-guarded extraction model call.

    ``text`` is the model output ready to parse, or ``None`` when the call failed or was truncated
    even after the retry. When ``text`` is ``None``, ``failure_reason`` carries the honest reason
    for the extractor to pass to its ``.failed(reason)`` — ``TRUNCATED_REASON`` for a persistent
    truncation (``truncated`` is then ``True``), else an AI-call failure. Token counts are from the
    response that produced ``text`` (or the final truncated response).
    """

    text: str | None
    input_tokens: int | None
    output_tokens: int | None
    failure_reason: str | None
    truncated: bool


async def _attempt(
    *, system: str, message: dict[str, Any], max_tokens: int, log_label: str, phase: str
) -> AICompletion | None:
    """One model call; ``None`` on an AI error (logged, metadata-only — never content/PII)."""
    try:
        return await complete(
            model=settings.anthropic_model_extraction,
            system=system,
            messages=[message],
            max_tokens=max_tokens,
        )
    except AIClientError:
        logger.warning("extraction_ai_failed", extractor=log_label, phase=phase)
        return None


async def run_extraction_completion(
    *,
    system: str,
    message: dict[str, Any],
    max_tokens: int,
    log_label: str,
    retry_max_tokens: int = RETRY_MAX_TOKENS,
) -> ExtractionCall:
    """Call the extraction model with the shared TRUNCATION GUARD (LP-102). Never raises.

    Returns an :class:`ExtractionCall`: ``text`` set (ready to parse) on success, or ``text=None``
    with an honest ``failure_reason`` on an AI failure or a persistent truncation. See the module
    docstring for the guard's policy (one retry at ``retry_max_tokens``, truncation-only).
    """
    first = await _attempt(
        system=system, message=message, max_tokens=max_tokens, log_label=log_label, phase="first"
    )
    if first is None:
        return ExtractionCall(None, None, None, "AI call failed", False)
    if first.stop_reason != "max_tokens":
        return ExtractionCall(first.text, first.input_tokens, first.output_tokens, None, False)

    # Truncated: the model was cut off mid-JSON. Log distinctly (NOT a parse failure) + retry once.
    logger.warning(
        "extraction_truncated",
        extractor=log_label,
        max_tokens=max_tokens,
        retry_max_tokens=retry_max_tokens,
    )
    second = await _attempt(
        system=system,
        message=message,
        max_tokens=retry_max_tokens,
        log_label=log_label,
        phase="retry",
    )
    if second is None:
        return ExtractionCall(None, None, None, "AI call failed", False)
    if second.stop_reason == "max_tokens":
        # Still truncated at the high ceiling — give up honestly (never "could not parse").
        logger.warning(
            "extraction_truncated_after_retry",
            extractor=log_label,
            retry_max_tokens=retry_max_tokens,
        )
        return ExtractionCall(
            None, second.input_tokens, second.output_tokens, TRUNCATED_REASON, True
        )
    return ExtractionCall(second.text, second.input_tokens, second.output_tokens, None, False)
