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

# Values are ESTIMATES, in USD PER TOKEN (published per-million price / 1_000_000),
# keyed by the EXACT model string that was invoked — see `resolve_model`, which under
# AI_PROVIDER=bedrock hands the inference-profile id to both the invoke and the costing.
# Keeping these current is a maintenance task, not a one-time fact.
#
# VERIFIED 2026-08-04 (B1) against Anthropic's published per-million rates. The prior
# Opus 4.8 entry was WRONG — 15.00/75.00, i.e. 3x the real price — so every Opus-tier
# cost estimate recorded before this date is overstated threefold. Haiku 4.5 and
# Sonnet 4.5 were already correct.
#
# ⚠️ The Bedrock rows below assume Bedrock's per-token rates equal the direct API's.
# That is the B1 ticket's stated premise and it is NOT independently confirmed here:
# Anthropic's own documentation describes Bedrock as partner-operated with separate
# pricing published by AWS. The rates are therefore a starting estimate — reconcile
# them against the AWS Bedrock pricing page and the first real invoice before anyone
# treats `Extraction.cost_estimate` as authoritative for Bedrock traffic.
PRICING: dict[str, tuple[float, float]] = {
    # --- Direct Anthropic API (AI_PROVIDER=anthropic) ------------------------
    # model string: (input_price_per_token, output_price_per_token)
    "claude-haiku-4-5": (1.00 / 1_000_000, 5.00 / 1_000_000),
    "claude-sonnet-4-5": (3.00 / 1_000_000, 15.00 / 1_000_000),
    # Opus 4.8 — not a configured tier today, retained because historical rows carry
    # it and a missing key silently prices them at $0.
    "claude-opus-4-8": (5.00 / 1_000_000, 25.00 / 1_000_000),
    # --- Amazon Bedrock (AI_PROVIDER=bedrock) --------------------------------
    # The `us.` CROSS-REGION INFERENCE PROFILE ids — the only form these models accept
    # (the bare `anthropic.claude-*` ids are rejected: no on-demand throughput). These
    # are the exact strings `resolve_model` returns, so they must match byte for byte
    # or every Bedrock call prices at $0 with only a warning.
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00 / 1_000_000, 5.00 / 1_000_000),
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (3.00 / 1_000_000, 15.00 / 1_000_000),
}

# Documented fallback for a model absent from PRICING: contribute 0.0 so an
# unknown model never inflates the estimate, and log a warning so the gap is
# visible and the table can be updated.
DEFAULT_RATE: tuple[float, float] = (0.0, 0.0)


#: Prompt-cache multipliers on the base INPUT rate. A cache write costs more than an ordinary input
#: token (the provider stores the prefix); a read costs a small fraction. Applied to whatever the
#: model's input rate is, rather than duplicating the whole PRICING table at two more rates.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def estimate_cost(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimate the USD cost of a call, including any prompt-cache traffic.

    An unknown model falls back to :data:`DEFAULT_RATE` (``0.0``) and logs
    ``ai_cost_unknown_model`` so the missing entry is noticed. The result is an
    estimate for tracking, not a billing figure.

    LP-628 review — THE CACHE TOKENS ARE NOT OPTIONAL DETAIL ON THE CHUNKED PATH. ``input_tokens`` is
    the uncached remainder, so on a cached call it excludes the document itself: a 3-chunk statement
    bills its bytes once as a write and twice as reads, none of which used to reach this function. The
    stored estimate was low by roughly an order of magnitude for exactly the documents the chunking
    work was built for. Both default to 0, so an uncached caller is unchanged.
    """
    rates = PRICING.get(model)
    if rates is None:
        logger.warning("ai_cost_unknown_model", model=model)
        rates = DEFAULT_RATE
    in_rate, out_rate = rates
    return (
        input_tokens * in_rate
        + cache_write_tokens * in_rate * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * in_rate * CACHE_READ_MULTIPLIER
        + output_tokens * out_rate
    )
