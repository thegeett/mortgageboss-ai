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

from datetime import timedelta
from uuid import uuid4

from app.models.base import utcnow
from app.models.document import (
    PIPELINE_IN_FLIGHT_STATUSES,
    PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS,
    Document,
    DocumentStatus,
)
from app.tasks.document_processing import DOCUMENT_HARD_LIMIT_SECONDS, _claim_for_processing
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
    assert document.status in PIPELINE_IN_FLIGHT_STATUSES


async def test_every_in_flight_status_is_unclaimable(db_session: AsyncSession) -> None:
    """A property over the SET rather than an example, because the set is shared with the API's
    refusal and CLASSIFIED was already once left out of it — the status a Tier 3 document holds for
    its entire free-extraction call, i.e. the longest window on the cohort this feature exists for.
    """
    for status in PIPELINE_IN_FLIGHT_STATUSES:
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


# --------------------------------------------------------------------------- #
# LP-637 review — a claim nobody can release is a document nobody can recover
# --------------------------------------------------------------------------- #
async def test_the_threshold_is_longer_than_a_worker_can_possibly_live() -> None:
    """The whole safety argument in one line, asserted rather than described.

    A live worker cannot go longer than the SIGKILL ceiling without writing the row, because past
    it there is no worker. If someone lowers the presumed-abandoned window below that ceiling, a
    SLOW document becomes reclaimable while its worker is still running — which is the duplicate
    run this ticket exists to prevent, reintroduced through the fix for it.
    """
    margin = PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS - DOCUMENT_HARD_LIMIT_SECONDS
    assert margin >= 120, (
        f"only {margin}s between the abandoned window and the hard time limit. `updated_at` is "
        "stamped app-side by the WORKER and compared against the API host's clock — no database "
        "clock is involved — so this margin is the tolerance for cross-host skew, not just for "
        "commit latency. Too thin and a live extraction reads as abandoned, the row is overwritten "
        "to PENDING, and a second full pipeline is enqueued: the duplicate run, through its own fix."
    )


async def test_a_document_abandoned_by_a_killed_worker_can_be_claimed_again(
    db_session: AsyncSession,
) -> None:
    """THE COST OF CHOOSING THE DATABASE OVER A LOCK WITH A TIMEOUT, paid.

    The claim sets CLASSIFYING with no expiry, so a worker killed mid-run — an OOM, a deploy, or
    LP-630's nightly 22:00 shutdown of staging's services — left the document in flight forever:
    refused by the reprocess endpoint, skipped by bulk, unclaimable by any later task. No route
    back through the product at all, and worse than the state before the claim existed, where a
    hard-killed worker simply left the document as it was.
    """
    document = await _document(db_session, status=DocumentStatus.PENDING)
    await db_session.commit()

    assert await _claim_for_processing(db_session, document.id) is True  # a worker takes it
    await db_session.refresh(document)
    assert document.status is DocumentStatus.CLASSIFYING

    # ...and is killed. Nothing writes the row again.
    document.updated_at = utcnow() - timedelta(
        seconds=PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS + 60
    )
    await db_session.commit()

    assert await _claim_for_processing(db_session, document.id) is True, (
        "an abandoned document could never be picked up again"
    )


async def test_a_live_run_is_still_protected(db_session: AsyncSession) -> None:
    """The positive control. The reclaim must not give back the race it was added to close —
    a document written recently has a worker behind it and stays untouchable."""
    document = await _document(db_session, status=DocumentStatus.PENDING)
    await db_session.commit()

    assert await _claim_for_processing(db_session, document.id) is True
    assert await _claim_for_processing(db_session, document.id) is False, (
        "the staleness escape hatch swallowed the claim itself"
    )


async def test_there_is_no_way_to_take_a_live_claim(db_session: AsyncSession) -> None:
    """A draft of this fix gave retries an unconditional reclaim, and it was a mistake worth
    recording rather than quietly deleting.

    The reasoning was that a retry of the task holding the claim would find its own status set and
    give up. But a retry can only ever be scheduled by a failure BEFORE the claim is taken —
    everything after it is inside the pipeline's `try`, which absorbs every exception into a
    terminal status, and the one it re-raises is in `terminal_on` and never retried. So a retrying
    task has never owned anything. What the escape hatch actually did was let task A, having failed
    in `task_session()` before claiming, steal document X from task B, which had legitimately won
    it and was mid-extraction — both then writing a current extraction, the partial unique index
    admitting one, and the loser landing in FAILED holding the winner's work. The ticket's own bug,
    through the fix for it.

    So there is no parameter to test. The assertion is that no call shape takes a live claim.
    """
    document = await _document(db_session, status=DocumentStatus.PENDING)
    await db_session.commit()

    assert await _claim_for_processing(db_session, document.id) is True
    assert await _claim_for_processing(db_session, document.id) is False
    assert (
        await _claim_for_processing(db_session, document.id, into=DocumentStatus.EXTRACTING)
        is False
    ), "the extraction-only path could take a claim the full pipeline was holding"


async def test_claiming_an_abandoned_document_refreshes_its_clock(
    db_session: AsyncSession,
) -> None:
    """THE CASE THE STALENESS RULE COULD HAVE MISSED, and it would have given back the whole race.

    The reclaim is "in flight but not written recently". If the claim's UPDATE did not itself
    refresh ``updated_at``, then taking over an abandoned document would leave the row still
    looking abandoned — and the very next worker would take it too, and the next. The reclaim would
    protect nothing precisely for the documents it exists to rescue.

    `TimestampMixin` sets ``onupdate=utcnow``; this pins that it applies to the Core UPDATE the
    claim issues, not only to ORM flushes.
    """
    document = await _document(db_session, status=DocumentStatus.CLASSIFYING)
    document.updated_at = utcnow() - timedelta(
        seconds=PIPELINE_PRESUMED_ABANDONED_AFTER_SECONDS + 60
    )
    await db_session.commit()

    assert await _claim_for_processing(db_session, document.id) is True  # rescued
    assert await _claim_for_processing(db_session, document.id) is False, (
        "the rescuing worker's own claim still looked abandoned — every worker would take it"
    )


async def test_the_extraction_only_path_takes_the_claim_too(db_session: AsyncSession) -> None:
    """A claim only exclusive against itself is not exclusive.

    The LP-44 type override enqueues `reprocess_document`, which writes a current extraction and a
    terminal status of its own and never took the claim. Run alongside a claimed
    `_process_document` it produced the very collision the claim exists to stop — and its terminal
    write RELEASED the other run's claim mid-flight, letting a third task in behind it.
    """
    document = await _document(db_session, status=DocumentStatus.COMPLETED)
    await db_session.commit()

    assert (
        await _claim_for_processing(db_session, document.id, into=DocumentStatus.EXTRACTING) is True
    )
    await db_session.refresh(document)
    assert document.status is DocumentStatus.EXTRACTING, "claimed into the wrong status"

    assert await _claim_for_processing(db_session, document.id) is False, (
        "the full pipeline could take a claim the extraction-only path was holding"
    )
