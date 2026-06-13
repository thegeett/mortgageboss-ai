"""AI cost estimation (LP-37).

A per-call USD cost ESTIMATE from token usage and a per-model pricing table.
This is **not** billing-grade: the table is an estimate that MUST be kept current
with Anthropic's published pricing, and the model strings are configuration to
verify (see :mod:`app.core.config`). The estimate feeds
``Extraction.cost_estimate`` (LP-16) and ``Verification.total_cost_estimate``
(LP-18) — callers persist what this computes.
"""

import structlog

logger = structlog.get_logger(__name__)

# TODO(pricing): VERIFY against current Anthropic pricing before relying on these.
# Values are ESTIMATES, in USD PER TOKEN (published per-million price / 1_000_000),
# keyed by the model strings in settings (anthropic_model_classification /
# anthropic_model_extraction — themselves TODO(models) to verify). Keeping these
# current is a maintenance task, not a one-time fact.
PRICING: dict[str, tuple[float, float]] = {
    # model string: (input_price_per_token, output_price_per_token)
    # --- placeholders to verify --------------------------------------------
    "claude-haiku-4-5": (1.00 / 1_000_000, 5.00 / 1_000_000),
    "claude-sonnet-4-5": (3.00 / 1_000_000, 15.00 / 1_000_000),
}

# Documented fallback for a model absent from PRICING: contribute 0.0 so an
# unknown model never inflates the estimate, and log a warning so the gap is
# visible and the table can be updated.
DEFAULT_RATE: tuple[float, float] = (0.0, 0.0)


def estimate_cost(*, model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate the USD cost of a call: ``input*in_rate + output*out_rate``.

    An unknown model falls back to :data:`DEFAULT_RATE` (``0.0``) and logs
    ``ai_cost_unknown_model`` so the missing entry is noticed. The result is an
    estimate for tracking, not a billing figure.
    """
    rates = PRICING.get(model)
    if rates is None:
        logger.warning("ai_cost_unknown_model", model=model)
        rates = DEFAULT_RATE
    in_rate, out_rate = rates
    return input_tokens * in_rate + output_tokens * out_rate
