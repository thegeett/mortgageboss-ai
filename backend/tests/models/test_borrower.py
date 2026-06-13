"""Tests for the Borrower model (LP-14).

Covers the two patterns this model introduces, against a real table:

  * **Encrypted SSN** — round-trips through the ORM, is stored as ciphertext at
    rest (verified by reading the raw column with SQL that bypasses the
    EncryptedString type), is masked for display, and never appears in the repr.
  * **Multiple borrowers per file** — a primary borrower plus co-borrowers,
    ordered by position, reachable from ``loan_file.borrowers``.

Plus the usual model guarantees: the marital-status CHECK constraint, soft
delete + only_active, and tenant isolation (borrowers reachable only through the
owning company's loan files, since they have no company_id of their own).

Uses the transaction-rollback ``db_session`` fixture from LP-10.
"""

import pytest
from app.models import (
    Borrower,
    Company,
    LoanFile,
    MaritalStatus,
    only_active,
    scope_to_company,
    utcnow,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

SSN = "123-45-6789"


async def _make_company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def _make_loan_file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _add_borrower(
    db_session: AsyncSession,
    loan_file: LoanFile,
    *,
    first_name: str = "Jane",
    last_name: str = "Doe",
    ssn: str | None = None,
    is_primary: bool = True,
    position: int = 1,
    marital_status: MaritalStatus | None = None,
) -> Borrower:
    borrower = Borrower(
        loan_file_id=loan_file.id,
        first_name=first_name,
        last_name=last_name,
        ssn=ssn,
        is_primary=is_primary,
        borrower_position=position,
        marital_status=marital_status,
    )
    db_session.add(borrower)
    await db_session.flush()
    return borrower


async def test_ssn_round_trips_through_the_orm(db_session: AsyncSession) -> None:
    """An SSN written through the model decrypts back to the same value on read."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _add_borrower(db_session, loan_file, ssn=SSN)

    # Re-read from the database so the value round-trips through decrypt.
    await db_session.refresh(borrower)
    assert borrower.ssn == SSN


async def test_ssn_is_encrypted_at_rest(db_session: AsyncSession) -> None:
    """The raw column holds ciphertext, not the plaintext SSN.

    Read the column with raw SQL, which bypasses the EncryptedString type's
    decrypt step, so we see exactly what is stored on disk.
    """
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _add_borrower(db_session, loan_file, ssn=SSN)

    raw = await db_session.scalar(
        text("SELECT ssn FROM borrowers WHERE id = :id"), {"id": borrower.id}
    )
    assert raw is not None
    assert raw != SSN
    assert SSN not in raw
    # Plain digits must not appear either (it is genuinely encrypted, not just
    # reformatted).
    assert "123456789" not in raw


async def test_masked_ssn_format(db_session: AsyncSession) -> None:
    """masked_ssn returns ***-**-1234 (last 4 only), or None when unset."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)

    with_ssn = await _add_borrower(db_session, loan_file, ssn=SSN)
    assert with_ssn.masked_ssn == "***-**-6789"

    without = await _add_borrower(
        db_session, loan_file, first_name="No", last_name="Ssn", is_primary=False, position=2
    )
    assert without.masked_ssn is None


async def test_repr_never_contains_ssn_or_pii(db_session: AsyncSession) -> None:
    """The repr must not leak the SSN (or other full PII) into logs/tracebacks."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _add_borrower(db_session, loan_file, ssn=SSN)

    text_repr = repr(borrower)
    assert SSN not in text_repr
    assert "123456789" not in text_repr
    # The name is PII too and must not be in the repr.
    assert "Jane" not in text_repr
    # The repr is still useful: it identifies the borrower by position.
    assert "position=1" in text_repr


async def test_multiple_borrowers_ordered_by_position(db_session: AsyncSession) -> None:
    """A file can hold a primary borrower plus co-borrowers, ordered by position."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)

    primary = await _add_borrower(
        db_session, loan_file, first_name="Jane", ssn=SSN, is_primary=True, position=1
    )
    co = await _add_borrower(
        db_session,
        loan_file,
        first_name="John",
        ssn="987-65-4321",
        is_primary=False,
        position=2,
    )

    # loan_file.borrowers returns both, ordered by borrower_position.
    stmt = (
        select(LoanFile)
        .where(LoanFile.id == loan_file.id)
        .options(selectinload(LoanFile.borrowers))
    )
    loaded = (await db_session.scalars(stmt)).one()
    assert [b.id for b in loaded.borrowers] == [primary.id, co.id]
    assert [b.is_primary for b in loaded.borrowers] == [True, False]
    assert [b.borrower_position for b in loaded.borrowers] == [1, 2]
    # Each borrower's own SSN round-trips independently.
    assert loaded.borrowers[0].ssn == SSN
    assert loaded.borrowers[1].ssn == "987-65-4321"


async def test_marital_status_check_constraint_rejects_invalid_value(
    db_session: AsyncSession,
) -> None:
    """The DB CHECK constraint rejects an out-of-range marital_status."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _add_borrower(db_session, loan_file)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE borrowers SET marital_status = :bad WHERE id = :id"),
                {"bad": "complicated", "id": borrower.id},
            )


async def test_marital_status_accepts_valid_enum(db_session: AsyncSession) -> None:
    """A valid MaritalStatus persists and reads back as the enum member."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _add_borrower(db_session, loan_file, marital_status=MaritalStatus.MARRIED)

    await db_session.refresh(borrower)
    assert borrower.marital_status is MaritalStatus.MARRIED


async def test_soft_delete_and_only_active(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at; only_active() filters such borrowers out."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    live = await _add_borrower(db_session, loan_file, first_name="Live", position=1)
    gone = await _add_borrower(
        db_session, loan_file, first_name="Gone", is_primary=False, position=2
    )

    gone.deleted_at = utcnow()
    await db_session.flush()
    assert gone.is_deleted is True

    stmt = only_active(select(Borrower), Borrower)
    ids = {b.id for b in (await db_session.scalars(stmt)).all()}
    assert live.id in ids
    assert gone.id not in ids


async def test_full_name_skips_absent_middle_name(db_session: AsyncSession) -> None:
    """full_name joins the name parts, omitting an absent middle name."""
    company = await _make_company(db_session, "acme")
    loan_file = await _make_loan_file(db_session, company)
    borrower = await _add_borrower(db_session, loan_file, first_name="Jane", last_name="Doe")
    assert borrower.full_name == "Jane Doe"

    borrower.middle_name = "Q"
    assert borrower.full_name == "Jane Q Doe"


async def test_borrowers_are_isolated_by_company_through_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """Borrowers carry no company_id; isolation is transitive via the loan file.

    A query scoped to company A's loan files must never surface company B's
    borrowers (ADR-052).
    """
    company_a = await _make_company(db_session, "company-a")
    company_b = await _make_company(db_session, "company-b")
    file_a = await _make_loan_file(db_session, company_a)
    file_b = await _make_loan_file(db_session, company_b)

    borrower_a = await _add_borrower(db_session, file_a, first_name="Alice", ssn=SSN)
    borrower_b = await _add_borrower(db_session, file_b, first_name="Bob", ssn="987-65-4321")

    # Borrowers reached by joining through the company-scoped loan files.
    stmt_a = scope_to_company(
        select(Borrower).join(LoanFile, Borrower.loan_file_id == LoanFile.id),
        LoanFile,
        company_a.id,
    )
    ids_a = {b.id for b in (await db_session.scalars(stmt_a)).all()}
    assert ids_a == {borrower_a.id}
    assert borrower_b.id not in ids_a

    stmt_b = scope_to_company(
        select(Borrower).join(LoanFile, Borrower.loan_file_id == LoanFile.id),
        LoanFile,
        company_b.id,
    )
    ids_b = {b.id for b in (await db_session.scalars(stmt_b)).all()}
    assert ids_b == {borrower_b.id}
    assert ids_a.isdisjoint(ids_b)
