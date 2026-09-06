"""LP-644 §1 — the per-stage timing that turns the ticket's projections into measurements.

The ticket's own numbers are a call count times a 4.3s mean taken from a FAILING run, and it says
so. These pin the arithmetic that replaces them — in particular the one distinction the whole
exercise depends on: cumulative model latency and stage wall-clock are different numbers under
concurrency, and reading one as the other would credit §2 with a saving it cannot deliver.
"""

from __future__ import annotations

from app.ai.stage_metrics import RunMetrics, StageMetrics


def test_a_call_accumulates_counts_tokens_and_latency() -> None:
    m = StageMetrics()
    m.record_call(input_tokens=100, output_tokens=20, seconds=4.0)
    m.record_call(input_tokens=200, output_tokens=30, seconds=6.0)

    assert m.calls == 2
    assert m.input_tokens == 300
    assert m.output_tokens == 50
    assert m.latency_seconds == 10.0
    assert m.mean_latency_seconds == 5.0


def test_mean_latency_of_a_stage_that_never_called_is_zero_not_a_crash() -> None:
    # Every stage is optional on some path — no transactions, a cache hit, a scoped run. A
    # ZeroDivisionError in instrumentation would fail a verification to describe it.
    assert StageMetrics().mean_latency_seconds == 0.0
    assert StageMetrics().tokens_per_minute == 0.0


def test_cumulative_latency_may_exceed_wall_time_under_concurrency() -> None:
    # THE DISTINCTION THE MODULE EXISTS FOR. Stage B runs at concurrency 8: eight 4s calls overlap
    # into ~4s of wall time while contributing 32s of cumulative model latency. Both are correct and
    # they answer different questions — only `wall_seconds` may be subtracted from the run.
    m = StageMetrics()
    for _ in range(8):
        m.record_call(input_tokens=10, output_tokens=5, seconds=4.0)
    m.wall_seconds = 4.5

    assert m.latency_seconds == 32.0
    assert m.wall_seconds == 4.5
    assert m.latency_seconds > m.wall_seconds  # not a bug — the concurrency factor


def test_tokens_per_minute_is_measured_over_wall_time() -> None:
    # LP-644 §4 will not raise the concurrency bound without this number: TPM is expected to bind
    # before RPM does, and a rejected Bedrock request still counts against quota.
    m = StageMetrics()
    m.record_call(input_tokens=900, output_tokens=100, seconds=1.0)
    m.wall_seconds = 30.0

    assert m.tokens_per_minute == 2000.0  # 1,000 tokens in half a minute


def test_the_run_sums_every_stage() -> None:
    run = RunMetrics()
    run.stage_a.record_call(input_tokens=1, output_tokens=1, seconds=2.0)
    run.stage_a.wall_seconds = 3.0
    run.stage_b.record_call(input_tokens=1, output_tokens=1, seconds=5.0)
    run.stage_b.wall_seconds = 6.0
    run.materialization.wall_seconds = 1.0

    assert run.ai_calls == 2
    assert run.ai_latency_seconds == 7.0
    assert run.ai_wall_seconds == 10.0


def test_the_non_ai_remainder_is_the_run_minus_the_stages() -> None:
    # The number the ticket turns on: it claims ~49% is the ceiling for everything in LP-644, which
    # only holds if the remainder really is about half.
    run = RunMetrics()
    run.stage_a.wall_seconds = 50.0
    run.stage_b.wall_seconds = 300.0
    run.materialization.wall_seconds = 110.0
    run.cross_source.wall_seconds = 4.0

    assert run.non_ai_seconds(946.0) == 482.0
    assert run.as_log_fields(946.0)["ai_wall_pct"] == 49


def test_the_remainder_never_goes_negative() -> None:
    # The stages are timed independently of the run, so a slight clock disagreement must print zero
    # rather than a negative that reads as a bug in the run instead of in the arithmetic.
    run = RunMetrics()
    run.stage_a.wall_seconds = 10.0
    assert run.non_ai_seconds(9.5) == 0.0


def test_a_zero_length_run_reports_zero_percent_rather_than_dividing() -> None:
    assert RunMetrics().as_log_fields(0.0)["ai_wall_pct"] == 0


def test_log_fields_carry_counts_and_seconds_only() -> None:
    # Instrumentation must never become a PII path: these lines go to CloudWatch alongside the rest
    # of the environment's logs, and the existing stage lines already hold to counts-only.
    m = StageMetrics()
    m.record_call(input_tokens=10, output_tokens=5, seconds=1.0)
    m.wall_seconds = 2.0

    fields = m.as_log_fields()
    assert set(fields) == {
        "ai_calls",
        "ai_latency_seconds",
        "ai_wall_seconds",
        "ai_mean_latency_seconds",
        "tokens_per_minute",
    }
    assert all(isinstance(v, int | float) for v in fields.values())
