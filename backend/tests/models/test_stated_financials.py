"""Tests for the stated-financials models + MISMO import record (LP-52).

Covers (against real tables, via the rollback ``db_session`` fixture): typed
round-trip (Decimals exact, dates, JSON, bool), the one-to-many relationships
(borrower → income/employers; file → liabilities/assets/imports) with
cascade-from-parent, per-model tenant isolation (transitive via the file), the
extended MISMO core fields on Borrower/Property/LoanFile (nullable), the
catch-all + import record + raw-file reference, the MismoImportStatus CHECK, and
flexible-string MISMO categories.
"""

from datetime import date
from decimal import Decimal

import pytest
from app.models import (
    Borrower,
    Company,
    LoanFile,
    MismoImport,
    MismoImportStatus,
    Property,
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.services.loan_files import create_loan_file
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def _company(db_session: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=slug)
    db_session.add(company)
    await db_session.flush()
    return company


async def _file(db_session: AsyncSession, company: Company) -> LoanFile:
    return await create_loan_file(db_session, company_id=company.id)


async def _borrower(db_session: AsyncSession, loan_file: LoanFile) -> Borrower:
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Jane", last_name="Doe")
    db_session.add(borrower)
    await db_session.flush()
    return borrower


# --------------------------------------------------------------------------- #
# Typed round-trip
# --------------------------------------------------------------------------- #


async def test_stated_models_round_trip_typed_values(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    borrower = await _borrower(db_session, lf)

    db_session.add_all(
        [
            StatedIncomeItem(
                borrower_id=borrower.id,
                monthly_amount=Decimal("7000.00"),
                income_type="Base",
                employment_income=True,
            ),
            StatedEmployer(borrower_id=borrower.id, employer_name="Cascade Logistics LLC"),
            StatedLiability(
                loan_file_id=lf.id,
                liability_type="MortgageLoan",
                monthly_payment=Decimal("4263.00"),
                unpaid_balance=Decimal("582417.00"),
                holder_name="NR/SMS/CAL",
            ),
            StatedAsset(
                loan_file_id=lf.id,
                asset_type="GiftOfCash",
                value=Decimal("56000.00"),
                holder_name="Relative",
            ),
        ]
    )
    await db_session.flush()
    db_session.expunge_all()

    income = (await db_session.scalars(select(StatedIncomeItem))).one()
    assert income.monthly_amount == Decimal("7000.00")  # exact Decimal
    assert income.income_type == "Base" and income.employment_income is True
    liab = (await db_session.scalars(select(StatedLiability))).one()
    assert liab.monthly_payment == Decimal("4263.00")
    assert liab.unpaid_balance == Decimal("582417.00")
    asset = (await db_session.scalars(select(StatedAsset))).one()
    assert asset.value == Decimal("56000.00")


async def test_mismo_import_round_trip(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    record = MismoImport(
        loan_file_id=lf.id,
        source_format="xml",
        status=MismoImportStatus.COMPLETED,
        parse_warnings=["Subject property is missing an estimated value."],
        catch_all=[
            {"section": "LOANS/LOAN", "fields": [{"label": "FIPSCountyCode", "value": "003"}]}
        ],
        raw_file_path=f"{company.id}/{lf.id}/mismo/original.xml",
    )
    db_session.add(record)
    await db_session.flush()
    db_session.expunge_all()

    got = (await db_session.scalars(select(MismoImport))).one()
    assert got.source_format == "xml"
    assert got.status is MismoImportStatus.COMPLETED
    assert got.parse_warnings == ["Subject property is missing an estimated value."]
    assert got.catch_all[0]["fields"][0]["label"] == "FIPSCountyCode"
    assert got.raw_file_path.endswith("original.xml")


# --------------------------------------------------------------------------- #
# One-to-many relationships + cascade-from-parent
# --------------------------------------------------------------------------- #


async def test_one_to_many_relationships(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    borrower = await _borrower(db_session, lf)
    db_session.add_all(
        [
            StatedIncomeItem(borrower_id=borrower.id, monthly_amount=Decimal("7000.00")),
            StatedIncomeItem(borrower_id=borrower.id, monthly_amount=Decimal("9400.00")),
            StatedEmployer(borrower_id=borrower.id, employer_name="Swad Mania LLC"),
            StatedEmployer(borrower_id=borrower.id, employer_name="CHHOTALA REALTY LLC"),
            *[StatedLiability(loan_file_id=lf.id, liability_type="Revolving") for _ in range(3)],
            *[StatedAsset(loan_file_id=lf.id, asset_type="Stock") for _ in range(2)],
        ]
    )
    await db_session.flush()
    db_session.expunge_all()

    got_b = (
        await db_session.scalars(
            select(Borrower)
            .options(
                selectinload(Borrower.stated_income_items), selectinload(Borrower.stated_employers)
            )
            .where(Borrower.id == borrower.id)
        )
    ).one()
    assert len(got_b.stated_income_items) == 2
    assert len(got_b.stated_employers) == 2

    got_lf = (
        await db_session.scalars(
            select(LoanFile)
            .options(
                selectinload(LoanFile.stated_liabilities), selectinload(LoanFile.stated_assets)
            )
            .where(LoanFile.id == lf.id)
        )
    ).one()
    assert len(got_lf.stated_liabilities) == 3
    assert len(got_lf.stated_assets) == 2


async def test_cascade_delete_from_parent(db_session: AsyncSession) -> None:
    """DB-level ON DELETE CASCADE: removing a parent removes its owned children."""
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    borrower = await _borrower(db_session, lf)
    db_session.add(StatedIncomeItem(borrower_id=borrower.id, monthly_amount=Decimal("7000.00")))
    db_session.add(StatedLiability(loan_file_id=lf.id, liability_type="MortgageLoan"))
    await db_session.flush()

    # Deleting the borrower (DB cascade) removes its income items; the file-owned
    # liability survives. (Core delete → exercises the FK ON DELETE CASCADE.)
    await db_session.execute(sa_delete(Borrower).where(Borrower.id == borrower.id))
    await db_session.flush()
    assert (await db_session.scalar(select(func.count()).select_from(StatedIncomeItem))) == 0
    assert (await db_session.scalar(select(func.count()).select_from(StatedLiability))) == 1

    # Deleting the file cascades to its liabilities (and assets, imports, …).
    await db_session.execute(sa_delete(LoanFile).where(LoanFile.id == lf.id))
    await db_session.flush()
    assert (await db_session.scalar(select(func.count()).select_from(StatedLiability))) == 0


# --------------------------------------------------------------------------- #
# Tenant isolation (transitive via the loan file)
# --------------------------------------------------------------------------- #


async def test_tenant_isolation_file_level_models(db_session: AsyncSession) -> None:
    a = await _company(db_session, "alpha")
    b = await _company(db_session, "bravo")
    lf_a = await _file(db_session, a)
    lf_b = await _file(db_session, b)
    db_session.add(StatedLiability(loan_file_id=lf_a.id, liability_type="MortgageLoan"))
    db_session.add(StatedLiability(loan_file_id=lf_b.id, liability_type="Revolving"))
    db_session.add(StatedAsset(loan_file_id=lf_a.id, asset_type="Stock"))
    await db_session.flush()

    # Scoped (transitively via the file) to A → only A's rows.
    liab_a = (
        await db_session.scalars(
            select(StatedLiability).join(LoanFile).where(LoanFile.company_id == a.id)
        )
    ).all()
    assert {x.liability_type for x in liab_a} == {"MortgageLoan"}
    # Every returned row genuinely belongs to company A's file.
    for x in liab_a:
        parent = await db_session.get(LoanFile, x.loan_file_id)
        assert parent is not None and parent.company_id == a.id
    # B's scope sees only B's row, never A's.
    liab_b = (
        await db_session.scalars(
            select(StatedLiability).join(LoanFile).where(LoanFile.company_id == b.id)
        )
    ).all()
    assert {x.liability_type for x in liab_b} == {"Revolving"}


async def test_tenant_isolation_borrower_level_models(db_session: AsyncSession) -> None:
    a = await _company(db_session, "alpha")
    b = await _company(db_session, "bravo")
    borrower_a = await _borrower(db_session, await _file(db_session, a))
    borrower_b = await _borrower(db_session, await _file(db_session, b))
    db_session.add(StatedIncomeItem(borrower_id=borrower_a.id, income_type="Base"))
    db_session.add(StatedEmployer(borrower_id=borrower_b.id, employer_name="B Corp"))
    await db_session.flush()

    income_a = (
        await db_session.scalars(
            select(StatedIncomeItem)
            .join(Borrower)
            .join(LoanFile)
            .where(LoanFile.company_id == a.id)
        )
    ).all()
    assert len(income_a) == 1 and income_a[0].borrower_id == borrower_a.id
    # B's company sees none of A's income items.
    income_b = (
        await db_session.scalars(
            select(StatedIncomeItem)
            .join(Borrower)
            .join(LoanFile)
            .where(LoanFile.company_id == b.id)
        )
    ).all()
    assert income_b == []


# --------------------------------------------------------------------------- #
# Extended MISMO core fields (nullable) on the existing models
# --------------------------------------------------------------------------- #


async def test_extended_core_fields_persist(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    lf.note_amount = Decimal("1104000.00")
    lf.note_rate_percent = Decimal("6.8750")
    lf.lien_priority = "FirstLien"
    lf.amortization_type = "Fixed"
    lf.amortization_months = 360
    lf.application_received_date = date(2026, 6, 2)

    borrower = Borrower(
        loan_file_id=lf.id,
        first_name="Mahesh",
        last_name="Chhotala",
        dependent_count=3,
        citizenship="PermanentResidentAlien",
        declarations={"BankruptcyIndicator": "false", "IntentToOccupyType": "Yes"},
    )
    prop = Property(
        loan_file_id=lf.id,
        valuation_amount=Decimal("1380000.00"),
        attachment_type="Detached",
        construction_method="SiteBuilt",
        financed_unit_count=1,
    )
    db_session.add_all([borrower, prop])
    await db_session.flush()
    db_session.expunge_all()

    got_lf = await db_session.get(LoanFile, lf.id)
    assert got_lf.note_rate_percent == Decimal("6.8750")
    assert got_lf.amortization_months == 360
    assert got_lf.application_received_date == date(2026, 6, 2)
    got_b = (await db_session.scalars(select(Borrower))).one()
    assert got_b.dependent_count == 3
    assert got_b.declarations["IntentToOccupyType"] == "Yes"
    got_p = (await db_session.scalars(select(Property))).one()
    assert got_p.valuation_amount == Decimal("1380000.00")
    assert got_p.financed_unit_count == 1


async def test_core_fields_default_null_on_manual_creation(db_session: AsyncSession) -> None:
    """Manual creation leaves the MISMO core fields empty (nullable)."""
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    borrower = await _borrower(db_session, lf)
    await db_session.flush()
    assert lf.note_amount is None and lf.application_received_date is None
    assert borrower.dependent_count is None and borrower.declarations is None


# --------------------------------------------------------------------------- #
# CHECK constraint + flexible strings
# --------------------------------------------------------------------------- #


async def test_mismo_import_status_check_rejects_invalid(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO mismo_imports (id, loan_file_id, source_format, status, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :lf, 'xml', 'not_a_status', now(), now())"
            ),
            {"lf": lf.id},
        )
        await db_session.flush()


async def test_flexible_category_strings_accept_mismo_values(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    lf = await _file(db_session, company)
    borrower = await _borrower(db_session, lf)
    # Arbitrary (large/evolving) MISMO category values are accepted (no CHECK).
    db_session.add(StatedIncomeItem(borrower_id=borrower.id, income_type="MilitaryBasePay"))
    db_session.add(StatedLiability(loan_file_id=lf.id, liability_type="HELOC"))
    db_session.add(StatedAsset(loan_file_id=lf.id, asset_type="BridgeLoanNotDeposited"))
    await db_session.flush()  # no CHECK violation
