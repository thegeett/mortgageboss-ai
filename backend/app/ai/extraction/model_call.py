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

from app.ai.client import (
    TRUNCATED_STOP_REASON,
    AIClientError,
    AICompletion,
    complete,
    infra_failure_kind,
    is_rerunnable_infra,
)
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
# FAIL-SAFE if that ceiling assumption is ever wrong: were a model's real max_output below a requested
# max_tokens, the API rejects the call, ``_attempt`` catches it (AIClientError) and returns None → an honest
# "AI call failed", never a crash. So 32768 being reachable is a COST/coverage property, not a safety one.
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
    #: LP-464 — set when the call never completed on infrastructure: ``rate_limited`` (throttled),
    #: ``oversized`` (payload over the document limit), or ``failed`` (other AI error). A THROTTLE must never
    #: be recorded as a content failure (the LP-462 distinction, now on the extraction path): the pipeline
    #: reads it (via the extractor's ``reasoning``, which carries ``failure_reason``) to record a throttled
    #: extraction as re-runnable, not a coverage gap. ``None`` on success or a truncation give-up.
    infra_failure: str | None = None
    #: LP-628 review — the prompt-cache halves of the input, which `input_tokens` EXCLUDES once caching
    #: is in play. Carried so a cost estimate can price them at their own rates (a write ~1.25x an input
    #: token, a read ~0.1x) instead of pricing only the uncached remainder — which on a cached call is
    #: everything except the document itself.
    #:
    #: LEFT AT 0 ON THIS PATH, and that is a statement of fact rather than an omission: caching is
    #: requested by exactly one caller (`chunked.py`, via `cache=True`), and it builds its own
    #: `ExtractionCall`. A whole-document call sends no cache marker, so both are genuinely zero. If
    #: that ever changes, populate them from the completion HERE — and note that the 128 extractor
    #: tests stub the completion as a SimpleNamespace, so they will need the fields too.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


async def _attempt(
    *, system: str, message: dict[str, Any], max_tokens: int, log_label: str, phase: str
) -> tuple[AICompletion | None, str | None]:
    """One model call → ``(completion, None)`` on success, ``(None, infra_kind)`` on an AI error.

    On failure, classifies the AIClientError by its underlying cause (LP-462 ``infra_failure_kind``:
    ``rate_limited`` / ``oversized`` / ``failed``) and — LP-464's 1a hardening — logs BOTH that kind AND the
    raw cause type (``ValueError``, ``RateLimitError``, …). We previously logged only "extraction_ai_failed"
    with no cause, so a crash gave the *what* but never the *where*; recording the cause type restores the
    location that a full diagnosis phase otherwise costs. Metadata-only — never content/PII.
    """
    try:
        completion = await complete(
            model=settings.anthropic_model_extraction,
            system=system,
            messages=[message],
            max_tokens=max_tokens,
        )
        return completion, None
    except AIClientError as err:
        kind = infra_failure_kind(err)
        cause = err.__cause__
        logger.warning(
            "extraction_ai_failed",
            extractor=log_label,
            phase=phase,
            error_kind=kind,  # rate_limited / oversized / failed
            cause_type=(type(cause).__name__ if cause is not None else None),  # the WHERE (1a)
        )
        return None, kind


def _failure_reason(infra_kind: str | None) -> str:
    """The ``failure_reason`` an extractor surfaces for a failed call.

    A RE-RUNNABLE infrastructure outcome carries its machine constant through, so the pipeline
    records it as infrastructure rather than a content coverage gap (LP-464). Any other AI error
    keeps the human "AI call failed".

    LP-636 defect 2: this used to pass through only ``INFRA_RATE_LIMITED``, which was fine when
    that constant meant "any transient cause". Now that connection and server failures have their
    own labels, the test has to be membership of :data:`RERUNNABLE_INFRA_KINDS` — an equality check
    against one member would drop the other two out of the re-runnable branch and record a dead
    socket as a content failure."""
    if infra_kind is not None and is_rerunnable_infra(infra_kind):
        return infra_kind
    return "AI call failed"


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
    first, first_kind = await _attempt(
        system=system, message=message, max_tokens=max_tokens, log_label=log_label, phase="first"
    )
    if first is None:
        return ExtractionCall(None, None, None, _failure_reason(first_kind), False, first_kind)
    if first.stop_reason != TRUNCATED_STOP_REASON:
        return ExtractionCall(first.text, first.input_tokens, first.output_tokens, None, False)

    # Truncated: the model was cut off mid-JSON. Log distinctly (NOT a parse failure) + retry once.
    logger.warning(
        "extraction_truncated",
        extractor=log_label,
        max_tokens=max_tokens,
        retry_max_tokens=retry_max_tokens,
    )
    second, second_kind = await _attempt(
        system=system,
        message=message,
        max_tokens=retry_max_tokens,
        log_label=log_label,
        phase="retry",
    )
    if second is None:
        return ExtractionCall(None, None, None, _failure_reason(second_kind), False, second_kind)
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
