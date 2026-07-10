"""Documents section assembler (LP-206) — DB-backed (test DB has the real schema).

Covers: single-borrower, joint, no-match belongsTo; soft-deleted document +
soft-deleted borrower exclusion; honest confidence; PII masking (no raw); and
absent≠empty. Seeds an LF-6T3N-like file.
"""

from typing import Any
from uuid import UUID

from app.models import (
    Borrower,
    Company,
    Document,
    ExtractionStatus,
    UploadSource,
)
from app.models.base import utcnow
from app.models.document_borrower_link import DocumentBorrowerLink, MatchMethod
from app.services.extractions import create_extraction_version
from app.services.loan_files import create_loan_file
from app.verification.snapshot.documents_section import build_documents_section
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.pii import PiiField
from sqlalchemy.ext.asyncio import AsyncSession


def _field(value: Any, confidence: float | None) -> dict[str, Any]:
    return {"value": value, "source": None, "confidence": confidence}


async def _seed(db: AsyncSession) -> tuple[UUID, dict[str, Borrower], dict[str, Document]]:
    company = Company(name="Acme", slug="acme")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    akash = Borrower(
        loan_file_id=lf.id,
        first_name="Akash",
        last_name="Patel",
        is_primary=True,
        borrower_position=1,
    )
    priya = Borrower(loan_file_id=lf.id, first_name="Priya", last_name="Patel", borrower_position=2)
    db.add_all([akash, priya])
    await db.flush()

    docs: dict[str, Document] = {}

    async def _doc(slug: str, extracted: dict[str, Any] | None) -> Document:
        d = Document(
            loan_file_id=lf.id,
            original_filename=f"{slug}.pdf",
            mime_type="application/pdf",
            file_size_bytes=1,
            storage_path=f"lf/{slug}.pdf",
            upload_source=UploadSource.USER_UPLOAD,
            document_type=slug,
        )
        db.add(d)
        await db.flush()
        if extracted is not None:
            await create_extraction_version(
                db,
                document_id=d.id,
                extracted_data=extracted,
                extraction_status=ExtractionStatus.SUCCEEDED,
            )
        docs[slug] = d
        return d

    await _doc(
        "pay_stub",
        {
            "employee_name": _field("Akash Patel", 0.98),
            "gross_pay": _field("5700.00", 0.94),
            "rate": _field(None, None),  # absent — omitted
            "pay_frequency": _field("", 0.5),  # present-empty
        },
    )
    await _doc(
        "bank_statement",
        {
            "account_holder_name": _field("Akash Patel and Priya Patel", 0.96),
            "account_number_masked": _field("****3312", 0.99),  # pre-masked PII
        },
    )
    await _doc("appraisal", {"appraised_value": _field("485000.00", 0.96)})

    # A soft-deleted document — must be excluded from the section.
    gone = await _doc("w2", {"employee_name": _field("Akash Patel", 0.9)})
    gone.deleted_at = utcnow()

    # Links: pay_stub → Akash; bank_statement → both (joint).
    db.add_all(
        [
            DocumentBorrowerLink(
                document_id=docs["pay_stub"].id,
                borrower_id=akash.id,
                confidence=1.0,
                method=MatchMethod.EXACT,
            ),
            DocumentBorrowerLink(
                document_id=docs["bank_statement"].id,
                borrower_id=akash.id,
                confidence=0.97,
                method=MatchMethod.NORMALIZED,
            ),
            DocumentBorrowerLink(
                document_id=docs["bank_statement"].id,
                borrower_id=priya.id,
                confidence=0.97,
                method=MatchMethod.NORMALIZED,
            ),
        ]
    )
    await db.flush()
    return lf.id, {"akash": akash, "priya": priya}, docs


def _by_type(entries: list, doc_type: str):
    return next(e for e in entries if e.document_type == doc_type)


async def _section(db: AsyncSession):
    lf_id, borrowers, _docs = await _seed(db)
    from app.models.loan_file import LoanFile
    from sqlalchemy import select

    loan_file = (await db.execute(select(LoanFile).where(LoanFile.id == lf_id))).scalar_one()
    return await build_documents_section(db, loan_file), borrowers


async def test_single_borrower_belongs_to_and_asserted_name(db_session: AsyncSession) -> None:
    entries, borrowers = await _section(db_session)
    pay = _by_type(entries, "pay_stub")
    assert pay.belongs_to is not None and len(pay.belongs_to) == 1
    ref = pay.belongs_to[0]
    assert ref.borrower_id == borrowers["akash"].id
    assert ref.name == "Akash Patel"
    # raw asserted name kept in fields, distinct from the resolved ref
    assert pay.fields["asserted_name"].value == "Akash Patel"
    assert pay.fields["employee_name"].value == "Akash Patel"


async def test_joint_document_belongs_to_multiple(db_session: AsyncSession) -> None:
    entries, borrowers = await _section(db_session)
    bank = _by_type(entries, "bank_statement")
    assert bank.belongs_to is not None and len(bank.belongs_to) == 2
    assert {r.borrower_id for r in bank.belongs_to} == {
        borrowers["akash"].id,
        borrowers["priya"].id,
    }
    assert {r.name for r in bank.belongs_to} == {"Akash Patel", "Priya Patel"}


async def test_no_match_document_belongs_to_is_none(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    appraisal = _by_type(entries, "appraisal")
    assert appraisal.belongs_to is None
    assert appraisal.fields["appraised_value"].value == "485000.00"


async def test_soft_deleted_document_excluded(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    assert all(e.document_type != "w2" for e in entries)


async def test_link_to_soft_deleted_borrower_excluded(db_session: AsyncSession) -> None:
    lf_id, borrowers, _docs = await _seed(db_session)
    borrowers["priya"].deleted_at = utcnow()  # remove a joint borrower after matching
    await db_session.flush()
    from app.models.loan_file import LoanFile
    from sqlalchemy import select

    loan_file = (
        await db_session.execute(select(LoanFile).where(LoanFile.id == lf_id))
    ).scalar_one()
    entries = await build_documents_section(db_session, loan_file)
    bank = _by_type(entries, "bank_statement")
    # Only Akash remains; Priya's link is dropped (soft-delete-safe read).
    assert bank.belongs_to is not None and len(bank.belongs_to) == 1
    assert bank.belongs_to[0].borrower_id == borrowers["akash"].id


async def test_confidence_surfaced_faithfully_never_fabricated(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    pay = _by_type(entries, "pay_stub")
    assert pay.fields["gross_pay"].confidence == 0.94
    assert pay.fields["employee_name"].confidence == 0.98
    # every field is source=extracted
    assert all(f.source is FieldSource.EXTRACTED for f in pay.fields.values())


async def test_pii_account_is_masked_piifield_no_raw(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    bank = _by_type(entries, "bank_statement")
    acct = bank.fields["account_number_masked"]
    assert isinstance(acct, PiiField)
    assert acct.display == "****3312"
    assert acct.match_hash is None  # only the masked form was ever captured
    blob = repr({k: v.model_dump() for e in entries for k, v in e.fields.items()})
    assert "3312" in bank.fields["account_number_masked"].display  # last-4 shown
    # no long raw digit-run anywhere
    import re

    assert not re.search(r"\d{9,}", blob)


async def test_absent_field_omitted_present_empty_kept(db_session: AsyncSession) -> None:
    entries, _ = await _section(db_session)
    pay = _by_type(entries, "pay_stub")
    assert "rate" not in pay.fields  # value was null → absent
    assert pay.fields["pay_frequency"] == Field.present(
        "", source=FieldSource.EXTRACTED, confidence=0.5
    )
    assert pay.fields["pay_frequency"].value == ""  # present-empty
