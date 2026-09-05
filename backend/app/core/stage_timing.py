"""Elapsed time and call counts for the verification stages (LP-644 §1).

WHY THIS EXISTS BEFORE ANY OPTIMISATION. Every projection in LP-644 is a call count multiplied by a
mean of 4.3s, and that mean predates every fix since and was taken on a FAILING run. Nothing in the
system records how long a stage actually TOOK, so the split between AI and non-AI time — the number
that decides whether the rest of that ticket is worth doing — is the one with the least evidence
behind it. Three things could each move the estimates materially and only measurement separates
them: the stale mean, per-call latency under concurrency (server-side contention would shrink the
concurrency win specifically), and the fact that every call count comes from ONE file.

A LEAF MODULE ON PURPOSE, like `run_limits`. It imports nothing from `app`, so a stage can time
itself without dragging the import graph anywhere new.

CALLS AND SUBJECTS ARE COUNTED SEPARATELY, and that is the point rather than an accident. Today
Stage B issues one call per deposit, so the two numbers are equal and the distinction looks like
pedantry. LP-644 §5 proposes batching fifteen deposits per call: the moment that lands, calls falls
and subjects does not, and a single number would have hidden which one moved.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StageTiming:
    """A stage's wall-clock cost, accumulated as it runs.

    Wall clock, NOT summed per-call latency: under concurrency those diverge, and the question this
    is here to answer is how long the RUN takes. Summing latencies across eight concurrent calls
    would report eight seconds for a stage that took one.
    """

    #: Model calls actually issued — including the ones that failed and were retried away, because
    #: a failing call costs the same wall time as a successful one and the baseline was measured on
    #: a run full of them.
    calls: int = 0
    #: Things judged. Equal to `calls` while each subject gets its own call; the two separate under
    #: batching, which is the change this instrumentation exists to evaluate.
    subjects: int = 0
    _started: float = field(default_factory=time.monotonic, repr=False)

    def record_call(self, *, subjects: int = 1) -> None:
        self.calls += 1
        self.subjects += subjects

    @property
    def elapsed_seconds(self) -> float:
        return round(time.monotonic() - self._started, 3)

    def as_log_fields(self) -> dict[str, float | int]:
        """The fields to splat into a stage's completion log line."""
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "calls": self.calls,
            "subjects": self.subjects,
        }


__all__ = ["StageTiming"]
