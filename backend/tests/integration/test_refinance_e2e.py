"""LP-101 — refinance end-to-end correctness SWEEP (completes the refi epic LP-99/100/101).

Runs the full refi path (import a refi MISMO fixture → LTV → rules/needs → the calculators) for
BOTH a rate/term and a cash-out fixture, and PROBES refi-correctness across every calculator — not
just "the import didn't crash". It asserts LP-99 (refinance_type parsed → the correct, stricter
cash-out LTV limit; appraised-value-only basis) and LP-100 (no spurious purchase-agreement rule on
a refi; the refi need-set), then probes DTI / MI / reserves / max-loan.

The sweep SURFACED two seams between the import/model and the calculators — the project's recurring
bug class — both in the CONSERVATIVE direction (they over-state risk, never make a file look more
qualified than it is):

* **GAP-2 (reserves), FIXED inline here:** the reserves down-payment default was ``value - loan``
  (home equity), wrongly subtracted from a refi's eligible reserves. A refi has no down payment →
  now 0. Asserted below.
* **GAP-1 (DTI), documented + xfail (follow-up LP-102):** the back-end DTI counts the existing
  mortgage being paid off by the refi (we don't parse the MISMO payoff indicator), double-counting
  it against the new PITI. Direction: conservative (DTI over-stated → possible spurious over-DTI).
  The ``xfail`` below asserts the DESIRED behavior so we never bake in the bug as "correct".

The fixtures are synthetic/de-identified grounded-starter test artifacts (see
``scripts/generate_refi_fixtures.py``); a real refi LOS export may differ — validate-with-Priya.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from app.mismo.import_service import create_loan_file_from_mismo
from app.mismo.parser import parse_mismo
from app.models import Company, NeedsItem
from app.models.finding import Finding
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanPurpose, RefinanceType
from app.services.calculators import build_calculator
from app.services.dti import build_dti_calculation
from app.services.ltv import build_ltv_calculation, ltv_purpose_for
from app.services.mi import compute_loan_mi
from app.services.verification_engine import run_verification
from app.verification.engine import evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.ltv import LtvPurpose
from app.verification.registry import default_registry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "mismo"
_RATE_TERM = _FIXTURES / "refi_rate_term.xml"
_CASH_OUT = _FIXTURES / "refi_cash_out.xml"
_VALUATION = Decimal("1380000.00")  # the fixtures' appraised/valuation amount (no sales contract)


async def _import(db: AsyncSession, path: Path, slug: str) -> LoanFile:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    raw = path.read_bytes()
    return await create_loan_file_from_mismo(
        db, parsed=parse_mismo(raw), company_id=company.id, raw_content=raw
    )


async def _needs_types(db: AsyncSession, loan_file: LoanFile) -> set[str]:
    # The import already seeds the floor needs (seed_floor_needs runs during creation and is
    # idempotent), so read the seeded rows rather than re-seeding (which would return []).
    rows = await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file.id))
    return {n.needs_type for n in rows.scalars().all() if n.needs_type is not None}


async def _findings(db: AsyncSession, loan_file_id) -> list[Finding]:
    rows = await db.execute(select(Finding).where(Finding.loan_file_id == loan_file_id))
    return list(rows.scalars().all())


# --------------------------------------------------------------------------- #
# IMPORT — the refi MISMO imports cleanly (LP-99)
# --------------------------------------------------------------------------- #


async def test_rate_term_imports_as_rate_term_refi(db_session: AsyncSession) -> None:
    lf = await _import(db_session, _RATE_TERM, "rt")
    assert lf.loan_purpose is LoanPurpose.REFINANCE
    assert lf.refinance_type is RefinanceType.RATE_TERM  # LP-99: NoCashOut → RATE_TERM
    assert lf.loan_program is LoanProgram.CONVENTIONAL
    assert lf.loan_amount == Decimal("1104000.00")


async def test_cash_out_imports_as_cash_out_refi(db_session: AsyncSession) -> None:
    lf = await _import(db_session, _CASH_OUT, "co")
    assert lf.loan_purpose is LoanPurpose.REFINANCE
    assert lf.refinance_type is RefinanceType.CASH_OUT  # LP-99: CashOut → CASH_OUT
    assert lf.loan_amount == Decimal("1173000.00")


# --------------------------------------------------------------------------- #
# LTV — appraised-value-only basis; the cash-out fixture gets the STRICTER limit (LP-99)
# --------------------------------------------------------------------------- #


async def test_rate_term_ltv_appraised_basis_and_rate_term_limit(db_session: AsyncSession) -> None:
    lf = await _import(db_session, _RATE_TERM, "rt")
    assert ltv_purpose_for(lf) is LtvPurpose.RATE_TERM_REFINANCE
    ltv = await build_ltv_calculation(db_session, loan_file=lf)

    # Appraised-value-only (no purchase price, no lesser-of degeneration).
    assert ltv.value_basis == _VALUATION
    assert "appraised" in ltv.value_basis_label
    assert ltv.ltv == Decimal("80.00")  # 1,104,000 / 1,380,000
    # Rate/term shares the purchase cap (97%) → passes.
    assert ltv.limit.rule_id == "conv.ltv.purchase_max"
    assert ltv.limit.purpose_basis == "purchase"
    assert ltv.limit.status == "pass"


async def test_cash_out_ltv_gets_the_stricter_cash_out_limit(db_session: AsyncSession) -> None:
    """The heart of LP-99: at 85% LTV the cash-out fixture is OVER the stricter 80% cash-out cap —
    yet it would PASS the 97% purchase cap. The populated refinance_type is what makes it bind."""
    lf = await _import(db_session, _CASH_OUT, "co")
    assert ltv_purpose_for(lf) is LtvPurpose.CASH_OUT_REFINANCE
    ltv = await build_ltv_calculation(db_session, loan_file=lf)

    assert ltv.value_basis == _VALUATION  # appraised-only
    assert ltv.ltv == Decimal("85.00")  # 1,173,000 / 1,380,000
    assert ltv.limit.rule_id == "conv.ltv.cash_out_max"  # the STRICTER limit
    assert ltv.limit.purpose_basis == "cash_out"
    assert ltv.limit.ltv_max == Decimal("80")
    assert ltv.limit.status == "over"  # 85% > 80% — flagged only because the stricter cap applied


# --------------------------------------------------------------------------- #
# RULES + NEEDS — no spurious purchase-agreement on a refi; the refi need-set (LP-100)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path,slug", [(_RATE_TERM, "rt"), (_CASH_OUT, "co")])
async def test_refi_needs_are_refi_shaped_not_purchase(
    db_session: AsyncSession, path: Path, slug: str
) -> None:
    lf = await _import(db_session, path, slug)
    types = await _needs_types(db_session, lf)
    # LP-100 refi need-set present; the purchase agreement is NOT sought on a refi.
    assert "existing_mortgage_statement" in types
    assert "payoff_statement" in types
    assert "purchase_agreement" not in types


@pytest.mark.parametrize("path,slug", [(_RATE_TERM, "rt"), (_CASH_OUT, "co")])
async def test_purchase_agreement_rule_skipped_on_refi_even_when_the_doc_fact_is_present(
    db_session: AsyncSession, path: Path, slug: str
) -> None:
    """LP-100 at the engine level, on the REAL imported file's purpose: with the purchase-agreement
    doc fact PRESENT (so it WOULD evaluate on a purchase), the rule is skipped on a refi — while a
    DTI rule still evaluates (DTI is never purpose-gated)."""
    lf = await _import(db_session, path, slug)
    facts = FileFacts(
        values={
            "documents.purchase_agreement_present": Fact(value=Decimal("1")),
            "dti.back_end_pct": Fact(value=Decimal("52")),
        }
    )
    rules = default_registry().resolve(program=lf.loan_program, lender_slug=None)
    results = evaluate(facts, rules, loan_purpose=lf.loan_purpose, refinance_type=lf.refinance_type)
    by_id = {r.rule.rule_id: r for r in results}
    assert by_id["conv.docs.purchase_agreement_present"].evaluated is False  # skipped on the refi
    assert by_id["conv.dti.back_end_max"].evaluated is True  # DTI fires regardless of purpose


async def test_full_verification_run_has_no_purchase_agreement_finding(
    db_session: AsyncSession,
) -> None:
    lf = await _import(db_session, _CASH_OUT, "co")
    await run_verification(db_session, loan_file=lf, company_id=lf.company_id)
    findings = await _findings(db_session, lf.id)
    assert findings  # the run produced findings (it ran end-to-end)
    assert all(f.rule_id != "conv.docs.purchase_agreement_present" for f in findings)


# --------------------------------------------------------------------------- #
# MI PROBE — computed on the refi (appraised-only) LTV, program-aware ✓
# --------------------------------------------------------------------------- #


async def test_mi_is_computed_on_the_refi_ltv(db_session: AsyncSession) -> None:
    # Cash-out refi at 85% LTV (Conventional) → PMI required, on the refi LTV.
    lf = await _import(db_session, _CASH_OUT, "co")
    comp = await compute_loan_mi(db_session, loan_file=lf)
    assert comp.result.ltv_pct == Decimal("85.00")  # the refi LTV, not a purchase basis
    assert comp.result.required is True  # PMI required above 80%

    # Rate/term at exactly 80% LTV → PMI not required.
    lf_rt = await _import(db_session, _RATE_TERM, "rt")
    comp_rt = await compute_loan_mi(db_session, loan_file=lf_rt)
    assert comp_rt.result.ltv_pct == Decimal("80.00")
    assert comp_rt.result.required is False


# --------------------------------------------------------------------------- #
# RESERVES PROBE — GAP-2 FIXED: a refi has no down payment (was value - loan)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path,slug", [(_RATE_TERM, "rt"), (_CASH_OUT, "co")])
async def test_reserves_refi_has_no_down_payment(
    db_session: AsyncSession, path: Path, slug: str
) -> None:
    lf = await _import(db_session, path, slug)
    view = await build_calculator(db_session, loan_file=lf, calculator="reserves")
    down = next(line for line in view.inputs if line.key == "reserves.down_payment")
    # LP-101 fix: the refi down-payment auto is 0 (not the old value - loan equity, which wrongly
    # gutted eligible reserves). Direction of the OLD bug was conservative (understated reserves).
    assert down.auto_amount == Decimal("0")


# --------------------------------------------------------------------------- #
# MAX-LOAN PROBE — refi-sensible: property value is the appraised basis
# --------------------------------------------------------------------------- #


async def test_max_loan_uses_the_appraised_value_basis_for_a_refi(db_session: AsyncSession) -> None:
    lf = await _import(db_session, _CASH_OUT, "co")
    view = await build_calculator(db_session, loan_file=lf, calculator="max_loan")
    prop_value = next(line for line in view.inputs if line.key == "max_loan.property_value")
    assert prop_value.auto_amount == _VALUATION  # the appraised basis, not a purchase price
    # It computes a bounded max loan (the constraints resolve — no purchase-shaped crash).
    assert view.headline is not None


# --------------------------------------------------------------------------- #
# DTI PROBE — GAP-1 (documented, xfail): the paid-off mortgage is double-counted
# --------------------------------------------------------------------------- #


async def test_refi_dti_computes_and_includes_the_mortgage_liabilities(
    db_session: AsyncSession,
) -> None:
    """Documents the CURRENT behavior (not asserted as 'correct'): the refi DTI computes, and the
    stated mortgage liabilities ARE present in the debt items — the raw material of GAP-1."""
    lf = await _import(db_session, _CASH_OUT, "co")
    dti = await build_dti_calculation(db_session, loan_file=lf)
    assert dti.back_end_dti is not None  # it computes for a refi
    mortgage_debits = [d for d in dti.debt_items if "mortgage" in d.label.lower()]
    assert mortgage_debits  # the existing mortgage(s) are in the debt list …
    assert any(d.amount > 0 and d.key.startswith("debt.") for d in mortgage_debits)


@pytest.mark.xfail(
    reason="GAP-1 (LP-102 follow-up): the back-end DTI counts the existing first mortgage being "
    "paid off by the refinance — we don't parse the MISMO payoff indicator, so the new PITI and "
    "the old payment are BOTH counted (double-count). Direction: CONSERVATIVE (DTI over-stated). "
    "Fix needs payoff-indicator parsing + purpose-aware debt exclusion; not a safe inline change "
    "(a borrower's OTHER mortgages must still count).",
    strict=True,
)
async def test_refi_dti_excludes_the_paid_off_mortgage(db_session: AsyncSession) -> None:
    """The DESIRED behavior (currently failing → xfail): on a refinance the existing first mortgage
    on the subject is being paid off, so it must NOT be in the back-end DTI's monthly debts. We
    assert the desired state so the gap is documented without ever asserting the bug as correct."""
    lf = await _import(db_session, _CASH_OUT, "co")
    dti = await build_dti_calculation(db_session, loan_file=lf)
    # The single largest stated mortgage is the subject's existing lien being refinanced.
    mortgage_payments = [
        d.amount for d in dti.debt_items if "mortgage" in d.label.lower() and d.amount > 0
    ]
    assert mortgage_payments, "fixture should carry an existing mortgage liability"
    paid_off = max(mortgage_payments)
    # DESIRED: the paid-off mortgage's payment is not part of the refi back-end obligations.
    assert paid_off not in {d.amount for d in dti.debt_items if d.key.startswith("debt.")}


# --------------------------------------------------------------------------- #
# TENANT SCOPING + NO CROSS-FIXTURE BLEED
# --------------------------------------------------------------------------- #


async def test_refi_fixtures_are_tenant_scoped(db_session: AsyncSession) -> None:
    rt = await _import(db_session, _RATE_TERM, "tenant-a")
    co = await _import(db_session, _CASH_OUT, "tenant-b")
    assert rt.company_id != co.company_id
    assert rt.refinance_type is RefinanceType.RATE_TERM
    assert co.refinance_type is RefinanceType.CASH_OUT
