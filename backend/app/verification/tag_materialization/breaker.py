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

**Terminal, not retried** — and the first cut of this module had that backwards. The reasoning that
looked right was "an outage may not recur, so retry it"; three counts say otherwise. ``started_at``
is stamped once at run creation and never per attempt, so a retry runs against a watchdog bound that
has been ticking since the first attempt — long enough and the watchdog fails a run whose retry is
still working, while its findings commit anyway. ``TagCaches`` is rebuilt per invocation, so a retry
re-pays for every call the first attempt already made. And the backoff window is about 35 seconds
across ``MAX_RETRIES``, which is not a length of time any outage worth tripping this breaker is over
in.

So it joins ``SoftTimeLimitExceeded`` in ``terminal_on``. The benefit the breaker delivers is
unchanged by that: the slot is released in under a minute instead of being ground away for the file's
whole budget, and the run is visibly FAILED and re-runnable once the backend is back. Releasing the
slot was always the win; the automatic retry was not.

**Nearly everything counts; one thing resets.** Only a PAYLOAD rejection
(:data:`~app.ai.client.INFRA_OVERSIZED`) clears the counter — that is the backend answering about
THIS request's shape, and one oversized document says nothing about the next call.

The first cut gated on :data:`~app.ai.client.RERUNNABLE_INFRA_KINDS` instead, on the reasoning that a
backend which answers is not the one this breaker looks for. That reasoning does not survive a 403:
``infra_failure_kind`` returns ``INFRA_FAILED`` for auth, permission and AccessDenied, which is
outside that set — so an expired credential mid-pass RESET the counter on every single call and was
the one outage shape that could never trip this breaker, while being the least recoverable of them
all. ADR-387 records out-of-band credentials as a live concern in this environment, so that was the
likely route, not a hypothetical one.

Content outcomes never reach here to begin with: a malformed response, an off-vocabulary value or a
truncation is handled by the fail-closed path and does not raise. Only an ``AIClientError`` does. The
residual risk is narrow and worth stating — a content-shaped failure raised as a causeless
``AIClientError`` would count, and five in a row would end the pass. That is a visible, re-runnable
failure rather than a silent one, which is the right side to err on.
"""

from __future__ import annotations

import structlog

from app.ai.client import INFRA_OVERSIZED, AIClientError, infra_failure_kind

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

        Only a PAYLOAD rejection resets the counter. That is evidence the backend answered and
        refused this particular request's shape — one oversized document is not an outage, and the
        next call may well land.

        EVERYTHING ELSE COUNTS, including ``INFRA_FAILED`` (LP-635 review). It used to reset, on the
        reasoning that "a backend that answers is not the one this breaker looks for" — but
        ``INFRA_FAILED`` is what `infra_failure_kind` returns for auth, permission and AccessDenied,
        and a 403 does answer while being the LEAST recoverable failure there is. ADR-387 records
        out-of-band credentials as a live concern in this environment, so an expired credential
        mid-pass is a realistic outage — and it was the one shape that could never trip this
        breaker, resetting the counter on every single call while the pass ground through the whole
        budget producing an all-``couldn't check`` run. That is precisely what this module exists to
        prevent, reachable by the most likely route.

        Only an ``AIClientError`` reaches here, so the residual risk is narrow: if some content-shaped
        failure is ever raised as a causeless ``AIClientError``, five of them in a row would end the
        pass. That is a visible, re-runnable failure rather than a silent one, which is the right
        side to err on.
        """
        if infra_failure_kind(err) == INFRA_OVERSIZED:
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
                f"The AI backend failed {self._consecutive} calls in a row. Stopping this "
                "pass rather than spending the rest of the run on calls that cannot land — "
                "re-run the verification once the backend is reachable."
            )


__all__ = [
    "CONSECUTIVE_INFRA_FAILURES_TO_TRIP",
    "AiBackendUnavailable",
    "AiInfraBreaker",
]
