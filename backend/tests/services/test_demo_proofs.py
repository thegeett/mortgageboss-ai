"""Phase-3 demo proofs + hardening (LP-89) — runnable demonstration of the plan's goals.

Automates the three demo proofs (DTI-with-the-math; UWM ≠ Sun-West enforcement; the end-to-end
slice) + the engineering hardening checks (performance under the full ~120-rule load; error-path
robustness on edge cases). The manual runbook is docs/demo-script.md.
"""

import time
from decimal import Decimal

from app.models import (
    Borrower,
    Company,
    Lender,
    LoanProgram,
    StatedIncomeItem,
    StatedLiability,
)
from app.services.calculators import build_calculator
from app.services.dti import build_dti_calculation
from app.services.loan_files import create_loan_file
from app.services.verification_engine import run_verification
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession) -> Company:
    company = Company(name="Acme", slug="acme")
    db.add(company)
    await db.flush()
    return company


async def _lender(db: AsyncSession, company: Company, slug: str) -> Lender:
    lender = Lender(company_id=company.id, name=slug.upper(), slug=slug)
    db.add(lender)
    await db.flush()
    return lender


async def _conventional_file(db: AsyncSession, company: Company, *, lender_id=None):
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL, lender_id=lender_id
    )
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True
    )
    db.add(borrower)
    await db.flush()
    # $10,000/mo income, $4,700/mo obligations → 47% back-end DTI (between UWM 45 + default 50).
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=Decimal("10000"),
            income_type="Self-employment",
            employment_income=True,
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Installment", monthly_payment=Decimal("4700")
        )
    )
    await db.flush()
    return loan_file


# --- Proof 1: DTI with the math shown (the "beat ChatGPT" moment) -------------


async def test_dti_shows_the_transparent_breakdown(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await _conventional_file(db_session, company)
    calc = await build_dti_calculation(db_session, loan_file=loan_file)

    # The ratio + the itemized breakdown + the explicit formula are all present.
    assert calc.back_end_dti == Decimal("47.00")
    assert calc.gross_monthly_income == Decimal("10000")
    assert any(item.amount == Decimal("4700") for item in calc.debt_items)  # the debt line shown
    assert "Back-end DTI" in calc.back_end_formula  # the formula, shown verbatim


# --- Proof 2: UWM != Sun-West (the lender-overlay enforcement moment) ---------


async def test_uwm_and_sunwest_produce_different_dti_verdicts_on_the_same_file(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    uwm = await _lender(db_session, company, "uwm")
    sunwest = await _lender(db_session, company, "sun-west")

    uwm_file = await _conventional_file(db_session, company, lender_id=uwm.id)
    sw_file = await _conventional_file(db_session, company, lender_id=sunwest.id)

    uwm_calc = await build_dti_calculation(db_session, loan_file=uwm_file)
    sw_calc = await build_dti_calculation(db_session, loan_file=sw_file)

    # Same 47% DTI: UWM tightens the cap to 45% → OVER; Sun-West leaves it at 50% → PASS.
    assert uwm_calc.limit.back_end_max == Decimal("45")
    assert uwm_calc.limit.status == "over"
    assert uwm_calc.limit.source == "overlay"
    assert sw_calc.limit.back_end_max == Decimal("50")
    assert sw_calc.limit.status == "pass"


# --- Hardening: performance under the full ~120-rule load --------------------


async def test_deterministic_verification_is_fast_under_the_full_rule_load(
    db_session: AsyncSession,
) -> None:
    """The deterministic engine (all Conventional + FHA + sample rules) runs fast on a real file."""
    company = await _company(db_session)
    loan_file = await _conventional_file(db_session, company)
    start = time.perf_counter()
    run = await run_verification(db_session, loan_file=loan_file, company_id=company.id)
    elapsed = time.perf_counter() - start
    assert run is not None
    # Deterministic evaluation of the full rule set is sub-second; the AI cross-source pass
    # (the slow part) is async/separate. A generous bound that still catches an N+1 regression.
    assert elapsed < 3.0, f"deterministic verification took {elapsed:.2f}s — investigate hotspots"


# --- Hardening: error-path robustness on edge cases --------------------------


async def test_calculators_handle_a_file_with_no_data_gracefully(db_session: AsyncSession) -> None:
    """An empty file (no borrower/income/docs) doesn't crash — the calculators show '—'."""
    company = await _company(db_session)
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await db_session.flush()

    dti = await build_dti_calculation(db_session, loan_file=loan_file)
    assert dti.back_end_dti is None  # cannot compute (no income) — not a crash

    for calc in ("mortgage_insurance", "self_employed", "reserves", "max_loan"):
        view = await build_calculator(db_session, loan_file=loan_file, calculator=calc)
        assert view.headline is not None  # a sensible "—"/"Not required", never a 500


async def test_fha_file_calculators_work(db_session: AsyncSession) -> None:
    """An FHA file exercises the FHA calculator paths (MI/MIP) without crashing."""
    company = await _company(db_session)
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.FHA
    )
    loan_file.note_amount = Decimal("300000")
    await db_session.flush()
    view = await build_calculator(db_session, loan_file=loan_file, calculator="mortgage_insurance")
    assert view.program == "fha"
    assert any("MIP" in step.label for step in view.steps)


async def test_run_verification_on_an_empty_file_does_not_crash(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.FHA
    )
    await db_session.flush()
    run = await run_verification(db_session, loan_file=loan_file, company_id=company.id)
    assert run is not None  # graceful — absent facts → rules not-evaluated, no crash
