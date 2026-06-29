"""Calculator service (LP-87) — the four calculators, auto-populated, overrideable, coupled.

The DB-facing half of the four LP-87 calculators (MI/MIP, self-employed income, reserves,
max loan). It reuses the LP-76/77 pattern exactly — auto-populate from structured data +
the sibling calculators (DTI/LTV), apply the processor's persisted overrides, compute via
the pure deterministic modules, and couple to findings — and shares ONE override table
(``calculator_overrides``, calculator-discriminated) + ONE response shape
(:class:`CalculatorView`).

Consumes (does not duplicate): LP-77's LTV (MI, max-loan), LP-76's DTI (reserves' PITI,
max-loan's income/debts/ceiling), LP-84's FHA MIP rule values (the MI calc's UFMIP rate),
and the reserve / DTI / LTV rule thresholds. The calculation METHODOLOGY where it is
domain-judgment (the PMI rate, the self-employed add-backs/averaging, the required
reserves, the loan limit) is a grounded-starter (``methodology.starter=True``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.calculator_override import CalculatorOverride
from app.models.helpers import only_active
from app.models.lender import Lender, LoanProgram
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedAsset
from app.schemas.calculators import (
    CalcFindings,
    CalcLine,
    CalcOverrideInput,
    CalcStep,
    CalculatorView,
    MethodologyNote,
)
from app.services.activity_log import log_activity
from app.services.dti import build_dti_calculation
from app.services.finding_blocking import open_in_scope_findings
from app.services.ltv import build_ltv_calculation
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.max_loan import (
    DTI_CONSTRAINT_FORMULA,
    LOAN_LIMIT_FORMULA,
    LTV_CONSTRAINT_FORMULA,
    compute_max_loan,
)
from app.verification.mortgage_insurance import (
    CONVENTIONAL_PMI_FORMULA,
    FHA_ANNUAL_MIP_FORMULA,
    FHA_UFMIP_FORMULA,
    compute_conventional_pmi,
    compute_fha_mip,
)
from app.verification.registry import default_registry
from app.verification.reserves import (
    ELIGIBLE_FORMULA,
    MONTHS_FORMULA,
    compute_reserves,
)
from app.verification.self_employed import (
    ADD_BACK_KEYS,
    ADJUSTED_YEAR_FORMULA,
    QUALIFYING_INCOME_FORMULA,
    SelfEmployedYear,
    compute_self_employed_income,
)

CALCULATORS = ("mortgage_insurance", "self_employed", "reserves", "max_loan")

# Grounded-starter methodology constants (validate with Priya — these are domain judgment).
_PMI_STARTER_RATE_BPS = Decimal("55")  # a starter PMI annual rate; real rate is a credit/LTV card
_FHA_ANNUAL_MIP_STARTER_BPS = Decimal("55")  # most 30-year FHA borrowers; LP-84's rule is the cap
_FHA_MIP_DURATION_LTV = Decimal("90")  # LP-84: LTV ≤ 90% → 11yr, > 90% → life
_FHA_RETIREMENT_FACTOR = Decimal("0.60")  # LP-84's FHA 60% retirement-reserve haircut
_CONFORMING_LOAN_LIMIT = Decimal("806500")  # 2025/26 baseline FHFA conforming (starter — verify)
_STARTER_REQUIRED_RESERVE_MONTHS = Decimal("2")

# Asset-type keywords (case-insensitive) — the reserves auto-population (Tier-2 heuristics).
_RETIREMENT_KEYWORDS = ("retirement", "401", "ira", "pension")
_GIFT_KEYWORDS = ("gift", "borrow")


# --------------------------------------------------------------------------- #
# Shared override machinery (one table, calculator-discriminated)
# --------------------------------------------------------------------------- #


class _Auto:
    """An auto-populated overrideable input line (pre-override)."""

    __slots__ = ("auto", "key", "label", "source")

    def __init__(self, key: str, label: str, auto: Decimal | None, source: str) -> None:
        self.key, self.label, self.auto, self.source = key, label, auto, source


async def _active_overrides(
    db: AsyncSession, loan_file_id: UUID, calculator: str
) -> dict[str, Decimal]:
    stmt = only_active(
        select(CalculatorOverride).where(
            CalculatorOverride.loan_file_id == loan_file_id,
            CalculatorOverride.calculator == calculator,
        ),
        CalculatorOverride,
    )
    return {row.field_key: row.value for row in (await db.execute(stmt)).scalars().all()}


def _apply(
    autos: Sequence[_Auto], overrides: dict[str, Decimal]
) -> tuple[list[CalcLine], dict[str, Decimal]]:
    """Build response input lines + an effective-value map (effective = override ?? auto ?? 0)."""
    lines: list[CalcLine] = []
    effective: dict[str, Decimal] = {}
    for auto in autos:
        override = overrides.get(auto.key)
        value = override if override is not None else (auto.auto or Decimal(0))
        effective[auto.key] = value
        lines.append(
            CalcLine(
                key=auto.key,
                label=auto.label,
                auto_amount=auto.auto,
                override_amount=override,
                amount=value,
                source="override" if override is not None else auto.source,
                overridden=override is not None,
            )
        )
    return lines, effective


async def _findings(db: AsyncSession, loan_file_id: UUID, cutoff: float) -> CalcFindings:
    in_scope = await open_in_scope_findings(db, loan_file_id=loan_file_id, confidence_cutoff=cutoff)
    return CalcFindings(unresolved=len(in_scope) > 0, open_in_scope_count=len(in_scope))


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


async def _lender_slug(db: AsyncSession, loan_file: LoanFile) -> str | None:
    if loan_file.lender_id is None:
        return None
    lender = await db.get(Lender, loan_file.lender_id)
    return lender.slug if lender is not None else None


async def _sum_assets(db: AsyncSession, loan_file_id: UUID, keywords: tuple[str, ...]) -> Decimal:
    stmt = only_active(
        select(StatedAsset).where(StatedAsset.loan_file_id == loan_file_id), StatedAsset
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sum(
        (
            r.value
            for r in rows
            if r.value is not None
            and r.asset_type is not None
            and any(k in r.asset_type.lower() for k in keywords)
        ),
        Decimal(0),
    )


async def _sum_assets_excluding(
    db: AsyncSession, loan_file_id: UUID, exclude: tuple[str, ...]
) -> Decimal:
    """Liquid assets — stated assets whose type matches none of the excluded keywords."""
    stmt = only_active(
        select(StatedAsset).where(StatedAsset.loan_file_id == loan_file_id), StatedAsset
    )
    rows = (await db.execute(stmt)).scalars().all()
    return sum(
        (
            r.value
            for r in rows
            if r.value is not None
            and not (r.asset_type is not None and any(k in r.asset_type.lower() for k in exclude))
        ),
        Decimal(0),
    )


# --------------------------------------------------------------------------- #
# 1) Mortgage insurance — program-aware (PMI vs. FHA MIP consuming LP-84)
# --------------------------------------------------------------------------- #


def _fha_ufmip_rate_bps() -> Decimal:
    """The FHA UFMIP rate, CONSUMED from LP-84's ``fha.mip.ufmip_rate`` rule (175 bps)."""
    rules = default_registry().resolve(program=LoanProgram.FHA, lender_slug=None)
    rule = next((r for r in rules if r.rule_id == "fha.mip.ufmip_rate"), None)
    return rule.condition.value if rule is not None else Decimal("175")


async def build_mi_view(db: AsyncSession, *, loan_file: LoanFile, cutoff: float) -> CalculatorView:
    program = loan_file.loan_program
    base_loan_default = loan_file.note_amount or loan_file.loan_amount
    ltv_calc = await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    ltv_pct = ltv_calc.ltv

    overrides = await _active_overrides(db, loan_file.id, "mortgage_insurance")
    steps: list[CalcStep] = []
    if ltv_pct is not None:
        steps.append(CalcStep(label="LTV (from the LTV calculator)", value=f"{ltv_pct}%"))

    if program is LoanProgram.FHA:
        autos = [
            _Auto("mi.base_loan_amount", "Base loan amount", base_loan_default, "stated"),
            _Auto(
                "mi.annual_mip_rate_bps",
                "Annual MIP rate (bps)",
                _FHA_ANNUAL_MIP_STARTER_BPS,
                "manual",
            ),
        ]
        lines, eff = _apply(autos, overrides)
        ufmip_bps = _fha_ufmip_rate_bps()
        result = compute_fha_mip(
            base_loan_amount=eff["mi.base_loan_amount"],
            ltv_pct=ltv_pct,
            upfront_rate_bps=ufmip_bps,
            annual_rate_bps=eff["mi.annual_mip_rate_bps"],
            duration_threshold_ltv=_FHA_MIP_DURATION_LTV,
        )
        steps += [
            CalcStep(
                label=f"Upfront MIP ({ufmip_bps} bps, financed)",
                value=_money(result.upfront_premium),
            ),
            CalcStep(label="Monthly MIP", value=_money(result.monthly_premium), emphasis=True),
            CalcStep(label="MIP duration", value=result.duration_label or "—"),
        ]
        headline = f"{_money(result.monthly_premium)} / mo"
        methodology = MethodologyNote(
            starter=True,
            text=(
                "UFMIP (1.75%) is consumed from LP-84's fha.mip.ufmip_rate rule; the annual MIP rate is "
                "a starter (most 30-year borrowers 0.55% — LP-84's rule is the cap) and the LTV-90% "
                "duration is LP-84's rule. Validate the exact annual rate (LTV/amount/term table) with Priya."
            ),
        )
        formulas = [FHA_UFMIP_FORMULA, FHA_ANNUAL_MIP_FORMULA]
        status = "required"
    else:
        autos = [
            _Auto("mi.base_loan_amount", "Base loan amount", base_loan_default, "stated"),
            _Auto("mi.pmi_rate_bps", "Annual PMI rate (bps)", _PMI_STARTER_RATE_BPS, "manual"),
        ]
        lines, eff = _apply(autos, overrides)
        result = compute_conventional_pmi(
            base_loan_amount=eff["mi.base_loan_amount"],
            ltv_pct=ltv_pct,
            annual_rate_bps=eff["mi.pmi_rate_bps"],
        )
        steps += [
            CalcStep(label="PMI required (LTV > 80%)", value="Yes" if result.required else "No"),
            CalcStep(label="Monthly PMI", value=_money(result.monthly_premium), emphasis=True),
            CalcStep(label="Cancels at", value=f"{result.cancel_ltv}% LTV"),
        ]
        headline = f"{_money(result.monthly_premium)} / mo" if result.required else "Not required"
        methodology = MethodologyNote(
            starter=True,
            text=(
                "PMI is required above 80% LTV and terminates at 78% (HPA) — these are exact. The annual "
                "PMI rate is credit-score / LTV-driven (a rate card); the starter rate here is a "
                "placeholder to validate with Priya."
            ),
        )
        formulas = [CONVENTIONAL_PMI_FORMULA]
        status = "required" if result.required else "not_required"

    return CalculatorView(
        calculator="mortgage_insurance",
        title="Mortgage insurance",
        headline=headline,
        headline_label="Monthly premium",
        status=status,
        program=program.value if program else None,
        inputs=lines,
        steps=steps,
        formulas=formulas,
        methodology=methodology,
        findings=await _findings(db, loan_file.id, cutoff),
    )


# --------------------------------------------------------------------------- #
# 2) Self-employed income — Form-1084-grounded, feeds DTI
# --------------------------------------------------------------------------- #

_SE_YEARS = (("y2", "most recent year", 2), ("y1", "prior year", 1))
_ADD_BACK_LABELS = {
    "depreciation": "Depreciation",
    "depletion": "Depletion",
    "amortization_casualty": "Amortization / casualty loss",
    "business_use_of_home": "Business use of home",
}


async def build_self_employed_view(
    db: AsyncSession, *, loan_file: LoanFile, cutoff: float
) -> CalculatorView:
    # Starter scaffold: the qualifying figure is derived from documents (Tier-2) — auto a
    # two-year frame the processor fills/overrides. Net profit defaults to 0 (entered from
    # the returns); add-backs default 0.
    overrides = await _active_overrides(db, loan_file.id, "self_employed")
    autos: list[_Auto] = []
    for slug, label, _year in _SE_YEARS:
        autos.append(_Auto(f"se.{slug}.net_profit", f"Net profit — {label}", None, "manual"))
        for key in ADD_BACK_KEYS:
            autos.append(
                _Auto(f"se.{slug}.{key}", f"{_ADD_BACK_LABELS[key]} — {label}", None, "manual")
            )
    lines, eff = _apply(autos, overrides)

    years = [
        SelfEmployedYear(
            year=year,
            net_profit=eff[f"se.{slug}.net_profit"],
            add_backs={key: eff[f"se.{slug}.{key}"] for key in ADD_BACK_KEYS},
        )
        for slug, _label, year in _SE_YEARS
    ]
    result = compute_self_employed_income(years)

    steps: list[CalcStep] = []
    for se_year, (_slug, label, _y) in zip(reversed(result.years), _SE_YEARS, strict=False):
        steps.append(
            CalcStep(
                label=f"Adjusted income — {label} (net profit + add-backs)",
                value=_money(se_year.adjusted),
            )
        )
    steps += [
        CalcStep(
            label=f"Average annual ({result.year_count}-yr)", value=_money(result.average_annual)
        ),
        CalcStep(
            label="Qualifying monthly income → DTI",
            value=_money(result.qualifying_monthly),
            emphasis=True,
        ),
    ]
    if result.declining:
        steps.append(CalcStep(label="⚠ Declining trend", value="most-recent year < prior — review"))

    return CalculatorView(
        calculator="self_employed",
        title="Self-employed income",
        headline=f"{_money(result.qualifying_monthly)} / mo",
        headline_label="Qualifying monthly income",
        status="declining" if result.declining else None,
        program=loan_file.loan_program.value if loan_file.loan_program else None,
        inputs=lines,
        steps=steps,
        formulas=[ADJUSTED_YEAR_FORMULA, QUALIFYING_INCOME_FORMULA],
        methodology=MethodologyNote(
            starter=True,
            text=(
                "Grounded in Fannie Mae's Cash Flow Analysis (Form 1084): net profit + non-cash add-backs "
                "(depreciation/depletion/amortization/business-use-of-home), averaged across 2 years. The "
                "exact add-back set + averaging-vs-most-recent judgment is domain expertise — validate with "
                "Priya. This qualifying figure FEEDS the DTI calculator's income side (LP-76)."
            ),
        ),
        findings=await _findings(db, loan_file.id, cutoff),
    )


# --------------------------------------------------------------------------- #
# 3) Reserves — eligible (60% FHA haircut) vs. required
# --------------------------------------------------------------------------- #


async def build_reserves_view(
    db: AsyncSession, *, loan_file: LoanFile, cutoff: float
) -> CalculatorView:
    program = loan_file.loan_program
    liquid_default = await _sum_assets_excluding(
        db, loan_file.id, _RETIREMENT_KEYWORDS + _GIFT_KEYWORDS
    )
    retirement_default = await _sum_assets(db, loan_file.id, _RETIREMENT_KEYWORDS)
    excluded_default = await _sum_assets(db, loan_file.id, _GIFT_KEYWORDS)

    dti_calc = await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    piti = dti_calc.housing_payment if dti_calc.housing_payment > 0 else None
    ltv_calc = await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    value_basis = ltv_calc.value_basis
    first_loan = loan_file.note_amount or loan_file.loan_amount
    down_default = (
        value_basis - first_loan if value_basis is not None and first_loan is not None else None
    )

    factor = _FHA_RETIREMENT_FACTOR if program is LoanProgram.FHA else Decimal("1.00")
    required_months = _resolve_required_reserve_months(program, await _lender_slug(db, loan_file))

    overrides = await _active_overrides(db, loan_file.id, "reserves")
    autos = [
        _Auto(
            "reserves.liquid_assets",
            "Liquid assets (checking/savings/etc.)",
            liquid_default,
            "stated",
        ),
        _Auto(
            "reserves.retirement_assets", "Vested retirement assets", retirement_default, "stated"
        ),
        _Auto("reserves.down_payment", "Down payment", down_default, "computed"),
        _Auto("reserves.closing_costs", "Closing costs", None, "manual"),
    ]
    lines, eff = _apply(autos, overrides)

    result = compute_reserves(
        liquid_assets=eff["reserves.liquid_assets"],
        retirement_assets=eff["reserves.retirement_assets"],
        retirement_factor=factor,
        excluded_funds=excluded_default,
        down_payment=eff["reserves.down_payment"],
        closing_costs=eff["reserves.closing_costs"],
        monthly_housing_payment=piti,
        months_required=required_months,
    )

    steps = [
        CalcStep(
            label=f"Retirement counted ({int(factor * 100)}%)",
            value=_money(result.retirement_counted),
        ),
        CalcStep(label="Gifts / borrowed (excluded)", value=_money(result.excluded_funds)),
        CalcStep(label="Eligible reserves", value=_money(result.eligible_reserves)),
        CalcStep(
            label="Monthly housing payment (PITI, from DTI)",
            value=_money(result.monthly_housing_payment),
        ),
        CalcStep(
            label="Months available",
            value="—" if result.months_available is None else f"{result.months_available} mo",
            emphasis=True,
        ),
        CalcStep(
            label="Months required",
            value="—" if result.months_required is None else f"{result.months_required} mo",
        ),
    ]
    status = (
        None if result.sufficient is None else "sufficient" if result.sufficient else "insufficient"
    )
    return CalculatorView(
        calculator="reserves",
        title="Reserves",
        headline="—" if result.months_available is None else f"{result.months_available} months",
        headline_label="Reserves available",
        status=status,
        program=program.value if program else None,
        inputs=lines,
        steps=steps,
        formulas=[ELIGIBLE_FORMULA, MONTHS_FORMULA],
        methodology=MethodologyNote(
            starter=True,
            text=(
                "Gifts/borrowed funds are excluded from reserves; vested retirement counts at a haircut — "
                f"FHA's 60% (LP-84) here ({int(factor * 100)}%). The required months are DU/program/property/"
                "overlay-driven (the asset rules, threshold-as-data) — a starter to validate with Priya."
            ),
        ),
        findings=await _findings(db, loan_file.id, cutoff),
    )


def _resolve_required_reserve_months(
    program: LoanProgram | None, lender_slug: str | None
) -> Decimal:
    """The required reserve months — from the reserves rule (overlay-overrideable), else starter."""
    if program is None:
        return _STARTER_REQUIRED_RESERVE_MONTHS
    rules = default_registry().resolve(program=program, lender_slug=lender_slug)
    rule = next(
        (
            r
            for r in rules
            if r.rule_id.endswith("reserves_required") or r.rule_id.endswith("reserves.min_months")
        ),
        None,
    )
    return rule.condition.value if rule is not None else _STARTER_REQUIRED_RESERVE_MONTHS


# --------------------------------------------------------------------------- #
# 4) Max loan — invert DTI / LTV / loan-limit; the binding (lowest) wins
# --------------------------------------------------------------------------- #


async def build_max_loan_view(
    db: AsyncSession, *, loan_file: LoanFile, cutoff: float
) -> CalculatorView:
    dti_calc = await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    ltv_calc = await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)

    non_pi_housing = dti_calc.housing_payment - _pi_component(dti_calc)
    overrides = await _active_overrides(db, loan_file.id, "max_loan")
    autos = [
        _Auto(
            "max_loan.gross_monthly_income",
            "Gross monthly income",
            dti_calc.gross_monthly_income,
            "computed",
        ),
        _Auto("max_loan.property_value", "Property value", ltv_calc.value_basis, "computed"),
        _Auto("max_loan.loan_limit", "Program loan limit", _CONFORMING_LOAN_LIMIT, "manual"),
    ]
    lines, eff = _apply(autos, overrides)

    result = compute_max_loan(
        gross_monthly_income=eff["max_loan.gross_monthly_income"],
        max_back_end_dti_pct=dti_calc.limit.back_end_max,
        other_monthly_debts=dti_calc.monthly_debts,
        monthly_non_pi_housing=non_pi_housing,
        annual_rate_percent=loan_file.note_rate_percent,
        term_months=loan_file.amortization_months,
        property_value=eff["max_loan.property_value"],
        max_ltv_pct=ltv_calc.limit.ltv_max,
        loan_limit=eff["max_loan.loan_limit"],
    )

    steps = [
        CalcStep(
            label=f"{c.label}{' ← binds' if c.key == result.binding_key else ''}",
            value=_money(c.max_loan),
            emphasis=c.key == result.binding_key,
        )
        for c in result.constraints
    ]
    return CalculatorView(
        calculator="max_loan",
        title="Maximum loan",
        headline=_money(result.max_loan),
        headline_label="Max qualifying loan",
        status="binding:" + result.binding_key if result.binding_key else None,
        program=loan_file.loan_program.value if loan_file.loan_program else None,
        inputs=lines,
        steps=steps,
        formulas=[DTI_CONSTRAINT_FORMULA, LTV_CONSTRAINT_FORMULA, LOAN_LIMIT_FORMULA],
        methodology=MethodologyNote(
            starter=True,
            text=(
                "Inverts the binding constraint: the DTI ceiling (LP-76) → max payment → max principal; the "
                "LTV limit (LP-77) → value x max-LTV; and the program loan limit. The lowest binds. The "
                "FHFA conforming / FHA loan limit is a grounded-starter (it changes annually + is "
                "county-specific) — validate with Priya."
            ),
        ),
        findings=await _findings(db, loan_file.id, cutoff),
    )


def _pi_component(dti_calc: object) -> Decimal:
    """The principal+interest housing line (non-PI = housing - P&I)."""
    items = getattr(dti_calc, "housing_items", [])
    for item in items:
        if getattr(item, "key", "") == "housing.principal_interest":
            return getattr(item, "amount", Decimal(0))
    return Decimal(0)


# --------------------------------------------------------------------------- #
# Dispatch + override set/clear (shared, audited)
# --------------------------------------------------------------------------- #

Builder = Callable[..., Awaitable[CalculatorView]]
_BUILDERS: dict[str, Builder] = {
    "mortgage_insurance": build_mi_view,
    "self_employed": build_self_employed_view,
    "reserves": build_reserves_view,
    "max_loan": build_max_loan_view,
}


class UnknownCalculatorError(Exception):
    """The calculator name is not one of the four."""


class UnknownCalcFieldError(Exception):
    """The override field_key is not an input of this calculator."""


async def build_calculator(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    calculator: str,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> CalculatorView:
    """Build one calculator's transparent view (auto + overrides + compute + findings)."""
    builder = _BUILDERS.get(calculator)
    if builder is None:
        raise UnknownCalculatorError(calculator)
    return await builder(db, loan_file=loan_file, cutoff=confidence_cutoff)


async def set_calculator_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    calculator: str,
    field_key: str,
    data: CalcOverrideInput,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> CalculatorView:
    """Set (or revive) a calculator input override, audited; then recompute."""
    view = await build_calculator(
        db, loan_file=loan_file, calculator=calculator, confidence_cutoff=confidence_cutoff
    )
    line = next((line for line in view.inputs if line.key == field_key), None)
    if line is None:
        raise UnknownCalcFieldError(field_key)
    prior = line.amount if line.overridden else line.auto_amount

    existing = await _get_row(db, loan_file.id, calculator, field_key)
    if existing is not None:
        existing.value = data.amount
        existing.note = data.note
        existing.actor_user_id = actor_user_id
        existing.deleted_at = None
    else:
        db.add(
            CalculatorOverride(
                loan_file_id=loan_file.id,
                calculator=calculator,
                field_key=field_key,
                value=data.amount,
                note=data.note,
                actor_user_id=actor_user_id,
            )
        )
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.CALCULATOR_OVERRIDDEN,
        summary=f"{calculator} input overridden: {field_key}",
        actor_user_id=actor_user_id,
        detail={
            "calculator": calculator,
            "field_key": field_key,
            "from": None if prior is None else str(prior),
            "to": str(data.amount),
            "note": data.note,
        },
    )
    return await build_calculator(
        db, loan_file=loan_file, calculator=calculator, confidence_cutoff=confidence_cutoff
    )


async def clear_calculator_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    calculator: str,
    field_key: str,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> CalculatorView:
    """Clear an override (revert to auto), audited; then recompute."""
    existing = await _get_row(db, loan_file.id, calculator, field_key)
    if existing is not None and not existing.is_deleted:
        prior = existing.value
        existing.deleted_at = utcnow()
        await db.flush()
        await log_activity(
            db,
            loan_file_id=loan_file.id,
            activity_type=ActivityType.CALCULATOR_OVERRIDDEN,
            summary=f"{calculator} override cleared: {field_key}",
            actor_user_id=actor_user_id,
            detail={
                "calculator": calculator,
                "field_key": field_key,
                "from": str(prior),
                "to": None,
                "cleared": True,
            },
        )
    return await build_calculator(
        db, loan_file=loan_file, calculator=calculator, confidence_cutoff=confidence_cutoff
    )


async def _get_row(
    db: AsyncSession, loan_file_id: UUID, calculator: str, field_key: str
) -> CalculatorOverride | None:
    stmt = select(CalculatorOverride).where(
        CalculatorOverride.loan_file_id == loan_file_id,
        CalculatorOverride.calculator == calculator,
        CalculatorOverride.field_key == field_key,
    )
    return (await db.execute(stmt)).scalars().first()
