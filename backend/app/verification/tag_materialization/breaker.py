"""Stop a rule-engine pass whose AI backend has gone away (LP-635).

THE RUN THIS EXISTS FOR. On 2026-08-30 staging could not reach Bedrock for about fifteen minutes.
LF-ZE9N's first verification did not fail during that window — it *ground through it*. Every AI batch
raised ``APIClientError`` at ``latency_ms=1`` (a request that fails in a millisecond never left the
host), each one burning its full retry budget, and
:func:`~app.verification.tag_materialization.ai.produce_ai_group_tags` did what it is supposed to do
with a single failure: logged it, marked the batch ``couldn't check``, and moved to the next one.

That per-batch tolerance is right and stays. What was missing is anyone asking whether the NEXT call
could possibly succeed. So the pass spent fifteen minutes issuing calls that could not land, held a
worker slot for all of it, and was finally killed by the Celery soft limit — which is what put a
transport outage in the logs wearing a timeout's clothes, and sent the first diagnosis after file
size when the cause was the network.

**What the run would have produced had it finished is the other half of the argument.** With every
call failing, every AI-derived tag resolves to ``unknown`` with a failure reason. The findings built
on those tags are all ``couldn't check``. That is not a degraded answer, it is an expensive way to
learn nothing — and it is indistinguishable, on the finished screen, from a file that genuinely lacks
the documents to check.

So: a run of consecutive INFRASTRUCTURE failures means stop. Not "this batch failed" — that stays
tolerated — but "the backend is not answering", which no amount of continuing will fix.

**Deliberately transient, not terminal.** Tripping raises, the exception leaves the pass, and
``retry_or_terminal`` in :mod:`app.tasks.verification_rules` retries it with backoff, because a
backend outage is the definition of a condition that may not recur. The slot is released in seconds
instead of held for fifteen minutes, and the retry happens later, when it might work. Before this,
the failure was slow AND unretryable: the soft limit is terminal by design (retrying a run that ran
out of clock just runs out of clock again), so an outage borrowed that terminality by arriving
dressed as a timeout.

**Only infrastructure counts.** A malformed response, an off-vocabulary value, a truncation — those
are content outcomes, they are what the fail-closed path already handles well, and a file that
produces many of them is a hard file rather than a broken backend. Counting them here would fail runs
that today complete with honest ``couldn't check`` findings, which is the one regression this module
must not cause. The set is :data:`~app.ai.client.RERUNNABLE_INFRA_KINDS` — routed off the SET, never
off one label, for the reason that module documents.
"""

from __future__ import annotations

import structlog

from app.ai.client import AIClientError, infra_failure_kind, is_rerunnable_infra

logger = structlog.get_logger(__name__)

#: Consecutive infrastructure failures that mean the backend is gone rather than flaky.
#:
#: Each failure here is already a call that exhausted ``settings.ai_max_retries`` attempts with
#: backoff, so five of them in a row is fifteen-plus failed round trips with no success between them.
#: Set from what the outage looked like rather than from taste: LF-ZE9N's window shows an unbroken
#: run of dozens, and a single flaky call — the case that must keep working — never reaches two.
#:
#: The counter resets on ANY success, so this is "five in a row", not "five in the run". A pass that
#: fails one call in ten is having a bad day and still finishes; a pass that cannot land five calls
#: back to back is not going to land the sixth.
CONSECUTIVE_INFRA_FAILURES_TO_TRIP = 5


class AiBackendUnavailable(RuntimeError):
    """Raised when consecutive infrastructure failures show the AI backend is unreachable.

    Carries no loan-file or borrower detail — it is raised deep in the materialization pass and ends
    up in task logs and a run's ``error_detail``, both of which are read by people who should not
    need to see a borrower's data to understand that Bedrock was down.
    """


class AiInfraBreaker:
    """Counts consecutive AI infrastructure failures across ONE pass.

    Not thread-safe and does not need to be: a pass materializes its groups sequentially in one
    event-loop task, which is the same reason its runtime is the sum of its AI calls and why this
    ticket exists at all.
    """

    def __init__(self, *, threshold: int = CONSECUTIVE_INFRA_FAILURES_TO_TRIP) -> None:
        self._threshold = threshold
        self._consecutive = 0
        self.infra_failures = 0  #: total infra failures seen, for the log line on trip

    @property
    def consecutive(self) -> int:
        return self._consecutive

    def record_success(self) -> None:
        """A call landed, so whatever was failing is not failing now."""
        self._consecutive = 0

    def record_failure(self, err: AIClientError) -> None:
        """Count ``err`` if it is an infrastructure outcome, and trip once too many stack up.

        A non-infrastructure failure RESETS the counter rather than being ignored. That is
        deliberate: it is evidence the backend answered — it returned something that parsed badly, or
        refused the request's shape — and a backend that answers is not the one this breaker looks
        for.
        """
        if not is_rerunnable_infra(infra_failure_kind(err)):
            self._consecutive = 0
            return
        self._consecutive += 1
        self.infra_failures += 1
        if self._consecutive >= self._threshold:
            logger.error(
                "ai_backend_unavailable",
                consecutive=self._consecutive,
                threshold=self._threshold,
                infra_failures=self.infra_failures,
            )
            raise AiBackendUnavailable(
                f"The AI backend failed {self._consecutive} calls in a row "
                "(connection, server or throttle). Stopping this pass so it can be retried "
                "rather than spending the run's remaining time on calls that cannot land."
            )


__all__ = [
    "CONSECUTIVE_INFRA_FAILURES_TO_TRIP",
    "AiBackendUnavailable",
    "AiInfraBreaker",
]
