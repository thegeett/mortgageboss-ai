"""LP-637 — two workers cannot process the same document at once.

THE RACE THE STATUS GUARDS COULD NOT CLOSE. The API refuses a reprocess for a document already in
flight, but a status only moves when a WORKER starts: two clicks seconds apart both read the row as
it was before either was picked up, and both enqueue. Bulk multiplies that by the batch size.

Two overlapping `_process_document` runs both write a current extraction, and
``UNIQUE (document_id) WHERE is_current`` admits one — the loser absorbs the IntegrityError into
FAILED, so the document reads FAILED while carrying the winner's perfectly good extraction. Since
findings superseding moved ahead of classification, the second run can also supersede the first
run's fresh findings.

Closed with a conditional UPDATE, so the DATABASE picks the winner and a duplicate task finds
nothing to do.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.document import _PIPELINE_IN_FLIGHT, Document, DocumentStatus
from app.tasks.document_processing import _claim_for_processing
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def _document(db: AsyncSession, *, status: DocumentStatus) -> Document:
    company = await factories.make_company(db, slug=f"acme-{uuid4().hex[:6]}")
    loan_file = await factories.make_loan_file(db, company=company)
    document = await factories.make_document(db, loan_file=loan_file, company=company)
    document.status = status
    await db.flush()
    return document


async def test_the_first_claim_wins_and_the_second_finds_nothing_to_do(
    db_session: AsyncSession,
) -> None:
    """The whole point. Two tasks, one document, one winner."""
    document = await _document(db_session, status=DocumentStatus.COMPLETED)

    assert await _claim_for_processing(db_session, document.id) is True
    assert await _claim_for_processing(db_session, document.id) is False


async def test_a_claim_leaves_the_document_visibly_in_flight(db_session: AsyncSession) -> None:
    """The claim only excludes a second worker once it is VISIBLE as in-flight — that is what the
    second claim reads. A claim that did not move the status would exclude nobody."""
    document = await _document(db_session, status=DocumentStatus.COMPLETED)

    await _claim_for_processing(db_session, document.id)

    await db_session.refresh(document)
    assert document.status is DocumentStatus.CLASSIFYING
    assert document.status in _PIPELINE_IN_FLIGHT


async def test_every_in_flight_status_is_unclaimable(db_session: AsyncSession) -> None:
    """A property over the SET rather than an example, because the set is shared with the API's
    refusal and CLASSIFIED was already once left out of it — the status a Tier 3 document holds for
    its entire free-extraction call, i.e. the longest window on the cohort this feature exists for.
    """
    for status in _PIPELINE_IN_FLIGHT:
        document = await _document(db_session, status=status)
        assert await _claim_for_processing(db_session, document.id) is False, status


async def test_every_terminal_status_is_claimable(db_session: AsyncSession) -> None:
    """The other direction, and the regression that would matter more: a claim that refused a
    terminal status would make reprocessing impossible for exactly the documents it is for —
    NEEDS_REVIEW and FAILED are LF-ZE9N's ten."""
    for status in (
        DocumentStatus.PENDING,
        DocumentStatus.COMPLETED,
        DocumentStatus.NEEDS_REVIEW,
        DocumentStatus.FAILED,
    ):
        document = await _document(db_session, status=status)
        assert await _claim_for_processing(db_session, document.id) is True, status


async def test_a_missing_document_is_not_claimable(db_session: AsyncSession) -> None:
    """Nothing to claim, and the caller's own missing-document branch has already run."""
    assert await _claim_for_processing(db_session, uuid4()) is False


async def test_the_second_pipeline_run_does_no_work_at_all(db_session: AsyncSession) -> None:
    """AT THE LAYER THE DEFECT WAS SEEN. Everything above tests the claim helper; none of it proves
    the pipeline consults it.

    The second run must not read storage, not classify, and not supersede the first run's findings —
    it must return having touched nothing. Asserted by watching the storage read, which is the first
    thing `_process_document` does after claiming: if it happens, the claim was not honoured.
    """
    from unittest.mock import AsyncMock, patch

    from app.tasks import document_processing as dp

    document = await _document(db_session, status=DocumentStatus.COMPLETED)
    await db_session.commit()

    # The document is claimed, as it would be by a worker that got there first.
    assert await _claim_for_processing(db_session, document.id) is True

    reads = AsyncMock()
    superseded = AsyncMock(return_value=0)
    with (
        patch.object(dp, "get_storage_backend", return_value=AsyncMock(read=reads)),
        patch.object(dp, "supersede_open_findings", superseded),
    ):
        await dp._process_document(db_session, str(document.id))

    reads.assert_not_awaited()
    superseded.assert_not_awaited()
