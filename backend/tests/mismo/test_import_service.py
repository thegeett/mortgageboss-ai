"""Tests for the MISMO → models mapping + file-creation service (LP-53).

Anchored on the REAL fixture (parsed by LP-51): create_loan_file_from_mismo maps
it into a correct, fully-populated LoanFile with exact stated financials. Also
covers convergence (a normal usable file), transactional all-or-nothing, the
partial-parse create+warn + the floor, tenant scoping, and the PII discipline
(SSN encrypted at rest, never logged; names/amounts never logged).
"""

from decimal import Decimal
from pathlib import Path

import pytest
import structlog
from app.core.config import settings
from app.mismo import import_service
from app.mismo.import_service import MismoImportError, create_loan_file_from_mismo
from app.mismo.parser import parse_mismo
from app.mismo.schema import ParsedMismo
from app.models import (
    Borrower,
    Company,
    LoanFile,
    LoanProgram,
    LoanPurpose,
    MaritalStatus,
    MismoImport,
    MismoImportStatus,
    OccupancyType,
    Property,
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.storage import get_storage_backend
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"


@pytest.fixture
def raw_bytes() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
def parsed(raw_bytes: bytes) -> ParsedMismo:
    return parse_mismo(raw_bytes)


@pytest.fixture(autouse=True)
def storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the storage backend at an isolated temp dir (never real ./storage)."""
    monkeypatch.setattr(settings, "storage_local_path", str(tmp_path / "storage"))
    get_storage_backend.cache_clear()
    yield
    get_storage_backend.cache_clear()


async def _company(db_session: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


# --------------------------------------------------------------------------- #
# Real fixture → a correct, populated file (exact values)
# --------------------------------------------------------------------------- #


async def test_real_fixture_creates_correct_file(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
    )

    # Loan
    assert lf.company_id == company.id
    assert lf.loan_amount == Decimal("1104000.00")
    assert lf.note_rate_percent == Decimal("6.8750")
    assert lf.loan_program is LoanProgram.CONVENTIONAL
    assert lf.loan_purpose is LoanPurpose.PURCHASE
    assert lf.amortization_type == "Fixed"
    assert lf.amortization_months == 360
    assert lf.application_received_date.isoformat() == "2026-06-02"

    # Property
    prop = (await db_session.scalars(select(Property).where(Property.loan_file_id == lf.id))).one()
    assert prop.city == "Elmwood Park" and prop.state == "NJ"
    assert prop.estimated_value == Decimal("1380000.00")
    assert prop.occupancy_type is OccupancyType.PRIMARY_RESIDENCE
    assert prop.attachment_type == "Detached" and prop.financed_unit_count == 1

    # Borrower
    borrower = (
        await db_session.scalars(select(Borrower).where(Borrower.loan_file_id == lf.id))
    ).one()
    assert (borrower.first_name, borrower.last_name) == ("Mahesh", "Chhotala")
    assert borrower.date_of_birth.isoformat() == "1984-02-17"
    assert borrower.marital_status is MaritalStatus.MARRIED
    assert borrower.dependent_count == 3
    assert borrower.is_primary is True
    assert borrower.citizenship == "PermanentResidentAlien"
    assert borrower.declarations["IntentToOccupyType"] == "Yes"
    assert borrower.ssn is not None and len(borrower.ssn) == 9  # decrypts via the property

    # Stated financials — exact values + counts
    incomes = (
        await db_session.scalars(
            select(StatedIncomeItem).where(StatedIncomeItem.borrower_id == borrower.id)
        )
    ).all()
    assert sorted(i.monthly_amount for i in incomes) == [Decimal("7000.00"), Decimal("9400.00")]
    employers = await db_session.scalar(
        select(func.count())
        .select_from(StatedEmployer)
        .where(StatedEmployer.borrower_id == borrower.id)
    )
    assert employers == 3
    assert (
        await db_session.scalar(
            select(func.count()).select_from(StatedAsset).where(StatedAsset.loan_file_id == lf.id)
        )
    ) == 9
    liabs = (
        await db_session.scalars(
            select(StatedLiability).where(StatedLiability.loan_file_id == lf.id)
        )
    ).all()
    assert len(liabs) == 10
    mortgage = next(x for x in liabs if x.liability_type == "MortgageLoan")
    assert mortgage.monthly_payment == Decimal("4263.00")

    # Catch-all + import record + raw file
    record = (
        await db_session.scalars(select(MismoImport).where(MismoImport.loan_file_id == lf.id))
    ).one()
    assert record.source_format == "xml"
    assert record.status is MismoImportStatus.COMPLETED  # real file has no warnings
    assert record.catch_all  # non-empty
    assert record.raw_file_path
    # The raw MISMO file is stored (audit) and round-trips.
    assert await get_storage_backend().read(record.raw_file_path) == raw_bytes


async def test_converges_with_manual_file(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    """The created file is a normal, usable LoanFile (ids generated, DRAFT, etc.)."""
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
    )
    assert lf.display_id and lf.display_id.startswith("LF-")
    assert lf.inbox_token  # the same capability a manual file has
    assert lf.status.value == "draft"
    # Reachable through the normal scoped path.
    got = await db_session.get(LoanFile, lf.id)
    assert got is not None and got.company_id == company.id


# --------------------------------------------------------------------------- #
# Transactional all-or-nothing
# --------------------------------------------------------------------------- #


async def test_transactional_rollback_on_midway_failure(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = await _company(db_session)

    class _BoomBackend:
        async def save(self, **_: object) -> str:
            raise RuntimeError("storage down")

    monkeypatch.setattr(import_service, "get_storage_backend", lambda: _BoomBackend())

    # The whole creation runs inside one savepoint; a mid-way failure rolls it
    # all back — no half-created file.
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await create_loan_file_from_mismo(
                db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
            )

    assert (await db_session.scalar(select(func.count()).select_from(LoanFile))) == 0
    assert (await db_session.scalar(select(func.count()).select_from(Borrower))) == 0
    assert (await db_session.scalar(select(func.count()).select_from(StatedLiability))) == 0


# --------------------------------------------------------------------------- #
# Partial parse — create + warn; the floor
# --------------------------------------------------------------------------- #


async def test_partial_parse_creates_with_warnings(
    db_session: AsyncSession, raw_bytes: bytes
) -> None:
    parsed = parse_mismo(raw_bytes)
    # Simulate a partial parse: drop the property value + record a warning.
    assert parsed.property is not None
    parsed.property.estimated_value = None
    parsed.parse_warnings.append("Subject property is missing an estimated value.")

    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
    )
    prop = (await db_session.scalars(select(Property).where(Property.loan_file_id == lf.id))).one()
    assert prop.estimated_value is None  # missing → null, not blocked
    record = (
        await db_session.scalars(select(MismoImport).where(MismoImport.loan_file_id == lf.id))
    ).one()
    assert record.status is MismoImportStatus.PARTIAL
    assert any("estimated value" in w for w in record.parse_warnings)


async def test_floor_rejects_empty_parse(db_session: AsyncSession, raw_bytes: bytes) -> None:
    company = await _company(db_session)
    empty = ParsedMismo(borrowers=[], loan=None, property=None)
    with pytest.raises(MismoImportError):
        await create_loan_file_from_mismo(
            db_session, parsed=empty, company_id=company.id, raw_content=b"<MESSAGE/>"
        )
    # Nothing was created.
    assert (await db_session.scalar(select(func.count()).select_from(LoanFile))) == 0


async def test_creates_with_loan_but_no_borrower(
    db_session: AsyncSession, raw_bytes: bytes
) -> None:
    """Above the floor: loan present, no borrower → still creates the file."""
    parsed = parse_mismo(raw_bytes)
    parsed.borrowers = []  # keep the loan
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
    )
    assert lf.loan_amount == Decimal("1104000.00")
    assert (await db_session.scalar(select(func.count()).select_from(Borrower))) == 0


# --------------------------------------------------------------------------- #
# Tenant scoping
# --------------------------------------------------------------------------- #


async def test_tenant_scoping(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    a = await _company(db_session, "alpha")
    b = await _company(db_session, "bravo")
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=a.id, raw_content=raw_bytes
    )
    # Liabilities reachable scoped to A, never to B.
    in_a = (
        await db_session.scalars(
            select(StatedLiability).join(LoanFile).where(LoanFile.company_id == a.id)
        )
    ).all()
    assert len(in_a) == 10
    in_b = (
        await db_session.scalars(
            select(StatedLiability).join(LoanFile).where(LoanFile.company_id == b.id)
        )
    ).all()
    assert in_b == []
    assert lf.company_id == a.id


# --------------------------------------------------------------------------- #
# PII discipline
# --------------------------------------------------------------------------- #


async def test_ssn_encrypted_at_rest(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    company = await _company(db_session)
    lf = await create_loan_file_from_mismo(
        db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
    )
    borrower = (
        await db_session.scalars(select(Borrower).where(Borrower.loan_file_id == lf.id))
    ).one()
    plaintext = borrower.ssn  # decrypted via the model
    # The raw stored column is ciphertext — NOT the plaintext SSN.
    raw_col = await db_session.scalar(
        text("SELECT ssn FROM borrowers WHERE id = :id"), {"id": borrower.id}
    )
    assert raw_col is not None
    assert raw_col != plaintext
    assert plaintext not in raw_col


async def test_no_pii_logged(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    company = await _company(db_session)
    with structlog.testing.capture_logs() as logs:
        lf = await create_loan_file_from_mismo(
            db_session, parsed=parsed, company_id=company.id, raw_content=raw_bytes
        )
    borrower = (
        await db_session.scalars(select(Borrower).where(Borrower.loan_file_id == lf.id))
    ).one()
    blob = repr(logs)
    assert borrower.ssn not in blob  # SSN never logged
    assert "Mahesh" not in blob  # nor names
    assert "Chhotala" not in blob
    assert "1104000" not in blob  # nor amounts
    assert any(e.get("event") == "mismo_import_created" for e in logs)  # metadata present
