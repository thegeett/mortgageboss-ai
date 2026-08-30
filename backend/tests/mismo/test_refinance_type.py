"""LP-99 — parse refinance_type (cash-out vs. rate/term) from MISMO.

The bug: refinance_type was never parsed from the import, so a cash-out refi landed NULL → the LTV
silently defaulted it to rate/term → the LOOSER limit (the dangerous permissive direction). The
fix parses MISMO's ``REFINANCE/RefinanceCashOutDeterminationType`` (+ the cash-out amount as a
fallback) and populates refinance_type so the LTV's existing correct cash-out path auto-triggers.
An undetermined refi is SURFACED (a needs item + a parse warning), never silently defaulted looser.
"""

from uuid import UUID

from app.mismo.import_service import create_loan_file_from_mismo
from app.mismo.parser import parse_mismo
from app.mismo.schema import WarningSubject
from app.models import Company, NeedsItem
from app.models.loan_file import LoanPurpose, RefinanceType
from app.services.ltv import LtvPurpose, build_ltv_calculation, ltv_purpose_for
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.mismo import synthetic


async def _company(db: AsyncSession, slug: str = "acme") -> Company:
    company = Company(name=slug.title(), slug=slug)
    db.add(company)
    await db.flush()
    return company


async def _import(db: AsyncSession, company: Company, raw: bytes):
    parsed = parse_mismo(raw)
    return await create_loan_file_from_mismo(
        db, parsed=parsed, company_id=company.id, raw_content=raw
    ), parsed


async def _needs(db: AsyncSession, loan_file_id: UUID) -> list[NeedsItem]:
    rows = (
        (await db.execute(select(NeedsItem).where(NeedsItem.loan_file_id == loan_file_id)))
        .scalars()
        .all()
    )
    return list(rows)


# --- Parse layer: the MISMO cash-out determination → the ParsedLoan fields ----


def test_parser_reads_the_cash_out_determination() -> None:
    raw = synthetic.refinance_variant(synthetic.base_bytes(), cash_out_type="CashOut")
    parsed = parse_mismo(raw)
    assert parsed.loan is not None
    assert parsed.loan.loan_purpose == "Refinance"
    assert parsed.loan.refinance_cash_out_type == "CashOut"


# --- Cash-out refi → CASH_OUT → the STRICTER limit (the bug fixed) ------------


async def test_cash_out_refi_gets_the_stricter_limit(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    raw = synthetic.refinance_variant(synthetic.base_bytes(), cash_out_type="CashOut")
    loan_file, _ = await _import(db_session, company, raw)

    assert loan_file.loan_purpose is LoanPurpose.REFINANCE
    assert loan_file.refinance_type is RefinanceType.CASH_OUT
    # The LTV's existing correct path now auto-triggers → the STRICTER cash-out limit rule.
    assert ltv_purpose_for(loan_file) is LtvPurpose.CASH_OUT_REFINANCE
    ltv = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert ltv.limit.purpose_basis == "cash_out"
    assert ltv.limit.rule_id == "conv.ltv.cash_out_max"  # NOT the looser conv.ltv.purchase_max


async def test_cash_out_by_amount_fallback(db_session: AsyncSession) -> None:
    """No determination type, but a positive cash-out AMOUNT ⇒ cash-out (the fallback signal)."""
    company = await _company(db_session)
    raw = synthetic.refinance_variant(synthetic.base_bytes(), cash_out_amount="50000")
    loan_file, _ = await _import(db_session, company, raw)
    assert loan_file.refinance_type is RefinanceType.CASH_OUT


# --- Rate/term refi → RATE_TERM → the rate/term (shared purchase) limit -------


async def test_rate_term_refi_gets_the_rate_term_limit(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    raw = synthetic.refinance_variant(synthetic.base_bytes(), cash_out_type="NoCashOut")
    loan_file, _ = await _import(db_session, company, raw)

    assert loan_file.refinance_type is RefinanceType.RATE_TERM
    assert ltv_purpose_for(loan_file) is LtvPurpose.RATE_TERM_REFINANCE
    ltv = await build_ltv_calculation(db_session, loan_file=loan_file)
    assert ltv.limit.purpose_basis == "purchase"  # rate/term shares the purchase limit
    assert ltv.limit.rule_id == "conv.ltv.purchase_max"


async def test_limited_cash_out_maps_to_rate_term(db_session: AsyncSession) -> None:
    """MISMO LimitedCashOut = the agency LCOR = rate/term limits (grounded-starter, validate-Priya)."""
    company = await _company(db_session)
    raw = synthetic.refinance_variant(synthetic.base_bytes(), cash_out_type="LimitedCashOut")
    loan_file, _ = await _import(db_session, company, raw)
    assert loan_file.refinance_type is RefinanceType.RATE_TERM


# --- Undetermined refi → SURFACED, never silently looser ----------------------


async def test_undetermined_refi_is_surfaced_not_silently_looser(db_session: AsyncSession) -> None:
    """A refi with NO cash-out signal: refinance_type stays null + a needs item + a parse warning
    surface the ambiguity — it is NOT silently defaulted to the looser rate/term limit."""
    company = await _company(db_session)
    raw = synthetic.refinance_variant(synthetic.base_bytes())  # refinance, no cash-out signal
    loan_file, parsed = await _import(db_session, company, raw)

    assert loan_file.loan_purpose is LoanPurpose.REFINANCE
    assert loan_file.refinance_type is None  # undetermined — not guessed
    # Surfaced two ways: a parse warning + a "confirm refinance type" needs item.
    assert any("could not be determined" in w.message for w in parsed.parse_warnings)
    assert any(w.subject is WarningSubject.LOAN for w in parsed.parse_warnings)
    needs = await _needs(db_session, loan_file.id)
    assert any("Confirm refinance type" in n.title for n in needs)


# --- Purchases unaffected + the manual override still works -------------------


async def test_purchase_is_unaffected(db_session: AsyncSession) -> None:
    """The real fixture (Mahesh) is a PURCHASE → refinance_type stays NA, no confirm-need."""
    company = await _company(db_session)
    loan_file, parsed = await _import(db_session, company, synthetic.base_bytes())
    assert loan_file.loan_purpose is LoanPurpose.PURCHASE
    assert loan_file.refinance_type is None
    assert not any("refinance type" in w.message.lower() for w in parsed.parse_warnings)
    needs = await _needs(db_session, loan_file.id)
    assert not any("Confirm refinance type" in n.title for n in needs)


async def test_manual_setter_still_overrides(db_session: AsyncSession) -> None:
    """The undetermined refi's null is CORRECTABLE via the update path — LP-99 exposes
    ``refinance_type`` on ``LoanFileUpdate`` so a processor can set it on the Overview
    (the needs item directs them there). Correcting it flips the LTV to the cash-out path."""
    from app.schemas.loan_file import LoanFileUpdate
    from app.services.loan_files import update_loan_file

    company = await _company(db_session)
    raw = synthetic.refinance_variant(synthetic.base_bytes())  # undetermined
    loan_file, _ = await _import(db_session, company, raw)
    assert loan_file.refinance_type is None

    await update_loan_file(
        db_session,
        loan_file=loan_file,
        data=LoanFileUpdate(refinance_type=RefinanceType.CASH_OUT),
    )
    assert loan_file.refinance_type is RefinanceType.CASH_OUT
    assert ltv_purpose_for(loan_file) is LtvPurpose.CASH_OUT_REFINANCE


async def test_refinance_type_is_tenant_scoped(db_session: AsyncSession) -> None:
    company_a = await _company(db_session, "company-a")
    company_b = await _company(db_session, "company-b")
    file_a, _ = await _import(
        db_session,
        company_a,
        synthetic.refinance_variant(synthetic.base_bytes(), cash_out_type="CashOut"),
    )
    file_b, _ = await _import(db_session, company_b, synthetic.base_bytes())  # purchase
    assert file_a.company_id == company_a.id and file_a.refinance_type is RefinanceType.CASH_OUT
    assert file_b.company_id == company_b.id and file_b.refinance_type is None
