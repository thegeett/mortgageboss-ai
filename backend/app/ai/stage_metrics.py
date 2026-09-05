"""Per-stage AI cost + latency for one verification run (LP-644 §1).

**Instrumentation only. No behaviour changes, no prompt, context or threshold is touched.**

LP-644 sizes every optimisation it proposes from ONE file's call counts multiplied by a 4.3s mean
latency taken from LP-635 — on a run that FAILED. That mean predates every fix since, per-call
latency under concurrency may not match serial latency, and the counts come from a single
document-heavy file. So the ticket's four-row table is a projection, and the split between AI
waiting and everything else — the number deciding whether the rest of the ticket is worth doing —
is the one with the least evidence behind it. This module is what turns those rows into
measurements.

⚠️ TWO DIFFERENT SECONDS, AND CONFLATING THEM IS THE WHOLE TRAP. Under concurrency they diverge by
the concurrency factor, and each answers a different question:

* ``latency_seconds`` — CUMULATIVE model latency, summed per call. Comparable to LP-635's
  "2,542s of cumulative model latency" and the right denominator for a per-call mean. Under
  concurrency 8 it can exceed the wall-clock of the whole run, which is not a bug.
* ``wall_seconds`` — elapsed time the STAGE actually took. This is what a faster run means, and the
  only one that may be subtracted from the run's total.

Reading a cumulative figure as wall-clock would credit §2 with a saving it cannot deliver, which is
precisely the error §1 exists to prevent.

The accumulators are mutable and run-scoped, threaded exactly like ``TagCaches`` — each stage
records into its own, and the run reads them all at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StageMetrics:
    """One stage's AI accounting for this run. Mutated in place by the stage that owns it."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    #: CUMULATIVE across calls — sums under concurrency. See the module docstring.
    latency_seconds: float = 0.0
    #: The stage's own elapsed time, set once by the stage. Includes its non-AI work (fingerprinting,
    #: tag building), which is why the run's non-AI remainder is computed from THIS and not from
    #: ``latency_seconds``.
    wall_seconds: float = 0.0

    def record_call(self, *, input_tokens: int, output_tokens: int, seconds: float) -> None:
        """Record ONE completed AI call. Called for a successful call only.

        A failed call is deliberately not counted: it has no tokens to attribute, and counting it
        would deflate the per-call mean exactly when the backend is degraded — the reading most
        likely to be looked at. The breaker already counts failures, and it is the honest home for
        that number.
        """
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.latency_seconds += seconds

    @property
    def mean_latency_seconds(self) -> float:
        """Mean per-call latency — the figure LP-644's projections rest on (it assumed 4.3s)."""
        return self.latency_seconds / self.calls if self.calls else 0.0

    @property
    def tokens_per_minute(self) -> float:
        """Observed TPM for this stage, over its WALL time.

        LP-644 §4 will not raise the concurrency bound without this: `bedrock_rpm_budget`'s own
        comment records that TOKENS per minute is expected to bind before requests do on
        document-heavy work, and that TPM was unmeasured. A rejected Bedrock request still counts
        against quota, so pacing at a ceiling nobody has measured turns one throttle into a
        self-sustaining one.
        """
        if self.wall_seconds <= 0:
            return 0.0
        return (self.input_tokens + self.output_tokens) * 60.0 / self.wall_seconds

    def as_log_fields(self) -> dict[str, object]:
        """The stage's numbers, rounded for a log line. Counts + seconds only — never content."""
        return {
            "ai_calls": self.calls,
            "ai_latency_seconds": round(self.latency_seconds, 1),
            "ai_wall_seconds": round(self.wall_seconds, 1),
            "ai_mean_latency_seconds": round(self.mean_latency_seconds, 2),
            "tokens_per_minute": round(self.tokens_per_minute),
        }


@dataclass
class RunMetrics:
    """Every AI stage's metrics for one run, threaded like :class:`TagCaches`.

    The four stages are the four places that make AI calls (LP-644's table). The ``rules`` stage is
    deterministic by ADR — AI for perception only — so it has no row here and nothing to win.
    """

    stage_a: StageMetrics = field(default_factory=StageMetrics)
    stage_b: StageMetrics = field(default_factory=StageMetrics)
    materialization: StageMetrics = field(default_factory=StageMetrics)
    cross_source: StageMetrics = field(default_factory=StageMetrics)

    def _stages(self) -> tuple[StageMetrics, ...]:
        return (self.stage_a, self.stage_b, self.materialization, self.cross_source)

    @property
    def ai_calls(self) -> int:
        return sum(s.calls for s in self._stages())

    @property
    def ai_latency_seconds(self) -> float:
        """Cumulative model latency across every stage — LP-635's 2,542s figure, measured."""
        return sum(s.latency_seconds for s in self._stages())

    @property
    def ai_wall_seconds(self) -> float:
        """Elapsed time spent INSIDE the AI stages. The honest numerator for "AI is half the run"."""
        return sum(s.wall_seconds for s in self._stages())

    def non_ai_seconds(self, run_wall_seconds: float) -> float:
        """The run's remainder: snapshot build, the rule engine, and DB work.

        THE NUMBER THE WHOLE TICKET TURNS ON. LP-644 estimates AI waiting at ~464s of a 946s run and
        concludes "~49% is the ceiling for everything in this ticket". If the remainder is much
        larger than that, §2-§5 are chasing a smaller prize than the ticket claims and the effort
        belongs elsewhere. Floored at zero rather than allowed to go negative: the stages are timed
        independently of the run, and a clock that disagrees slightly should not print a negative
        remainder that reads as a bug in the run rather than in the arithmetic.
        """
        return max(0.0, run_wall_seconds - self.ai_wall_seconds)

    def as_log_fields(self, run_wall_seconds: float) -> dict[str, object]:
        """The run-level split, for ``verification_run_done``."""
        non_ai = self.non_ai_seconds(run_wall_seconds)
        return {
            "ai_calls": self.ai_calls,
            "ai_latency_seconds": round(self.ai_latency_seconds, 1),
            "ai_wall_seconds": round(self.ai_wall_seconds, 1),
            "non_ai_seconds": round(non_ai, 1),
            "ai_wall_pct": (
                round(100.0 * self.ai_wall_seconds / run_wall_seconds)
                if run_wall_seconds > 0
                else 0
            ),
            "stage_a_wall_seconds": round(self.stage_a.wall_seconds, 1),
            "stage_b_wall_seconds": round(self.stage_b.wall_seconds, 1),
            "materialization_wall_seconds": round(self.materialization.wall_seconds, 1),
            "cross_source_wall_seconds": round(self.cross_source.wall_seconds, 1),
        }


__all__ = ["RunMetrics", "StageMetrics"]
