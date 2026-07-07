"""Tests for LP-118.7 store-everything — persist the parsed-but-dropped MISMO fields + stop the
parser silently losing unmapped leaves.

Anchored on the REAL fixture. Covers: the borrower current address + property county now persist
(parse → column, end to end); a genuinely-unmapped parsed leaf (FullName) now survives to the
catch-all instead of being dropped; the mapped subject-property leaves are consumed (NOT
double-stored in the catch-all); and existing mapped fields are unchanged.
"""

from pathlib import Path

import pytest
from app.mismo.import_service import create_loan_file_from_mismo
from app.mismo.parser import parse_mismo
from app.mismo.schema import ParsedMismo
from app.models import Borrower, Company, Property
from sqlalchemy import select
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
    from app.storage import get_storage_backend

    backend = get_storage_backend()
    monkeypatch.setattr(backend, "_base_dir", tmp_path, raising=False)
    return tmp_path


async def _company(db: AsyncSession, slug: str = "se") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _import(db: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes):
    company = await _company(db)
    return await create_loan_file_from_mismo(
        db, parsed=parsed, company_id=company.id, raw_content=raw_bytes
    )


# --------------------------------------------------------------------------- #
# Part A — the two dropped fields now persist
# --------------------------------------------------------------------------- #


async def test_borrower_current_address_persists(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    lf = await _import(db_session, parsed, raw_bytes)
    borrower = (
        (await db_session.execute(select(Borrower).where(Borrower.loan_file_id == lf.id)))
        .scalars()
        .first()
    )
    assert borrower is not None
    # Parsed all along (parser reads ADDRESSES/ADDRESS); now persisted to structured columns.
    assert borrower.current_address_line == parsed.borrowers[0].address_line
    assert borrower.current_city == parsed.borrowers[0].city
    assert borrower.current_state == parsed.borrowers[0].state
    assert borrower.current_postal_code == parsed.borrowers[0].postal_code
    assert borrower.current_address_type == parsed.borrowers[0].address_type
    # The real fixture actually carries a value (not just a null round-trip).
    assert borrower.current_address_line


async def test_property_county_persists(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    lf = await _import(db_session, parsed, raw_bytes)
    prop = (
        (await db_session.execute(select(Property).where(Property.loan_file_id == lf.id)))
        .scalars()
        .first()
    )
    assert prop is not None
    assert prop.county == parsed.property.county == "Bergen County"


# --------------------------------------------------------------------------- #
# Part B — no parsed leaf is silently lost
# --------------------------------------------------------------------------- #


def _catch_all_labels(result: ParsedMismo) -> list[tuple[str, str]]:
    return [(s.section, f.label) for s in result.catch_all for f in s.fields]


def test_unmapped_leaf_survives_to_catch_all(raw_bytes: bytes) -> None:
    """FullName is read (for the name-presence warning) but NOT persisted — previously consumed +
    dropped, now it falls through to the catch-all (peek, not text)."""
    result = parse_mismo(raw_bytes)
    labels = {label for _, label in _catch_all_labels(result)}
    assert "FullName" in labels  # previously dropped — now recoverable
    # And the value is genuinely present (not just the label).
    full_values = {f.value for s in result.catch_all for f in s.fields if f.label == "FullName"}
    assert result.borrowers[0].full_name in full_values


def test_mapped_subject_leaves_not_double_stored(raw_bytes: bytes) -> None:
    """The subject-property county + address ARE persisted (consumed by the typed core), so they
    must NOT also appear in the catch-all — no double-storage."""
    result = parse_mismo(raw_bytes)
    subject_labels = {
        label for section, label in _catch_all_labels(result) if "SUBJECT_PROPERTY" in section
    }
    assert "CountyName" not in subject_labels  # consumed → persisted, not duplicated
    assert "AddressLineText" not in subject_labels
    # Sanity: genuinely-non-core subject leaves DO remain in the catch-all (the safety net works).
    assert "FIPSCountyCode" in subject_labels


async def test_existing_mapped_fields_unchanged(
    db_session: AsyncSession, parsed: ParsedMismo, raw_bytes: bytes
) -> None:
    """Regression: the fields that already mapped still parse + persist unchanged."""
    lf = await _import(db_session, parsed, raw_bytes)
    prop = (
        (await db_session.execute(select(Property).where(Property.loan_file_id == lf.id)))
        .scalars()
        .first()
    )
    assert prop is not None
    # Mapped property fields untouched by the county addition.
    assert prop.address_line == parsed.property.address_line == "60 North Street"
    assert prop.city == "Elmwood Park"
    assert prop.estimated_value == parsed.property.estimated_value
    # Mapped borrower name fields untouched by the FullName peek change.
    borrower = (
        (await db_session.execute(select(Borrower).where(Borrower.loan_file_id == lf.id)))
        .scalars()
        .first()
    )
    assert borrower is not None
    assert (borrower.first_name, borrower.last_name) == ("Mahesh", "Chhotala")
