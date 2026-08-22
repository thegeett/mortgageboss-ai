"""bug-001 — the re-link backfill: does a matcher fix reach the files already in the system?

Borrower linking runs ONCE, at extraction time. Without this script a matcher fix only ever reaches
documents uploaded after it deploys, and the file that exposed the bug stays broken.
"""

from __future__ import annotations

from app.models.document_borrower_link import DocumentBorrowerLink
from app.models.extraction import ExtractionStatus
from app.scripts.relink_document_borrowers import _relink
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories


async def _extracted(db: AsyncSession, document, name: str, *, status=ExtractionStatus.SUCCEEDED):
    await factories.make_extraction(
        db,
        document=document,
        data={"employee_name": {"value": name, "confidence": 0.99}},
        status=status,
    )


async def _links(db: AsyncSession, document_id) -> set:
    return set(
        (
            await db.scalars(
                select(DocumentBorrowerLink.borrower_id).where(
                    DocumentBorrowerLink.document_id == document_id
                )
            )
        ).all()
    )


async def test_the_real_case_gains_its_link(db_session: AsyncSession) -> None:
    """`Vidulasrri` on the application, `VIDULA SRRI` on the pay stub — unlinked before the fix."""
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    borrower = await factories.make_borrower(
        db_session, loan_file=loan_file, first_name="Vidulasrri", last_name="Muruganandam"
    )
    doc = await factories.make_document(
        db_session, loan_file=loan_file, company=company, document_type="pay_stub"
    )
    await _extracted(db_session, doc, "VIDULA SRRI MURUGANANDAM")
    await db_session.commit()

    assert await _links(db_session, doc.id) == set()  # as staging found it

    out = await _relink(db_session, apply=True, only_file=loan_file.display_id)

    assert await _links(db_session, doc.id) == {borrower.id}
    assert out.gained == 1 and out.lost == 0


async def test_report_only_writes_nothing(db_session: AsyncSession) -> None:
    """The write must be a second, deliberate step — not a side effect of looking."""
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    await factories.make_borrower(
        db_session, loan_file=loan_file, first_name="Vidulasrri", last_name="Muruganandam"
    )
    doc = await factories.make_document(
        db_session, loan_file=loan_file, company=company, document_type="pay_stub"
    )
    await _extracted(db_session, doc, "VIDULA SRRI MURUGANANDAM")
    await db_session.commit()
    # Captured BEFORE the run: report-only ends in a rollback, which expires every ORM object the
    # test still holds — reading `doc.id` afterwards would lazy-load on a session mid-rollback.
    doc_id, display_id = doc.id, loan_file.display_id

    out = await _relink(db_session, apply=False, only_file=display_id)

    assert out.gained == 1  # it SAYS what it would do
    assert await _links(db_session, doc_id) == set()  # and does not do it


async def test_a_failed_extraction_keeps_its_links(db_session: AsyncSession) -> None:
    """LP-569's guard, re-applied here. The linker DELETEs before it looks for names, so running it
    over an all-null extraction would commit the wipe — and a failed extraction is an ABSENCE OF
    DATA, not a determination that the document names nobody."""
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    borrower = await factories.make_borrower(
        db_session, loan_file=loan_file, first_name="Vidulasrri", last_name="Muruganandam"
    )
    doc = await factories.make_document(
        db_session, loan_file=loan_file, company=company, document_type="pay_stub"
    )
    await _extracted(db_session, doc, "VIDULA SRRI MURUGANANDAM", status=ExtractionStatus.FAILED)
    db_session.add(
        DocumentBorrowerLink(
            document_id=doc.id, borrower_id=borrower.id, confidence=1.0, method="exact"
        )
    )
    await db_session.commit()

    out = await _relink(db_session, apply=True, only_file=loan_file.display_id)

    assert await _links(db_session, doc.id) == {borrower.id}  # untouched
    assert out.extraction_failed == 1


async def test_running_twice_changes_nothing_the_second_time(db_session: AsyncSession) -> None:
    company = await factories.make_company(db_session, slug="acme")
    loan_file = await factories.make_loan_file(db_session, company=company)
    await factories.make_borrower(
        db_session, loan_file=loan_file, first_name="Vidulasrri", last_name="Muruganandam"
    )
    doc = await factories.make_document(
        db_session, loan_file=loan_file, company=company, document_type="pay_stub"
    )
    await _extracted(db_session, doc, "VIDULA SRRI MURUGANANDAM")
    await db_session.commit()

    await _relink(db_session, apply=True, only_file=loan_file.display_id)
    again = await _relink(db_session, apply=True, only_file=loan_file.display_id)

    assert again.gained == 0 and again.lost == 0 and again.unchanged == 1
