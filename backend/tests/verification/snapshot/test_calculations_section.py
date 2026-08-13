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
from app.verification.ltv import delivered_percent
from app.verification.snapshot import calculations_section as cs
from app.verification.snapshot.calculations_section import (
    _calc_confidence,
    _gate_reason,
    build_calculations_section,
    map_dti,
    map_ltv,
    map_mi,
    map_reserves,
)
from app.verification.snapshot.model import (
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
)
from sqlalchemy.ext.asyncio import AsyncSession

_UNSET = object()


def _line(
    key: str,
    label: str,
    amount: Decimal | None,
    source: str,
    overridden: bool = False,
    auto_amount: Decimal | None | object = _UNSET,
) -> NS:
    # auto_amount defaults to the effective amount (a "known" input); pass None explicitly for an
    # UNKNOWN input (the calculator couldn't derive it → LP-318 gates on this).
    auto = amount if auto_amount is _UNSET else auto_amount
    return NS(
        key=key,
        label=label,
        amount=amount,
        auto_amount=auto,
        source=source,
        overridden=overridden,
    )


def _dti(back_end: Decimal | None = Decimal("43.10")) -> NS:
    # A COMPLETE, fully-tagged file: the required housing inputs (taxes + insurance) are present, so
    # the DTI is NOT gated. Uses the real housing keys the calculator emits (so from_tag resolves).
    return NS(
        front_end_dti=Decimal("28.00"),
        back_end_dti=back_end,
        gross_monthly_income=Decimal("6000.00"),
        housing_payment=Decimal("1680.00"),
        monthly_debts=Decimal("900.00"),
        total_monthly_obligations=Decimal("2580.00"),
        income_items=[_line("income.1", "Base", Decimal("6000.00"), "stated")],
        housing_items=[
            _line("housing.principal_interest", "P&I", Decimal("1380.00"), "computed"),
            _line("housing.taxes", "Tax", Decimal("300.00"), "extracted"),
            _line("housing.insurance", "Insurance", Decimal("120.00"), "extracted"),
        ],
        debt_items=[_line("debt.1", "Card", Decimal("900.00"), "stated", overridden=True)],
    )


def _ltv(ratio: Decimal | None = Decimal("80.00")) -> NS:
    # LP-496 — the calculation now carries BOTH the exact ratio and B2-1.2-01's delivered whole
    # percent, so the stub must too. `delivered_percent` is used rather than a literal: a stub that
    # hard-coded the rounding would keep passing if the real rule changed.
    delivered = delivered_percent(ratio)
    return NS(
        ltv=ratio,
        cltv=ratio,
        hcltv=ratio,
        ltv_delivered=delivered,
        cltv_delivered=delivered,
        hcltv_delivered=delivered,
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
    assert entry.gated is False  # complete file → not gated
    # every line preserved (1 income + 3 housing + 1 debt), tags passed through verbatim
    assert len(entry.breakdown) == 5
    assert [line.source for line in entry.breakdown] == [
        "stated",
        "computed",
        "extracted",
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
    # LP-318 fail-closed on REAL data: the seed has no hazard binder / tax figure, so the required
    # housing inputs are unknown → the DTI is PRESENT but GATED (ratio nulled, reason names the tag),
    # NOT a confident too-low number. The other three still map to present entries.
    assert section.dti is not None
    assert section.dti.gated is True
    assert section.dti.value["back_end_dti"] is None
    assert "housing.insurance_monthly" in (section.dti.gate_reason or "")
    assert section.dti.breakdown  # income + housing + debt lines
    # DTI's income line is fed from STATED income → tagged stated (transparency) + traced to its tag.
    income_lines = [line for line in section.dti.breakdown if line.key.startswith("income")]
    assert {line.source for line in income_lines} == {"stated"}
    assert {line.from_tag for line in income_lines} == {"income.qualifying_monthly"}
    assert section.ltv is not None and section.mi is not None and section.reserves is not None
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


# --------------------------------------------------------------------------- #
# LP-318 — from_tag lineage, confidence propagation, fail-closed gating
# --------------------------------------------------------------------------- #


def _from_tags(entry: CalculationEntry) -> dict[str, str | None]:
    return {line.key: line.from_tag for line in entry.breakdown}


def test_dti_lines_carry_from_tag_lineage() -> None:
    entry = map_dti(_dti())
    assert entry is not None
    tags = _from_tags(entry)
    assert tags["income.1"] == "income.qualifying_monthly"
    assert tags["housing.principal_interest"] == "housing.pi"
    assert tags["housing.taxes"] == "housing.taxes_monthly"
    assert tags["housing.insurance"] == "housing.insurance_monthly"
    assert tags["debt.1"] == "liab.dti_payment"


def test_ltv_mi_reserves_lines_carry_from_tag() -> None:
    ltv = map_ltv(_ltv())
    assert ltv is not None and _from_tags(ltv)["ltv.first"] is not None
    # A key with no fact-tag behind it is honestly "derived" — never a fabricated tag id.
    ltv_full = map_ltv(
        NS(
            **{
                **_ltv().__dict__,
                "loan_items": [_line("ltv.first_loan", "First", Decimal("1000"), "stated")],
                "value_items": [
                    _line("ltv.appraised_value", "Appraised", Decimal("2000"), "manual"),
                    _line("ltv.unmapped", "Computed subtotal", Decimal("1"), "computed"),
                ],
            }
        )
    )
    assert ltv_full is not None
    ltv_tags = _from_tags(ltv_full)
    assert ltv_tags["ltv.first_loan"] == "loan.amount"
    assert ltv_tags["ltv.appraised_value"] == "property.appraised_value"
    assert ltv_tags["ltv.unmapped"] == "derived"  # honest, not fabricated

    mi = map_mi(
        NS(
            **{
                **_mi().__dict__,
                "inputs": [
                    _line("mi.base_loan_amount", "Base loan", Decimal("400000"), "stated"),
                    _line("mi.pmi_rate_bps", "PMI rate", Decimal("55"), "extracted"),
                ],
            }
        )
    )
    mi_tags = _from_tags(mi)
    assert mi_tags["mi.base_loan_amount"] == "loan.amount"
    assert mi_tags["mi.pmi_rate_bps"] == "mi.factor"

    reserves = map_reserves(
        NS(
            **{
                **_reserves().__dict__,
                "inputs": [
                    _line("reserves.liquid_assets", "Liquid", Decimal("40000"), "stated"),
                    _line("reserves.down_payment", "Down payment", Decimal("100000"), "computed"),
                ],
            }
        )
    )
    assert reserves is not None
    res_tags = _from_tags(reserves)
    assert res_tags["reserves.liquid_assets"] == "asset.usable_value"
    assert res_tags["reserves.down_payment"] == "derived"


def test_fully_tagged_calc_is_not_gated_and_has_no_confidence_floor() -> None:
    # All inputs are parsed/extracted/computed passthroughs (no AI confidence) → confidence None
    # (the LP-315 convention: passthroughs are ignored in the min). Not gated.
    entry = map_dti(_dti())
    assert entry is not None
    assert entry.gated is False and entry.gate_reason is None
    assert entry.confidence is None


def test_dti_gated_when_insurance_unknown() -> None:
    # LF-6T3N: no hazard binder → the insurance line is UNKNOWN (auto None) → the DTI is gated:
    # the ratio is nulled + the reason names the tag, NOT a confident too-low number.
    dti = _dti()
    dti.housing_items = [
        _line("housing.principal_interest", "P&I", Decimal("1380.00"), "computed"),
        _line("housing.taxes", "Tax", Decimal("300.00"), "extracted"),
        _line("housing.insurance", "Insurance", Decimal("0.00"), "extracted", auto_amount=None),
    ]
    entry = map_dti(dti)
    assert entry is not None
    assert entry.gated is True
    assert entry.value["back_end_dti"] is None  # not a confident number
    assert entry.value["front_end_dti"] is None
    assert "housing.insurance_monthly is unknown" in (entry.gate_reason or "")
    # the unknown line surfaces amount=None (honest — the "absent≠0" trap), not a fabricated 0.
    insurance = next(x for x in entry.breakdown if x.key == "housing.insurance")
    assert insurance.amount is None
    assert insurance.from_tag == "housing.insurance_monthly"


def test_dti_gated_when_required_tag_absent_with_distinct_reason() -> None:
    # A required feeding tag with NO breakdown line at all → gated with an "absent" reason,
    # distinct from "unknown".
    dti = _dti()
    dti.housing_items = [_line("housing.principal_interest", "P&I", Decimal("1380.00"), "computed")]
    entry = map_dti(dti)
    assert entry is not None
    assert entry.gated is True
    reason = entry.gate_reason or ""
    assert "housing.insurance_monthly is absent" in reason
    assert "housing.taxes_monthly is absent" in reason


def test_an_overridden_missing_input_is_not_unknown() -> None:
    # A processor override supplies the number even when auto couldn't derive it → NOT unknown,
    # NOT gated (a human vouched for it).
    dti = _dti()
    dti.housing_items = [
        _line("housing.principal_interest", "P&I", Decimal("1380.00"), "computed"),
        _line("housing.taxes", "Tax", Decimal("300.00"), "extracted"),
        _line(
            "housing.insurance",
            "Insurance",
            Decimal("150.00"),
            "override",
            overridden=True,
            auto_amount=None,
        ),
    ]
    entry = map_dti(dti)
    assert entry is not None
    assert entry.gated is False
    assert entry.value["back_end_dti"] == "43.10"


def test_calc_confidence_is_min_of_feeding_tag_confidences() -> None:
    # The propagation MECHANISM: given materialized feeding-tag confidences, calc_confidence is
    # their min (ignoring parsed/derived passthroughs, which return None). Dormant in production
    # today (all inputs are passthroughs → None), it activates when AI-confidence tags are wired.
    lines = [
        CalcBreakdownLine(
            key="a", label="A", amount="1", source="stated", from_tag="income.qualifying_monthly"
        ),
        CalcBreakdownLine(key="b", label="B", amount="2", source="computed", from_tag="housing.pi"),
        CalcBreakdownLine(
            key="c", label="C", amount="3", source="extracted", from_tag="liab.dti_payment"
        ),
    ]
    confidences = {
        "income.qualifying_monthly": 0.9,
        "liab.dti_payment": 0.4,
    }  # housing.pi passthrough → None

    def lookup(tag: str) -> float | None:
        return confidences.get(tag)

    assert _calc_confidence(lines, lookup) == 0.4  # min of the non-None feeding confidences
    assert _calc_confidence(lines, lambda _t: None) is None  # all passthroughs → None


def test_gate_reason_checks_every_line_of_a_multi_line_required_tag() -> None:
    # A required tag fed by SEVERAL breakdown lines must gate if ANY of them is unknown — the gate
    # must not last-wins-collapse the lines and only inspect the last (LP-318 review).
    tag = "income.qualifying_monthly"
    known = CalcBreakdownLine(key="a", label="A", amount="6000", source="stated", from_tag=tag)
    unknown = CalcBreakdownLine(key="b", label="B", amount=None, source="stated", from_tag=tag)

    # Unknown line first, known line last → last-wins would have wrongly passed.
    reason = _gate_reason([unknown, known], frozenset({tag}))
    assert reason is not None and f"{tag} is unknown" in reason
    # All lines known → not gated.
    assert _gate_reason([known], frozenset({tag})) is None
    # No line for the required tag at all → absent.
    absent = _gate_reason([], frozenset({tag}))
    assert absent is not None and f"{tag} is absent" in absent


def test_max_loan_and_self_employed_are_not_in_the_snapshot() -> None:
    # LP-318 scope: only the 4 in-snapshot calcs are tagged. max_loan / self_employed are API-only
    # (no snapshot consumer) → deliberately NOT surfaced here; tagging them would be dead lineage.
    assert set(CalculationsSection.model_fields) >= {"dti", "ltv", "mi", "reserves"}
    assert "max_loan" not in CalculationsSection.model_fields
    assert "self_employed" not in CalculationsSection.model_fields
