"""Shared truncation-guarded extraction model call (LP-102).

Every per-type extractor made the SAME model call — ``complete(...)`` at a fixed ``max_tokens`` —
then parsed the text. None checked ``stop_reason``, so a response the model TRUNCATED at the token
ceiling (``stop_reason == "max_tokens"``, cut off mid-JSON) silently failed to parse and was
misreported as ``"could not parse extraction"`` → an empty ``NEEDS_REVIEW`` extraction. A pay stub
(many earnings/deduction/tax line items, each with a verbatim snippet) overflowed 4096 tokens and
hit exactly this; ``investment_account`` hit it on its densest doc too. Under a thorough
transcription model, any verbose type can.

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

Per-type ``_MAX_TOKENS`` SIZING RULE (LP-102/LP-103) — right-size by OUTPUT SHAPE, do NOT blanket-raise:

* **Unbounded catch-all output** — the prompt says "capture every X" (a variable-length list of line
  items each with a verbatim snippet: holdings, transactions, expense lines, schedule rows, contract
  terms) → give a **generous** budget: **8192** (e.g. pay_stub, bank_statement, investment_account,
  retirement_account, profit_and_loss, purchase_agreement), or **16384** for the densest (tax_return's
  nested 1040 + schedules).
* **Bounded fixed-form output** — a fixed set of fields, no unbounded list (W-2 boxes, a VOE, a
  driver's license) → a **small** budget (2048 to 4096) is correct and *intentional*.

Why not just set everything high: a right-sized budget encodes a useful size EXPECTATION, so a
truncation against it is a meaningful ANOMALY signal (it's how the pay-stub and investment-account
bugs were found). A uniform high ceiling would blind the system to output size and let a runaway
output generate expensively before anything stopped it. The guard above is the backstop that makes
right-sizing (vs. over-provisioning) safe — a mis-sized type still fails HONESTLY, never silently.
When adding a new extractor, size its budget by this rule from the start.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.ai.client import TRUNCATED_STOP_REASON, AIClientError, AICompletion, complete
from app.core.config import settings

logger = structlog.get_logger(__name__)

# The single, decisive high-ceiling retry budget on truncation — one jump, not incremental bumps.
# It must sit ABOVE the largest first-attempt budget (16384, the ≥2-nested-list tier: credit_report,
# tax_return), or the "retry" re-rolls the SAME ceiling and a genuine truncation truncates again → a
# wrongful FAILED (LP-445 found this: credit_report._MAX_TOKENS == RETRY_MAX_TOKENS == 16384, zero
# headroom). 32768 doubles the top tier — real headroom for the densest instance (a 40-tradeline
# tri-merge) — while staying HALF of the extraction model's 64K output ceiling (claude-sonnet-4-5 AND
# claude-haiku-4-5 both cap at 64K output — LP-457 verified the switch to Haiku 4.5 leaves this ceiling
# reachable, not stranded), so a runaway output still stops well before the API limit and a >32K response
# genuinely warrants a human look. The per-type first-attempt tiers (4096/8192/16384) are UNCHANGED — they
# still encode the size expectation the sizing guard asserts; only this decisive retry ceiling moves.
RETRY_MAX_TOKENS = 32768

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
    if first.stop_reason != TRUNCATED_STOP_REASON:
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
    if second.stop_reason == TRUNCATED_STOP_REASON:
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
