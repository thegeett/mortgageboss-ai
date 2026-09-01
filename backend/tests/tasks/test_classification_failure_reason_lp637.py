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
    INFRA_OVERSIZED,
    INFRA_RATE_LIMITED,
    is_rerunnable_infra,
)
from app.api.documents import _TOO_LARGE_MARKER, _would_benefit
from app.models.document import Document, DocumentStatus


def _document(*, error: str | None, status: DocumentStatus = DocumentStatus.NEEDS_REVIEW):
    return Document(
        loan_file_id=None,
        document_type=None,
        status=status,
        processing_error=error,
    )


def test_an_oversized_file_is_not_re_queued_by_bulk() -> None:
    """THE FILE IS WHAT IT IS. Re-reading spends a classification call to reach the same refusal,
    and without this LF-ZE9N's last document would be re-queued on every bulk press forever —
    always failing, always still uncategorized."""
    assert not is_rerunnable_infra(INFRA_OVERSIZED)  # the premise, not an assumption
    too_big = _document(
        error=(
            "This file is too large for the AI to read. Re-reading won't help — split it into "
            "smaller files or upload a lower-resolution scan."
        )
    )

    assert _would_benefit(too_big) is False


def test_a_transient_failure_stays_eligible() -> None:
    """The regression that would matter more: a throttle or a dropped connection is precisely what
    re-reading is FOR. Excluding those would strand the common case to fix the rare one."""
    for kind in (INFRA_RATE_LIMITED, INFRA_CONNECTION):
        assert is_rerunnable_infra(kind)
        flaky = _document(error=f"Couldn't read this document ({kind}) — try re-reading it.")
        assert _would_benefit(flaky) is True, kind


def test_a_document_with_no_error_is_unaffected() -> None:
    assert _would_benefit(_document(error=None)) is True


def test_the_marker_the_api_matches_is_the_one_the_pipeline_writes() -> None:
    """THE TWO-DEFINITIONS GUARD. The API decides eligibility by matching a phrase the pipeline
    writes. That is a weak coupling on purpose — the exact signal would be a persisted
    `infra_failure` column, which is a migration — but weak is not the same as unpinned: reword the
    sentence in `document_processing.py` and this fails rather than the skip silently ceasing to
    work.
    """
    import inspect

    from app.tasks import document_processing

    source = inspect.getsource(document_processing)
    assert _TOO_LARGE_MARKER in source, (
        "the pipeline no longer writes the phrase the bulk filter matches on — they have drifted"
    )
