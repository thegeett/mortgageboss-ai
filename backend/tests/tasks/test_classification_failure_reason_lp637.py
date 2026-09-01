"""LP-637 — a classification that fails on infrastructure says so ON THE DOCUMENT.

FOUND ON LF-ZE9N, after the reprocess feature shipped. Nine of its ten unidentified documents were
recovered; the tenth stayed "Processing / uncategorized" with nothing explaining why. The worker
knew exactly why — 15 pages encoding to 33 MB against a 23 MB budget, refused by the LP-636 payload
cap — and wrote that reason to the log and to the activity feed, and never to `processing_error`,
which is the only place a processor looks.

The extraction branches have always written that column. Classification never did, and the reprocess
endpoint now CLEARS it, so any older text was gone too.
"""

from __future__ import annotations

from app.ai.client import (
    INFRA_CONNECTION,
    INFRA_FAILED,
    INFRA_OVERSIZED,
    INFRA_RATE_LIMITED,
    INFRA_SERVER,
    is_rerunnable_infra,
)
from app.api.documents import _refused_for_size, _would_benefit
from app.models.document import Document, DocumentStatus
from app.tasks.document_processing import (
    PAYLOAD_TOO_LARGE_MARKER,
    PAYLOAD_TOO_LARGE_MESSAGE,
    _classification_failure_message,
)


def _document(*, error: str | None, status: DocumentStatus = DocumentStatus.NEEDS_REVIEW):
    return Document(
        loan_file_id=None,
        document_type=None,
        status=status,
        processing_error=error,
    )


def test_a_file_that_cannot_be_sent_is_recognised_as_such() -> None:
    """THE FILE IS WHAT IT IS. Re-reading spends a classification call to reach the same refusal,
    and without this LF-ZE9N's last document would be re-queued on every bulk press forever —
    always failing, always still uncategorized.

    The exclusion itself lives in the bulk endpoint rather than in `_would_benefit`, so the skip can
    be REPORTED under its own reason — see the endpoint tests. What is asserted here is the signal
    the endpoint reads.
    """
    too_big = _document(
        error=_classification_failure_message(INFRA_OVERSIZED, payload_over_budget=True)
    )

    assert _refused_for_size(too_big) is True


def test_a_transient_failure_stays_eligible() -> None:
    """The regression that would matter more: a throttle or a dropped connection is precisely what
    re-reading is FOR. Excluding those would strand the common case to fix the rare one."""
    for kind in (INFRA_RATE_LIMITED, INFRA_CONNECTION):
        assert is_rerunnable_infra(kind)
        flaky = _document(error=_classification_failure_message(kind, payload_over_budget=False))
        assert _refused_for_size(flaky) is False, kind
        assert _would_benefit(flaky) is True, kind


def test_a_document_with_no_error_is_unaffected() -> None:
    assert _would_benefit(_document(error=None)) is True


def test_the_reader_uses_the_writer_s_own_marker() -> None:
    """THE TWO-DEFINITIONS GUARD, made structural rather than pinned.

    The API decides eligibility by matching a phrase the pipeline writes — a weak coupling on
    purpose, since the exact signal would be a persisted `infra_failure` column and that is a
    migration this filter does not earn. The first version had the reader holding its OWN copy of
    the phrase, with a test grepping the pipeline's source to keep them equal.

    That is a test catching drift where a structure can prevent it. The marker now lives with the
    writer, the message is built around it, and the API imports it — so rewording the sentence
    cannot silently disable the filter, and there is no second copy to fall out of step.
    """
    from app.api import documents as documents_api
    from app.tasks import document_processing

    assert documents_api.PAYLOAD_TOO_LARGE_MARKER is document_processing.PAYLOAD_TOO_LARGE_MARKER, (
        "the API has forked its own copy of the marker — the coupling is a promise again"
    )
    assert document_processing.PAYLOAD_TOO_LARGE_MARKER in PAYLOAD_TOO_LARGE_MESSAGE, (
        "the message no longer contains the marker the filter matches on"
    )


def test_an_auth_failure_is_not_blamed_on_the_file_size() -> None:
    """THE THIRD APPEARANCE OF THE SAME OUTAGE, and the reason to name it every time.

    The two voices were keyed on `is_rerunnable_infra`, whose set is
    {rate_limited, connection, server_error}. `INFRA_FAILED` — what `infra_failure_kind` returns for
    auth, permission and AccessDenied — is not in it, so an expired credential fell into the else
    branch and told a processor:

        "This file is too large for the AI to read. Re-reading won't help — split it into smaller
         files or upload a lower-resolution scan."

    False, and expensively so: the processor goes and splits a perfectly readable file. Worse, the
    same sentence is what `_refused_for_size` matches, so the document is dropped from the bulk
    default FOREVER — while re-reading is precisely what fixes it, the moment the credential is.

    ADR-387 records out-of-band credentials as a live concern in this environment, so this is the
    likely route rather than a hypothetical one. It is the same shape that made an expired
    credential the one outage the LP-635 breaker could never trip.
    """
    assert not is_rerunnable_infra(INFRA_FAILED)  # the premise that made the branch wrong

    # Built by the PRODUCTION function, not typed out here. A first draft of this test wrote the
    # expected sentence by hand and passed against the very bug it describes — it was asserting
    # about its own string.
    stranded = _document(
        error=_classification_failure_message(INFRA_FAILED, payload_over_budget=False)
    )

    assert PAYLOAD_TOO_LARGE_MARKER not in (stranded.processing_error or ""), (
        "an auth failure was described to the processor as an oversized file"
    )
    assert _refused_for_size(stranded) is False, (
        "an auth failure was permanently excluded from bulk reprocess, which is what fixes it"
    )


def test_the_permanent_voice_follows_the_measurement_not_the_error_name() -> None:
    """Stated as a property over the whole set, in BOTH directions, because two versions of this
    branch shipped keyed on a proxy and each proxy was wrong for a different kind.

    `is_rerunnable_infra` excludes INFRA_FAILED, so auth failures were told their file was too
    large. Then `infra_failure == INFRA_OVERSIZED` — but `infra_failure_kind` returns that for every
    non-throttle HTTP 400, so a corrupt PDF or a misconfigured model id got the same sentence and
    the same permanent bulk exclusion. Only the measurement earns it.
    """
    kinds = (INFRA_RATE_LIMITED, INFRA_CONNECTION, INFRA_SERVER, INFRA_FAILED, INFRA_OVERSIZED)
    for kind in kinds:
        for over_budget in (False, True):
            message = _classification_failure_message(kind, payload_over_budget=over_budget)
            permanent = PAYLOAD_TOO_LARGE_MARKER in message
            assert permanent is over_budget, (
                f"{kind} / over_budget={over_budget}: says re-reading won't help = {permanent}"
            )
            assert _refused_for_size(_document(error=message)) is over_budget, (
                f"{kind} / over_budget={over_budget}: the bulk exclusion disagrees with the copy"
            )
