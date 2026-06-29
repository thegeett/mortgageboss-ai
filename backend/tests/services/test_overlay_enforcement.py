"""Overlay enforcement at the calculator layer (LP-80) — the effective limit.

Proves the DTI/LTV calculators (LP-76/77) reflect the starter UWM / Sun-West
overlays in their EFFECTIVE limit (via LP-74's resolution + LP-80's content), and
the headline: the SAME file flags for UWM but not Sun-West. The per-file lender
binding selects the overlay; lenders are per-company. Uses the rollback db_session.
"""

from decimal import Decimal

from app.models import (
    Borrower,
    Company,
    Lender,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
)
from app.models.loan_file import LoanPurpose
from app.services.dti import build_dti_calculation
from app.services.loan_files import create_loan_file
from app.services.ltv import build_ltv_calculation
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _lender(db: AsyncSession, company: Company, *, name: str, slug: str) -> Lender:
    lender = Lender(
        company_id=company.id, name=name, slug=slug, supported_programs=["conventional"]
    )
    db.add(lender)
    await db.flush()
    return lender


async def _conv_file_at_48_pct_dti(db: AsyncSession, company: Company):
    """A Conventional file at exactly 48% back-end DTI ($4,800 debt / $10k income).

    No housing (no note) so back-end = debt / income — between UWM's 45 cap and the
    investor 50 default, the sweet spot for the enforcement proof.
    """
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    borrower = Borrower(loan_file_id=loan_file.id, first_name="Pat", last_name="B", is_primary=True)
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=Decimal("10000"),
            income_type="Base",
            employment_income=True,
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=Decimal("4800")
        )
    )
    await db.flush()
    return loan_file


# --- The effective-limit connection: the calculator reflects the overlay ------


async def test_dti_calculator_reflects_uwm_overlay(db_session: AsyncSession) -> None:
    """A UWM file shows UWM's tighter DTI limit (45), sourced from the overlay."""
    company = await _company(db_session)
    uwm = await _lender(db_session, company, name="UWM", slug="uwm")
    loan_file = await _conv_file_at_48_pct_dti(db_session, company)
    loan_file.lender_id = uwm.id
    await db_session.flush()

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.back_end_dti == Decimal("48.00")
    assert calc.limit.back_end_max == Decimal("45")
    assert calc.limit.source == "overlay"
    assert calc.limit.lender_slug == "uwm"
    assert calc.limit.status == "over"  # 48 > 45 → flagged for UWM


async def test_dti_calculator_uses_investor_default_for_sunwest(db_session: AsyncSession) -> None:
    """A Sun-West file falls through to the investor DTI default (50) — no override."""
    company = await _company(db_session)
    sunwest = await _lender(db_session, company, name="Sun-West", slug="sun-west")
    loan_file = await _conv_file_at_48_pct_dti(db_session, company)
    loan_file.lender_id = sunwest.id
    await db_session.flush()

    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    assert calc.limit.back_end_max == Decimal("50")
    assert calc.limit.source == "program_default"
    assert calc.limit.status == "pass"  # 48 <= 50 → clear for Sun-West


# --- THE ENFORCEMENT PROOF at the calculator: same file → different status -----


async def test_same_file_flags_for_uwm_not_sunwest(db_session: AsyncSession) -> None:
    """The SAME file: 'over' under UWM (45), 'pass' under Sun-West (50)."""
    company = await _company(db_session)
    uwm = await _lender(db_session, company, name="UWM", slug="uwm")
    sunwest = await _lender(db_session, company, name="Sun-West", slug="sun-west")
    loan_file = await _conv_file_at_48_pct_dti(db_session, company)

    loan_file.lender_id = uwm.id
    await db_session.flush()
    under_uwm = await build_dti_calculation(db_session, loan_file=loan_file)

    loan_file.lender_id = sunwest.id  # same file, just retarget the lender
    await db_session.flush()
    under_sunwest = await build_dti_calculation(db_session, loan_file=loan_file)

    assert under_uwm.limit.status == "over"  # UWM is stricter → flags
    assert under_sunwest.limit.status == "pass"  # Sun-West is looser → clear
    # Same observed DTI both times — only the lender (and its overlay) changed.
    assert under_uwm.back_end_dti == under_sunwest.back_end_dti == Decimal("48.00")


# --- LTV: the calculator reflects Sun-West's overlay (the other lender diff) ---


async def test_ltv_calculator_reflects_sunwest_overlay(db_session: AsyncSession) -> None:
    """A Sun-West purchase file shows Sun-West's tighter LTV cap (95); UWM uses 97."""
    company = await _company(db_session)
    uwm = await _lender(db_session, company, name="UWM", slug="uwm")
    sunwest = await _lender(db_session, company, name="Sun-West", slug="sun-west")
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    loan_file.loan_purpose = LoanPurpose.PURCHASE
    await db_session.flush()

    loan_file.lender_id = sunwest.id
    await db_session.flush()
    under_sunwest = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert under_sunwest.limit.ltv_max == Decimal("95")
    assert under_sunwest.limit.source == "overlay"
    assert under_sunwest.limit.lender_slug == "sun-west"

    loan_file.lender_id = uwm.id  # same file → UWM does not override purchase LTV
    await db_session.flush()
    under_uwm = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert under_uwm.limit.ltv_max == Decimal("97")
    assert under_uwm.limit.source == "program_default"


# --- The per-file lender binding + tenant scoping -----------------------------


async def test_no_lender_uses_defaults(db_session: AsyncSession) -> None:
    """A file with no target lender gets the investor defaults (no overlay)."""
    company = await _company(db_session)
    loan_file = await _conv_file_at_48_pct_dti(db_session, company)

    calc = await build_dti_calculation(db_session, loan_file=loan_file)
    assert calc.limit.back_end_max == Decimal("50")
    assert calc.limit.source == "program_default"


async def test_lender_binding_is_per_company(db_session: AsyncSession) -> None:
    """Each company has its own UWM lender row; both bind to the UWM overlay.

    The starter overlays are universal config keyed by slug; the lender ROW is
    per-company. A file resolves its own company's lender → the right overlay.
    """
    company_a = await _company(db_session, "company-a")
    company_b = await _company(db_session, "company-b")
    uwm_a = await _lender(db_session, company_a, name="UWM", slug="uwm")
    uwm_b = await _lender(db_session, company_b, name="UWM", slug="uwm")

    file_a = await _conv_file_at_48_pct_dti(db_session, company_a)
    file_a.lender_id = uwm_a.id
    file_b = await _conv_file_at_48_pct_dti(db_session, company_b)
    file_b.lender_id = uwm_b.id
    await db_session.flush()

    calc_a = await build_dti_calculation(db_session, loan_file=file_a)
    calc_b = await build_dti_calculation(db_session, loan_file=file_b)
    assert calc_a.limit.lender_slug == calc_b.limit.lender_slug == "uwm"
    assert calc_a.limit.back_end_max == calc_b.limit.back_end_max == Decimal("45")
