"""How long one rule-engine pass is allowed to take (LP-635).

A LEAF MODULE ON PURPOSE. These are pure arithmetic over a document count, and THREE callers need
them: the API that enqueues the pass, the stuck-run watchdog that decides a run is dead, and the
deploy CLI that supersedes a stuck one. Two of those are request-path code.

Living in :mod:`app.tasks.verification_rules` — where they started — made the API import the task
module, and through it Celery and the whole rule engine: 263 ``app.*`` modules at import time, which
is exactly what that module's own function-local ``import run_rule_engine_pass`` was arranged to
avoid. Splitting the policy from the task keeps one definition of "how long is too long" without
making an HTTP handler pay for the worker.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# The pass's time limits — LP-635
# ---------------------------------------------------------------------------
# THESE SCALE WITH THE FILE, and that is the fix. A fixed limit was never wrong about the clock; it
# was wrong about the assumption underneath it, and it could not notice. Its own comment read:
#
#     RULE_ENGINE_SOFT_LIMIT_SECONDS = 900  # 15 min — a 30-doc run (~282s) finishes with wide headroom
#
# That is 9.4 seconds per document. LF-AWBB's COMPLETED run is 747 seconds over 21 documents —
# 35.6 s/doc, nearly four times the assumption — so by the time LF-ZE9N (44 documents) arrived, the
# "wide headroom" was a deficit. The constant never drifted; the cost per document grew underneath
# it, and a constant cannot report that. Making the limit a function of the thing that drives the
# runtime is what stops the next silent divergence: if the cost per document grows again, files get
# slower rather than suddenly unverifiable, and the measurement below is what needs revisiting.
#
# THIS IS NOT THE WHOLE FIX and should not be mistaken for one. LP-635 ranks "raise the limit" LAST,
# behind understanding why a 44-document file needs 591 model calls at all. This buys those files the
# ability to finish; it does not make finishing cheap.

#: Measured, not chosen: LF-AWBB's completed run, 747s over 21 documents, on 2026-08-30.
#: Re-measure before trusting it — this is exactly the number whose staleness caused the incident.
MEASURED_SECONDS_PER_DOCUMENT = 35.6

#: Headroom over the measurement. A soft limit must be loose enough that a healthy run never trips it
#: (tripping is terminal — see ``terminal_on`` in ``app.tasks.verification_rules``) and tight
#: enough to catch a genuinely stuck
#: one. 1.7x covers the run-to-run variance seen between LF-AWBB's ~10-minute and 12m27s runs.
LIMIT_HEADROOM = 1.7

#: The floor keeps today's behaviour for ordinary files: a small file gets the same 15 minutes it
#: always had, so this change cannot make anything detect a stuck run more slowly than before.
RULE_ENGINE_MIN_SOFT_SECONDS = 900

#: The ceiling is a REFUSAL, not a budget. Past this, a file needs the resumable pass LP-635 asks for
#: (item 3), not a longer lease on a worker slot — one task holding a prefork slot for an hour
#: starves everything queued behind it. A file that exceeds this will still fail; it will fail having
#: been given an hour, which is the signal that the pass itself has to change.
RULE_ENGINE_MAX_SOFT_SECONDS = 3600

#: Soft -> hard -> watchdog, each with the same 300s gap the original constants used. The ordering is
#: load-bearing: the soft limit lets the task mark its own run FAILED, the hard limit SIGKILLs a task
#: that ignored it, and the watchdog catches a hard-killed task that could not write its own marker.
LIMIT_STEP_SECONDS = 300

#: Backwards-compatible defaults — the decorator needs values at import time, and they are the bounds
#: a task gets when it is enqueued without per-file limits.
RULE_ENGINE_SOFT_LIMIT_SECONDS = RULE_ENGINE_MIN_SOFT_SECONDS
RULE_ENGINE_HARD_LIMIT_SECONDS = RULE_ENGINE_MIN_SOFT_SECONDS + LIMIT_STEP_SECONDS

#: The widest bound any run can be given — what the stuck-run watchdog must sit above.
RULE_ENGINE_MAX_HARD_SECONDS = RULE_ENGINE_MAX_SOFT_SECONDS + LIMIT_STEP_SECONDS


def rule_engine_limits(document_count: int) -> tuple[int, int]:
    """``(soft, hard)`` seconds for a file with ``document_count`` documents.

    One function so the enqueue path and the stuck-run watchdog cannot disagree about how long a run
    is allowed to take — a watchdog that fails a run its own task was still legitimately working on
    is a worse failure than the one this ticket is about.
    """
    budget = document_count * MEASURED_SECONDS_PER_DOCUMENT * LIMIT_HEADROOM
    soft = int(min(max(budget, RULE_ENGINE_MIN_SOFT_SECONDS), RULE_ENGINE_MAX_SOFT_SECONDS))
    return soft, soft + LIMIT_STEP_SECONDS
