"""Tests for the borrower service (LP-29).

Exercises :mod:`app.services.borrowers` against the rollback ``db_session``:
CRUD, ordering by position, the minimal primary/position defaults and demote
behaviour, cross-file isolation of ``get_borrower``, and the SSN handling —
stored **encrypted at rest** (verified by reading the raw column with SQL that
bypasses the ``EncryptedString`` type) and surfaced only via ``masked_ssn``.
"""

from app.models import Company
from app.models.loan_file import LoanFile
from app.schemas.borrower import BorrowerCreate, BorrowerUpdate
from app.services.borrowers import (
    create_borrower,
    get_borrower,
    list_borrowers,
    soft_delete_borrower,
    update_borrower,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SSN = "123-45-6789"  # pragma: allowlist secret


async def _file(db: AsyncSession, slug: str = "acme") -> LoanFile:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return await create_loan_file(db, company_id=company.id)


async def test_first_borrower_defaults_primary_position_1(db_session: AsyncSession) -> None:
    """The first borrower on a file defaults to primary at position 1."""
    loan_file = await _file(db_session)
    borrower = await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Pat", last_name="Buyer"),
    )
    assert borrower.is_primary is True
    assert borrower.borrower_position == 1


async def test_second_borrower_defaults_nonprimary_next_position(db_session: AsyncSession) -> None:
    """A later borrower defaults to non-primary at the next position."""
    loan_file = await _file(db_session)
    await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Pat", last_name="Buyer"),
    )
    second = await create_borrower(
        db_session, loan_file_id=loan_file.id, data=BorrowerCreate(first_name="Sam", last_name="Co")
    )
    assert second.is_primary is False
    assert second.borrower_position == 2


async def test_creating_primary_demotes_others(db_session: AsyncSession) -> None:
    """Adding a borrower as primary clears the previous primary (one primary)."""
    loan_file = await _file(db_session)
    first = await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Pat", last_name="Buyer"),
    )
    assert first.is_primary is True

    second = await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Sam", last_name="Co", is_primary=True),
    )
    await db_session.refresh(first)
    assert second.is_primary is True
    assert first.is_primary is False


async def test_list_ordered_by_position(db_session: AsyncSession) -> None:
    """list_borrowers returns active borrowers ordered by position."""
    loan_file = await _file(db_session)
    await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="C", last_name="Three", borrower_position=3),
    )
    await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="A", last_name="One", borrower_position=1),
    )
    borrowers = await list_borrowers(db_session, loan_file_id=loan_file.id)
    assert [b.borrower_position for b in borrowers] == [1, 3]


async def test_get_borrower_is_scoped_to_the_file(db_session: AsyncSession) -> None:
    """get_borrower returns None for a borrower that belongs to a different file."""
    file_a = await _file(db_session, "company-a")
    file_b = await _file(db_session, "company-b")
    borrower = await create_borrower(
        db_session, loan_file_id=file_a.id, data=BorrowerCreate(first_name="Pat", last_name="Buyer")
    )
    # Found under its own file...
    assert (
        await get_borrower(db_session, loan_file_id=file_a.id, borrower_id=borrower.id) is not None
    )
    # ...but NOT under a different file.
    assert await get_borrower(db_session, loan_file_id=file_b.id, borrower_id=borrower.id) is None


async def test_update_applies_set_fields_and_reencrypts_ssn(db_session: AsyncSession) -> None:
    """Update applies only provided fields; a new ssn is re-encrypted."""
    loan_file = await _file(db_session)
    borrower = await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Pat", last_name="Buyer"),
    )
    await update_borrower(
        db_session, borrower=borrower, data=BorrowerUpdate(phone="555-0100", ssn=SSN)
    )
    assert borrower.phone == "555-0100"
    assert borrower.first_name == "Pat"  # untouched
    assert borrower.ssn == SSN  # round-trips through the ORM (decrypted)


async def test_soft_delete_excludes_from_reads(db_session: AsyncSession) -> None:
    """Soft delete sets deleted_at and removes the borrower from list/get."""
    loan_file = await _file(db_session)
    borrower = await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Pat", last_name="Buyer"),
    )
    await soft_delete_borrower(db_session, borrower=borrower)
    assert borrower.deleted_at is not None
    assert (
        await get_borrower(db_session, loan_file_id=loan_file.id, borrower_id=borrower.id) is None
    )
    assert await list_borrowers(db_session, loan_file_id=loan_file.id) == []


async def test_ssn_is_encrypted_at_rest(db_session: AsyncSession) -> None:
    """The raw ssn column holds ciphertext, not the plaintext SSN.

    Read the column with raw SQL, bypassing the EncryptedString decrypt step.
    """
    loan_file = await _file(db_session)
    borrower = await create_borrower(
        db_session,
        loan_file_id=loan_file.id,
        data=BorrowerCreate(first_name="Pat", last_name="Buyer", ssn=SSN),
    )
    raw = await db_session.scalar(
        text("SELECT ssn FROM borrowers WHERE id = :id"), {"id": borrower.id}
    )
    assert raw is not None
    assert raw != SSN
    assert SSN not in raw
    assert "123456789" not in raw  # also not the unformatted digits
    # The ORM round-trips it back to plaintext, and masking works.
    assert borrower.ssn == SSN
    assert borrower.masked_ssn == "***-**-6789"
