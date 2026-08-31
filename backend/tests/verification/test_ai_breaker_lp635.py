"""LP-635 — a pass whose AI backend has gone away stops instead of grinding.

LF-ZE9N's first verification did not fail during the Bedrock outage of 2026-08-30; it ground through
it for fifteen minutes and was killed by the Celery soft limit, which is how a transport outage
reached the logs dressed as a timeout.

The two halves that matter are pulled apart deliberately here: a SINGLE failure must still be
tolerated (that is the fail-closed behaviour the rest of the engine is built on), and a RUN of
infrastructure failures must stop the pass. A test suite that only asserted the second could be
satisfied by a breaker that trips on the first flaky call, which would be a much worse bug than the
one being fixed.
"""

from __future__ import annotations

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError
from app.ai.client import AIClientError
from app.verification.tag_materialization.breaker import (
    CONSECUTIVE_INFRA_FAILURES_TO_TRIP,
    AiBackendUnavailable,
    AiInfraBreaker,
)


def _connection_error() -> AIClientError:
    """The shape LF-ZE9N actually saw: `APIConnectionError` at ~1ms — never left the host."""
    err = AIClientError("transport failed")
    err.__cause__ = APIConnectionError(request=httpx.Request("POST", "https://bedrock.invalid"))
    return err


def _content_error() -> AIClientError:
    """A 400 — the backend ANSWERED and refused the request's shape. Not an outage."""
    response = httpx.Response(
        400, request=httpx.Request("POST", "https://bedrock.invalid"), json={"message": "bad"}
    )
    err = AIClientError("bad request")
    err.__cause__ = APIStatusError("bad", response=response, body=None)
    return err


def test_a_single_infrastructure_failure_does_not_trip() -> None:
    """THE REGRESSION THIS MUST NOT CAUSE. One flaky call is what the per-batch fail-closed path
    handles well, and a pass that dies on it would be far worse than one that grinds."""
    breaker = AiInfraBreaker()
    breaker.record_failure(_connection_error())
    assert breaker.consecutive == 1


def test_failures_below_the_threshold_do_not_trip() -> None:
    breaker = AiInfraBreaker()
    for _ in range(CONSECUTIVE_INFRA_FAILURES_TO_TRIP - 1):
        breaker.record_failure(_connection_error())
    assert breaker.consecutive == CONSECUTIVE_INFRA_FAILURES_TO_TRIP - 1


def test_a_run_of_infrastructure_failures_stops_the_pass() -> None:
    """The outage case. Nothing between these calls succeeded, so the next one will not either."""
    breaker = AiInfraBreaker()
    with pytest.raises(AiBackendUnavailable):
        for _ in range(CONSECUTIVE_INFRA_FAILURES_TO_TRIP):
            breaker.record_failure(_connection_error())


def test_a_success_resets_the_count() -> None:
    """CONSECUTIVE, not cumulative. A pass that fails one call in ten is having a bad day and must
    still finish — counting those toward a total would fail long files for being long."""
    breaker = AiInfraBreaker()
    for _ in range(CONSECUTIVE_INFRA_FAILURES_TO_TRIP - 1):
        breaker.record_failure(_connection_error())
    breaker.record_success()
    assert breaker.consecutive == 0
    # And the budget is genuinely restored, not merely reported as zero.
    for _ in range(CONSECUTIVE_INFRA_FAILURES_TO_TRIP - 1):
        breaker.record_failure(_connection_error())


def test_a_content_failure_does_not_count_and_resets() -> None:
    """A 400 means the backend ANSWERED. Counting content failures here would fail runs on hard
    files that today complete with honest `couldn't check` findings — the one regression this module
    must not cause."""
    breaker = AiInfraBreaker()
    for _ in range(CONSECUTIVE_INFRA_FAILURES_TO_TRIP - 1):
        breaker.record_failure(_connection_error())
    breaker.record_failure(_content_error())
    assert breaker.consecutive == 0


def test_content_failures_alone_never_trip() -> None:
    """Even a great many of them. A file the model keeps refusing is a content problem, and the
    fail-closed path is the right answer to it."""
    breaker = AiInfraBreaker()
    for _ in range(CONSECUTIVE_INFRA_FAILURES_TO_TRIP * 4):
        breaker.record_failure(_content_error())
    assert breaker.consecutive == 0


def test_the_error_says_what_happened_without_naming_the_file() -> None:
    """It lands in task logs and a run's `error_detail`, both read by people who should not need a
    borrower's data to learn that Bedrock was down."""
    breaker = AiInfraBreaker(threshold=2)
    with pytest.raises(AiBackendUnavailable) as caught:
        breaker.record_failure(_connection_error())
        breaker.record_failure(_connection_error())
    message = str(caught.value)
    assert "2 calls in a row" in message
    # It says what to DO. This string reaches a run's `error_detail`, which a processor reads, and an
    # earlier version told them it would be "retried" — which stopped being true the moment the
    # breaker became terminal. Prose asserting behaviour is the one claim nothing type-checks.
    assert "re-run" in message
    assert "retried" not in message


# --------------------------------------------------------------------------- #
# At the layer the defect was seen: the pass, and the backstop above it
# --------------------------------------------------------------------------- #
async def test_the_group_pass_stops_once_the_backend_is_gone() -> None:
    """Everything above is a unit test of a counter. This is the behaviour that was actually broken:
    the pass kept issuing calls into a backend that was not answering.

    The reasoner here fails the way the outage did, and the assertion is that the pass RAISES rather
    than returning a full set of unknown-with-reason tags — the "successful" outcome that cost
    fifteen minutes and told nobody anything.
    """
    from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations
    from tests.verification.tag_materialization.test_producers import _doc, _snapshot

    calls = 0

    async def always_unreachable(_context: str) -> object:
        nonlocal calls
        calls += 1
        raise _connection_error()

    group = load_ai_groups()["id_address"]
    # Enough distinct documents to fill several BATCHES. The unit is the call, not the document —
    # the pass batches subjects, so 40 documents is three calls, not forty. Written down because it
    # is also the answer to "how long does a real outage take to trip": five batches, not five
    # documents.
    docs = [_doc(f"d{i}", fields={"address": f"{i} Main St"}) for i in range(40)]
    snap = _snapshot(docs=docs)

    from app.verification.tag_materialization.ai import produce_ai_group_tags

    # Threshold 2 so the trip lands inside this group's batches rather than depending on the batch
    # size staying where it is today.
    with pytest.raises(AiBackendUnavailable):
        await produce_ai_group_tags(
            snap,
            group,
            {t: load_declarations()[t].allowed_values for t in group.tag_ids},
            reasoner=always_unreachable,
            breaker=AiInfraBreaker(threshold=2),
        )
    # It stopped EARLY. Three batches were available and it made two — the third was never issued,
    # which is the whole point.
    assert calls == 2


async def test_without_a_breaker_the_pass_still_degrades_as_before() -> None:
    """The unchanged path, pinned. Every existing caller passes no breaker — the eval, calibration
    and worksheet harnesses among them — and must keep the fail-closed behaviour they rely on."""
    from app.verification.tag_materialization.ai import produce_ai_group_tags
    from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations
    from tests.verification.tag_materialization.test_producers import _doc, _snapshot

    async def always_unreachable(_context: str) -> object:
        raise _connection_error()

    group = load_ai_groups()["id_address"]
    snap = _snapshot(docs=[_doc("d1", fields={"address": "1 Main St"})])
    out = await produce_ai_group_tags(
        snap,
        group,
        {t: load_declarations()[t].allowed_values for t in group.tag_ids},
        reasoner=always_unreachable,
    )
    assert out["d1"]["id.address_normalized"].value == "unknown"


async def test_the_stage_backstop_lets_this_one_through() -> None:
    """The backstop degrades a wholesale stage failure instead of killing the run, and that trade is
    right for an unexpected error and wrong for a known outage: degrading would turn a retryable
    outage into a permanently thin result nothing would revisit.

    Paired with its own control below, because a test that only asserts the re-raise would still pass
    if the backstop had been removed entirely.
    """
    from app.services.verification_run import Degradation, _run_stage

    async def outage(_snapshot: object) -> object:
        raise AiBackendUnavailable("backend gone")

    degradations: list[Degradation] = []
    with pytest.raises(AiBackendUnavailable):
        await _run_stage("materialization", outage, object(), degradations)  # type: ignore[arg-type]
    assert degradations == [], "an outage must not be recorded as a mere degradation"


async def test_the_stage_backstop_still_catches_everything_else() -> None:
    """The positive control for the test above."""
    from app.services.verification_run import Degradation, _run_stage

    sentinel = object()

    async def boom(_snapshot: object) -> object:
        raise ValueError("something unexpected")

    degradations: list[Degradation] = []
    result = await _run_stage("materialization", boom, sentinel, degradations)  # type: ignore[arg-type]
    assert result is sentinel
    assert len(degradations) == 1


# --------------------------------------------------------------------------- #
# LP-635 REVIEW — Stage B was outside the breaker
# --------------------------------------------------------------------------- #


def test_stage_b_accepts_a_breaker() -> None:
    """Stage B judges once per money-in deposit, so it is the stage with the MOST calls — and it
    was the one left out.

    An outage beginning in Stage B was invisible to the counter, so the pass ground through the
    whole of it: the exact behaviour the breaker exists to stop, still reachable by the commonest
    route. Asserted on the signature so the parameter cannot be quietly dropped again.
    """
    import inspect

    from app.services.tag_correlation import produce_stage_b_sourcing_tags

    assert "breaker" in inspect.signature(produce_stage_b_sourcing_tags).parameters


def test_every_ai_stage_in_the_pass_is_wired_to_the_breaker() -> None:
    """The property, rather than one stage at a time.

    `stage_a` and `materialization` were wired and `stage_b` was not, which no test noticed because
    each stage had its own. This reads the call site and asserts that every stage taking a
    `reasoner` also takes the `breaker` — so adding a fifth AI stage without wiring it fails here.

    `recurrence` is deliberately absent: it is pure and synchronous (`_recurrence_stage`), makes no
    calls, and has nothing to report.
    """
    import re
    from pathlib import Path

    source = Path("app/services/verification_run.py").read_text()
    body = source[source.index("if produce_tags:") : source.index("# 4.")]

    reasoner_stages = re.findall(r"reasoner=reasoners\.(\w+)", body)
    assert reasoner_stages, "no AI stages found — the anchor for this test has moved"

    for call in re.findall(r"lambda s: \w+\([^)]*\)", body, re.S):
        if "reasoner=reasoners." in call:
            assert "breaker=ai_breaker" in call, (
                f"an AI stage runs without the breaker, so an outage during it is invisible:\n{call}"
            )


def test_an_auth_failure_trips_the_breaker_rather_than_resetting_it() -> None:
    """LP-635 REVIEW — the outage shape that could NEVER trip this breaker.

    `infra_failure_kind` returns INFRA_FAILED for auth, permission and AccessDenied, which is not in
    RERUNNABLE_INFRA_KINDS — so the old rule reset the counter on every single call. An expired
    credential or revoked model access mid-pass would grind through the entire budget (now up to
    3600s, not 900) producing an all-`couldn't check` run: exactly what this module exists to
    prevent, by the most likely route. ADR-387 records out-of-band credentials as a live concern in
    this environment.
    """
    import httpx
    from anthropic import AuthenticationError
    from app.ai.client import AIClientError

    breaker = AiInfraBreaker(threshold=3)
    request = httpx.Request("POST", "https://x/y")
    response = httpx.Response(401, request=request, json={"message": "expired"})

    def _auth_error() -> AIClientError:
        err = AIClientError("auth")
        err.__cause__ = AuthenticationError("no", response=response, body=None)
        return err

    with pytest.raises(AiBackendUnavailable):
        for _ in range(3):
            breaker.record_failure(_auth_error())


def test_an_oversized_payload_still_resets_the_counter() -> None:
    """The boundary. One document too large for the request is not an outage — the backend answered
    and refused that call's shape, and the next call may land. Resetting is right there, and it is
    the only kind that should."""
    import httpx
    from anthropic import BadRequestError
    from app.ai.client import AIClientError

    breaker = AiInfraBreaker(threshold=2)
    request = httpx.Request("POST", "https://x/y")

    connection = AIClientError("conn")
    connection.__cause__ = httpx.ConnectError("boom", request=request)
    breaker.record_failure(connection)
    assert breaker.consecutive == 1

    oversized = AIClientError("too big")
    oversized.__cause__ = BadRequestError(
        "too big", response=httpx.Response(400, request=request, json={}), body=None
    )
    breaker.record_failure(oversized)

    assert breaker.consecutive == 0, "an oversized payload must not count toward an outage"
