"""Tests for AI cost estimation (LP-37)."""

import structlog
from app.ai.cost import DEFAULT_RATE, PRICING, estimate_cost


def test_estimate_cost_known_model() -> None:
    model = "claude-haiku-4-5"
    in_rate, out_rate = PRICING[model]
    cost = estimate_cost(model=model, input_tokens=1000, output_tokens=500)
    assert cost == 1000 * in_rate + 500 * out_rate
    assert cost > 0


def test_estimate_cost_zero_tokens_is_zero() -> None:
    cost = estimate_cost(model="claude-sonnet-4-5", input_tokens=0, output_tokens=0)
    assert cost == 0.0


def test_estimate_cost_unknown_model_falls_back_and_warns() -> None:
    with structlog.testing.capture_logs() as logs:
        cost = estimate_cost(model="not-a-real-model", input_tokens=1000, output_tokens=1000)
    # Documented fallback: unknown model contributes 0.0.
    assert cost == 1000 * DEFAULT_RATE[0] + 1000 * DEFAULT_RATE[1] == 0.0
    assert any(
        entry["event"] == "ai_cost_unknown_model" and entry.get("model") == "not-a-real-model"
        for entry in logs
    )
