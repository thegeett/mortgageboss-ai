"""LP-644 §1 — the instrumentation that has to land before anything in that ticket is chosen.

WHAT THIS CAN AND CANNOT PROVE. It cannot show that a stage's reported elapsed time is CORRECT —
that needs a real run against a real model. It can show the counter is wired to something that
moves: a timing that always reports zero calls, or an elapsed that never advances, is the failure
that would make every number in LP-644 look freshly measured while being as invented as the 4.3s
mean it replaces. That is the specific way instrumentation lies, so that is what is asserted.
"""

from __future__ import annotations

import time

from app.core.stage_timing import StageTiming


def test_a_fresh_timing_has_counted_nothing() -> None:
    timing = StageTiming()
    assert timing.calls == 0
    assert timing.subjects == 0


def test_calls_and_subjects_move_independently() -> None:
    """THE WHOLE REASON BOTH ARE RECORDED. Today Stage B issues one call per deposit and the two
    numbers are equal, which makes the pair look redundant. LP-644 §5 batches fifteen deposits into
    one call — the change this instrumentation exists to evaluate — and at that moment `calls` falls
    while `subjects` does not. A single number could not show which one moved."""
    timing = StageTiming()
    for _ in range(3):
        timing.record_call()  # one subject each, the Stage B shape today
    assert (timing.calls, timing.subjects) == (3, 3)

    timing.record_call(subjects=15)  # the batched shape
    assert (timing.calls, timing.subjects) == (4, 18)


def test_elapsed_advances_with_real_time() -> None:
    """The positive control. An elapsed that never moves reports a stage as free, which is worse
    than reporting nothing: a zero looks like a measurement."""
    timing = StageTiming()
    first = timing.elapsed_seconds
    time.sleep(0.02)
    second = timing.elapsed_seconds

    assert second > first, "elapsed_seconds did not advance across a real sleep"
    assert first >= 0.0


def test_the_log_fields_carry_all_three() -> None:
    """A stage splats these into its completion line, so a missing key is a silently absent column
    in the only place these numbers are ever read."""
    timing = StageTiming()
    timing.record_call(subjects=15)

    fields = timing.as_log_fields()

    assert set(fields) == {"elapsed_seconds", "calls", "subjects"}
    assert fields["calls"] == 1
    assert fields["subjects"] == 15
