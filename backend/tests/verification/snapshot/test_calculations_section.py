"""Calculations section assembler (LP-207).

Mapper units use lightweight stand-ins for the calculator return shapes (the mapper
reads attributes only). The assembler test mocks the four calculator entry points
(invoke-not-reimplement). A DB-backed test runs the real calculators end to end.
"""

from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.models.loan_file import LoanFile
from app.verification.snapshot import calculations_section as cs
from app.verification.snapshot.calculations_section import (
    build_calculations_section,
    map_dti,
    map_ltv,
    map_mi,
    map_reserves,
)
from app.verification.snapshot.model import CalculationEntry, CalculationsSection
from sqlalchemy.ext.asyncio import AsyncSession


def _line(
    key: str, label: str, amount: Decimal | None, source: str, overridden: bool = False
) -> NS:
    return NS(key=key, label=label, amount=amount, source=source, overridden=overridden)


def _dti(back_end: Decimal | None = Decimal("43.10")) -> NS:
    return NS(
        front_end_dti=Decimal("28.00"),
        back_end_dti=back_end,
        gross_monthly_income=Decimal("6000.00"),
        housing_payment=Decimal("1680.00"),
        monthly_debts=Decimal("900.00"),
        total_monthly_obligations=Decimal("2580.00"),
        income_items=[_line("income.1", "Base", Decimal("6000.00"), "stated")],
        housing_items=[
            _line("housing.pi", "P&I", Decimal("1380.00"), "computed"),
            _line("housing.tax", "Tax", Decimal("300.00"), "extracted"),
        ],
        debt_items=[_line("debt.1", "Card", Decimal("900.00"), "stated", overridden=True)],
    )


def _ltv(ratio: Decimal | None = Decimal("80.00")) -> NS:
    return NS(
        ltv=ratio,
        cltv=ratio,
        hcltv=ratio,
        value_basis=Decimal("1450000.00"),
        value_basis_label="lesser of (purchase price, appraised value)",
        appraised_value_source="valuation_amount",
        purpose="purchase",
        program="conventional",
        loan_items=[_line("ltv.first", "First mortgage", Decimal("1160000.00"), "stated")],
        value_items=[_line("ltv.appraised", "Appraised value", Decimal("1450000.00"), "manual")],
    )


def _mi(required: bool = True) -> NS:
    result = NS(
        program="conventional",
        required=required,
        monthly_premium=Decimal("125.00") if required else None,
        annual_rate_bps=Decimal("55"),
        upfront_premium=None,
        cancel_ltv=Decimal("78"),
        duration_label=None,
    )
    return NS(
        result=result, inputs=[_line("mi.base", "Base loan", Decimal("1160000.00"), "stated")]
    )


def _reserves(*, computed: bool = True) -> NS:
    return NS(
        computed=computed,
        headline="12 months" if computed else "—",
        status="sufficient" if computed else None,
        program="conventional",
        inputs=[
            _line("reserves.liquid", "Liquid assets", Decimal("40000.00"), "stated"),
            _line("reserves.down", "Down payment", Decimal("290000.00"), "computed"),
        ],
    )


# --------------------------------------------------------------------------- #
# Mapping: value + full breakdown + source pass-through
# --------------------------------------------------------------------------- #


def test_dti_maps_value_and_full_breakdown_with_source_tags() -> None:
    entry = map_dti(_dti())
    assert entry is not None
    assert entry.value["back_end_dti"] == "43.10"
    # every line preserved (1 income + 2 housing + 1 debt), tags passed through verbatim
    assert len(entry.breakdown) == 4
    assert [line.source for line in entry.breakdown] == [
        "stated",
        "computed",
        "extracted",
        "stated",
    ]
    assert entry.breakdown[-1].overridden is True


def test_source_tags_are_passed_through_not_re_derived() -> None:
    """An 'override' tag (a 5th value beyond stated/extracted/computed/manual) survives."""
    dti = _dti()
    dti.income_items = [_line("income.1", "Base", Decimal("6000"), "override")]
    entry = map_dti(dti)
    assert entry is not None
    assert entry.breakdown[0].source == "override"  # not coerced


def test_ltv_surfaces_value_basis_and_breakdown() -> None:
    entry = map_ltv(_ltv())
    assert entry is not None
    assert entry.value["ltv"] == "80.00"
    assert entry.value["value_basis"] == "1450000.00"
    assert entry.value["appraised_value_source"] == "valuation_amount"
    assert len(entry.breakdown) == 2


def test_mi_always_present_even_when_not_required() -> None:
    entry = map_mi(_mi(required=False))
    assert entry is not None  # MI is a computed answer, never None
    assert entry.value["required"] is False
    assert entry.value["monthly_premium"] is None  # honest null, not a fabricated 0


def test_reserves_maps_headline_status_and_inputs() -> None:
    entry = map_reserves(_reserves())
    assert entry is not None
    assert entry.value["headline"] == "12 months"
    assert entry.value["status"] == "sufficient"
    assert {line.source for line in entry.breakdown} == {"stated", "computed"}


# --------------------------------------------------------------------------- #
# Not-computed = None (never a fabricated 0.0)
# --------------------------------------------------------------------------- #


def test_dti_not_computed_is_none() -> None:
    assert map_dti(_dti(back_end=None)) is None


def test_ltv_none_ratio_maps_to_none_not_zero() -> None:
    assert map_ltv(_ltv(ratio=None)) is None


def test_reserves_not_computed_maps_to_none() -> None:
    """Branches on the structured `computed` flag, not the display headline string."""
    assert map_reserves(_reserves(computed=False)) is None


# --------------------------------------------------------------------------- #
# Money precision
# --------------------------------------------------------------------------- #


def test_decimal_money_is_stringified_not_floated() -> None:
    dti = _dti(back_end=Decimal("43.10"))
    entry = map_dti(dti)
    assert entry is not None
    assert entry.value["back_end_dti"] == "43.10"  # exact string, not 43.1
    assert isinstance(entry.value["back_end_dti"], str)
    assert entry.breakdown[0].amount == "6000.00"


# --------------------------------------------------------------------------- #
# Assembler: invoke the real entry points (no reimplemented math)
# --------------------------------------------------------------------------- #


async def test_assembler_invokes_the_four_calculators() -> None:
    db = AsyncMock(spec=AsyncSession)
    loan_file = NS(id=uuid4())
    with (
        patch.object(cs, "build_dti_calculation", AsyncMock(return_value=_dti())) as m_dti,
        patch.object(cs, "build_ltv_calculation", AsyncMock(return_value=_ltv())) as m_ltv,
        patch.object(cs, "compute_loan_mi", AsyncMock(return_value=_mi())) as m_mi,
        patch.object(cs, "build_reserves_view", AsyncMock(return_value=_reserves())) as m_res,
    ):
        section = await build_calculations_section(db, loan_file)  # type: ignore[arg-type]

    m_dti.assert_awaited_once()
    m_ltv.assert_awaited_once()
    m_mi.assert_awaited_once()
    m_res.assert_awaited_once()
    assert isinstance(section, CalculationsSection)
    assert section.is_present
    assert isinstance(section.dti, CalculationEntry)
    assert section.dti.value["back_end_dti"] == "43.10"
    assert isinstance(section.ltv, CalculationEntry)
    assert isinstance(section.mi, CalculationEntry)
    assert isinstance(section.reserves, CalculationEntry)


async def test_assembler_maps_ltv_none_through() -> None:
    db = AsyncMock(spec=AsyncSession)
    loan_file = NS(id=uuid4())
    with (
        patch.object(cs, "build_dti_calculation", AsyncMock(return_value=_dti())),
        patch.object(cs, "build_ltv_calculation", AsyncMock(return_value=_ltv(ratio=None))),
        patch.object(cs, "compute_loan_mi", AsyncMock(return_value=_mi())),
        patch.object(cs, "build_reserves_view", AsyncMock(return_value=_reserves())),
    ):
        section = await build_calculations_section(db, loan_file)  # type: ignore[arg-type]
    assert section.ltv is None  # not-computed, not a fabricated entry


# --------------------------------------------------------------------------- #
# DB-backed: the real calculators run end to end
# --------------------------------------------------------------------------- #


async def _seed_loan_file(
    db: AsyncSession, *, with_property: bool, with_loan_terms: bool = True
) -> LoanFile:
    from app.models import Borrower, Company
    from app.models.lender import LoanProgram
    from app.models.loan_file import LoanPurpose
    from app.models.property import Property
    from app.models.stated_financials import StatedAsset, StatedIncomeItem, StatedLiability
    from app.services.loan_files import create_loan_file

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    lf.loan_program = LoanProgram.CONVENTIONAL
    lf.loan_purpose = LoanPurpose.PURCHASE if with_property else LoanPurpose.REFINANCE
    if with_loan_terms:  # without loan amount/rate there is no P&I → no PITI divisor
        lf.loan_amount = Decimal("400000.00")
        lf.note_amount = Decimal("400000.00")
        lf.note_rate_percent = Decimal("6.5000")
        lf.amortization_months = 360
    borrower = Borrower(
        loan_file_id=lf.id,
        first_name="Akash",
        last_name="Patel",
        is_primary=True,
        borrower_position=1,
    )
    db.add(borrower)
    await db.flush()
    db.add(
        StatedIncomeItem(
            borrower_id=borrower.id, monthly_amount=Decimal("9000.00"), income_type="Base"
        )
    )
    db.add(
        StatedLiability(
            loan_file_id=lf.id, liability_type="Installment", monthly_payment=Decimal("500.00")
        )
    )
    db.add(StatedAsset(loan_file_id=lf.id, asset_type="CheckingAccount", value=Decimal("60000.00")))
    if with_property:
        db.add(
            Property(
                loan_file_id=lf.id,
                purchase_price=Decimal("500000.00"),
                estimated_value=Decimal("500000.00"),
            )
        )
    await db.flush()
    return lf


async def test_db_backed_all_four_calculators_map(db_session: AsyncSession) -> None:
    lf = await _seed_loan_file(db_session, with_property=True)
    section = await build_calculations_section(db_session, lf)
    assert section.dti is not None and section.dti.value["back_end_dti"] is not None
    assert section.dti.breakdown  # income + housing + debt lines
    # DTI's income line is fed from STATED income → tagged stated (transparency).
    income_sources = {
        line.source for line in section.dti.breakdown if line.key.startswith("income")
    }
    assert income_sources == {"stated"}
    assert section.ltv is not None and section.ltv.value["ltv"] is not None
    assert section.mi is not None  # MI always present
    assert section.reserves is not None


async def test_db_backed_ltv_none_when_no_value_basis(db_session: AsyncSession) -> None:
    """A refinance with no property valuation → LTV can't compute → None (not 0)."""
    lf = await _seed_loan_file(db_session, with_property=False)
    section = await build_calculations_section(db_session, lf)
    assert section.ltv is None


async def test_db_backed_reserves_none_when_no_piti(db_session: AsyncSession) -> None:
    """No loan amount/rate → no P&I → no PITI divisor → reserves not computable → None.

    Drives the REAL build_reserves_view (its ``computed`` flag), so the not-computed
    coupling is exercised end-to-end, not against a hardcoded placeholder string.
    """
    lf = await _seed_loan_file(db_session, with_property=True, with_loan_terms=False)
    section = await build_calculations_section(db_session, lf)
    assert section.reserves is None
