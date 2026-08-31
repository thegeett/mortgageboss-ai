"""LP-635 review — the watchdog asks about THIS RUN, not about the file as it looks now.

The bound is a function of the document count, and the watchdog runs on READ — potentially hours
after the run started. Re-deriving it there asks the wrong question, and `only_active` makes the
wrong answer specific: soft-delete documents during a long run and the derived bound SHRINKS below
the one the running task is actually holding. A healthy 44-document run gets failed, and the
processor is told it "timed out" while the work is still in flight.

So the limit is recorded on the run when it is enqueued. These tests pin both directions — the stored
value wins, and a run without one still reconciles.
"""

from __future__ import annotations

from app.api.verification import _watchdog_hard_limit
from app.core.run_limits import rule_engine_limits
from app.models.verification import Verification, VerificationStatus, VerificationTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def _running_run(db: AsyncSession, loan_file, *, limit: int | None) -> Verification:
    run = Verification(
        loan_file_id=loan_file.id,
        status=VerificationStatus.RUNNING,
        trigger=VerificationTrigger.MANUAL,
        time_limit_seconds=limit,
    )
    db.add(run)
    await db.flush()
    return run


async def test_the_stored_limit_survives_the_documents_being_deleted(db_session) -> None:
    """THE REPORTED HOLE. A 44-document run is enqueued and given ~2,962s. Documents are then
    soft-deleted — a processor tidying a file, a re-upload, a bad batch removed. Re-deriving would
    now return the 1,200s floor, and the watchdog would fail a run that is legitimately still
    working with most of its budget left."""
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    enqueued_limit = rule_engine_limits(44)[1]
    run = await _running_run(db_session, loan_file, limit=enqueued_limit)

    # The file now looks empty — every document gone since the run started.
    assert await _watchdog_hard_limit(db_session, run, loan_file.id) == enqueued_limit
    # And that is emphatically not what deriving would have said.
    assert rule_engine_limits(0)[1] < enqueued_limit


async def test_a_run_without_a_stored_limit_still_reconciles(db_session) -> None:
    """The fallback, for runs enqueued before the column existed. They behave exactly as they did
    before — wrong in the same narrow way, and far better than refusing to reconcile them at all,
    which would leave a dead run RUNNING forever."""
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    run = await _running_run(db_session, loan_file, limit=None)

    assert await _watchdog_hard_limit(db_session, run, loan_file.id) == rule_engine_limits(0)[1]


async def test_the_stored_limit_is_what_the_enqueue_computed(db_session) -> None:
    """The two halves must agree. A stored number that did not come from `rule_engine_limits` would
    make the watchdog's question meaningless — it would be comparing against a value no task was ever
    given."""
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    for _index in range(3):
        await factories.make_document(db_session, loan_file=loan_file, company=company)
    await db_session.flush()

    from app.api.verification import _document_count

    documents = await _document_count(db_session, loan_file.id)
    assert documents == 3
    run = await _running_run(db_session, loan_file, limit=rule_engine_limits(documents)[1])

    assert await _watchdog_hard_limit(db_session, run, loan_file.id) == rule_engine_limits(3)[1]
