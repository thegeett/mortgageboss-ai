"""Calculations section assembler (LP-207, ADR-244).

Calls the four existing calculators (DTI / LTV / MI / reserves) and maps each
native return shape into LP-204's uniform ``CalculationEntry {value, breakdown}``.
It **computes nothing** — the calculators are the single source of truth; this is a
pure invoke + map, preserving each breakdown line's own source tag verbatim.

* **Source tags pass through, never re-derived.** A line the calculator tagged
  ``stated`` / ``extracted`` / ``computed`` / ``manual`` / ``override`` keeps that
  tag. (``CalcBreakdownLine.source`` is a free string, so the calculator's
  ``override`` tag — a 5th value — survives losslessly; no enum coercion.)
* **Not-computed = ``None``, never a fabricated 0.0.** When a calculator can't
  produce its headline (DTI has no income → ratio ``None``; LTV has no value basis
  → ratio ``None``; reserves has no PITI divisor → ``months_available`` ``None``),
  that calculation is ``None`` (LP-204: ``CalculationEntry | None``). MI always
  determines ``required`` (a "not required" answer is computed, not missing), so it
  is always present.
* **Money is stringified exactly** (LP-204's ``value`` rejects raw ``Decimal`` to
  avoid a silent float; breakdown ``amount`` is likewise a string).
* **DTI uses STATED (MISMO) income by construction** — surfaced faithfully with the
  income line tagged ``stated``. Reconciling stated-vs-extracted income is a
  downstream finding, not this assembler's job; the source tag makes the input
  transparent.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan_file import LoanFile
from app.schemas.calculators import CalculatorView
from app.schemas.dti import DtiCalculation, UnverifiedInput
from app.schemas.ltv import LtvCalculation
from app.services.calculators import build_reserves_view
from app.services.dti import (
    HOUSING_HOA,
    HOUSING_INSURANCE,
    HOUSING_MORTGAGE_INSURANCE,
    HOUSING_PRINCIPAL_INTEREST,
    HOUSING_TAXES,
    build_dti_calculation,
)
from app.services.ltv import (
    LTV_APPRAISED_VALUE,
    LTV_FIRST_LOAN,
    LTV_HELOC_DRAWN,
    LTV_HELOC_LIMIT,
    LTV_PURCHASE_PRICE,
    LTV_SECOND_LOAN,
    build_ltv_calculation,
)
from app.services.mi import (
    MI_ANNUAL_MIP_RATE_KEY,
    MI_BASE_LOAN_KEY,
    MI_PMI_RATE_KEY,
    MiComputation,
    compute_loan_mi,
)
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.snapshot.model import (
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
)

# --------------------------------------------------------------------------- #
# from_tag lineage: each breakdown line → the fact-tag id (fact_tags.csv) that produced it.
# A computed subtotal / a line with no fact-tag behind it → "derived" (NEVER a fabricated id).
# --------------------------------------------------------------------------- #
_DERIVED = "derived"  # an honest "no single fact-tag — a computed value"
_INCOME_PREFIX = "income."
_DEBT_PREFIX = "debt."

_DTI_FROM_TAG: dict[str, str] = {
    HOUSING_PRINCIPAL_INTEREST: "housing.pi",
    HOUSING_TAXES: "housing.taxes_monthly",
    HOUSING_INSURANCE: "housing.insurance_monthly",
    HOUSING_MORTGAGE_INSURANCE: "housing.mi_monthly",
    HOUSING_HOA: "housing.hoa_monthly",
}
_LTV_FROM_TAG: dict[str, str] = {
    LTV_FIRST_LOAN: "loan.amount",
    LTV_SECOND_LOAN: "loan.amount",
    LTV_HELOC_DRAWN: "liab.balance",
    LTV_HELOC_LIMIT: "liab.heloc_credit_limit",
    LTV_PURCHASE_PRICE: "property.purchase_price",
    LTV_APPRAISED_VALUE: "property.appraised_value",
}
_MI_FROM_TAG: dict[str, str] = {
    MI_BASE_LOAN_KEY: "loan.amount",
    MI_ANNUAL_MIP_RATE_KEY: "mi.factor",
    MI_PMI_RATE_KEY: "mi.factor",
}
_RESERVES_FROM_TAG: dict[str, str] = {
    "reserves.liquid_assets": "asset.usable_value",
    "reserves.retirement_assets": "asset.usable_value",
}

# The REQUIRED feeding tags whose unknown/absence GATES the calc (fail-closed through it). Kept to
# the inputs a trustworthy ratio genuinely needs: a missing hazard binder or tax figure understates
# the housing payment → the DTI would be confidently too-low. hoa/mi legitimately 0 → NOT required.
# LTV/MI/reserves already return None when their core input is missing, so they add none here.
_REQUIRED_DTI_TAGS = frozenset({"housing.insurance_monthly", "housing.taxes_monthly"})


def _dti_from_tag(key: str) -> str:
    if key.startswith(_INCOME_PREFIX):
        return "income.qualifying_monthly"
    if key.startswith(_DEBT_PREFIX):
        return "liab.dti_payment"
    return _DTI_FROM_TAG.get(key, _DERIVED)


class _CalcLineItem(Protocol):
    """The shape every calculator's line item shares (DtiLineItem / LtvLineItem / CalcLine).

    ``auto_amount`` is the auto-populated value BEFORE any override — ``None`` when the calculator
    could NOT derive it (no binder, no extraction). That ``None`` (not overridden) is the honest
    "this input is UNKNOWN" signal LP-318 gates on — the calculators otherwise collapse it to 0.
    """

    key: str
    label: str
    amount: Decimal
    auto_amount: Decimal | None
    source: str
    overridden: bool
    # LP-568 — DTI-only today (LtvLineItem has no notion of an obligation that ends at closing),
    # so both carry defaults and the protocol stays satisfiable by every calculator.
    excluded: bool
    excluded_reason: str | None


def _money(value: Decimal | None) -> str | None:
    """Serialize a Decimal amount as an exact string (None stays None)."""
    return None if value is None else str(value)


def _is_unknown(item: _CalcLineItem) -> bool:
    """This input was NOT derivable and was not overridden — the calculator defaulted it to 0."""
    return item.auto_amount is None and not item.overridden


def _line(item: _CalcLineItem, from_tag: str) -> CalcBreakdownLine:
    """Map one calculator line item, keeping its source tag + recording its fact-tag lineage.

    An UNKNOWN input surfaces ``amount=None`` (honest — the "absent≠0" trap the fact-tag vocab
    warns about), not the calculator's fabricated 0, so a gated calc's breakdown shows WHICH line
    was unknown.
    """
    return CalcBreakdownLine(
        key=item.key,
        label=item.label,
        amount=None if _is_unknown(item) else _money(item.amount),
        source=item.source,  # verbatim — never re-derived
        overridden=item.overridden,
        from_tag=from_tag,
        excluded=item.excluded,
        excluded_reason=item.excluded_reason,
    )


def _calc_confidence(lines: list[CalcBreakdownLine], confidence_of: _ConfidenceOf) -> float | None:
    """Min of the feeding fact-tags' confidences, ignoring parsed/derived passthroughs (LP-315).

    ``confidence_of(from_tag)`` returns a materialized fact-tag's confidence, or ``None`` for a
    parsed/derived passthrough (which the min ignores). Today every calc input is
    parsed/extracted/computed/derived, so this is ``None`` — the mechanism activates once
    AI-confidence tags (income.qualifying_monthly, liab.dti_payment) are materialized and wired.
    """
    confidences = [
        c for line in lines if (c := confidence_of(line.from_tag or _DERIVED)) is not None
    ]
    return min(confidences) if confidences else None


def _gate_reason(lines: list[CalcBreakdownLine], required: frozenset[str]) -> str | None:
    """Fail-closed: name the required feeding tag(s) that are unknown/absent, else None (not gated).

    A REQUIRED tag with no breakdown line at all → "absent"; ANY line for it surfaced unknown
    (``amount=None``) → "unknown". Distinct reasons, both fail-closed — the calc must not emit a
    confident number resting on a fabricated 0. Lines are grouped by from_tag (not last-wins), so a
    required tag fed by SEVERAL lines gates if any one of them is unknown.
    """
    lines_by_tag: dict[str, list[CalcBreakdownLine]] = defaultdict(list)
    for line in lines:
        if line.from_tag is not None:
            lines_by_tag[line.from_tag].append(line)
    problems: list[str] = []
    for tag in sorted(required):
        tag_lines = lines_by_tag.get(tag)
        if not tag_lines:
            problems.append(f"{tag} is absent")
        elif any(line.amount is None for line in tag_lines):
            problems.append(f"{tag} is unknown")
    if not problems:
        return None
    return "calculation gated (fail-closed): " + "; ".join(problems)


class _ConfidenceOf(Protocol):
    def __call__(self, from_tag: str) -> float | None: ...


def _no_tag_confidence(from_tag: str) -> float | None:
    """Production lookup: no fact-tag is materialized with a confidence yet → always None."""
    return None


def _entry(
    value: dict[str, str | bool | None],
    lines: list[CalcBreakdownLine],
    *,
    required: frozenset[str] = frozenset(),
    nullable_headlines: tuple[str, ...] = (),
    confidence_of: _ConfidenceOf = _no_tag_confidence,
    unverified_inputs: tuple[UnverifiedInput, ...] = (),
    upstream_gate_reason: str | None = None,
) -> CalculationEntry:
    """Assemble a CalculationEntry with confidence + fail-closed gating over its breakdown.

    When gated, the ``nullable_headlines`` (the ratio/premium a rule would trust) are set to None so
    the calc emits the gated marker + reason, NOT a confident-but-wrong number.

    ``upstream_gate_reason`` (LP-621 review) is a gate the CALCULATOR itself raised, which this
    breakdown-derived check cannot see. The two are independent and either one gates: the local check
    knows about absent/unknown INPUT LINES, while a calculator can gate for a reason no line expresses
    — LP-621's is "this is an investment subject and the method that applies to it cannot be computed",
    which is a fact about the LOAN, not about a missing figure. Without this the snapshot published a
    confident 44.8% to the calibrated rules while the /dti card showed the gate, so the only consumer
    that could act on the ratio was the one not told it was unsound.
    """
    reason = _gate_reason(lines, required)
    if upstream_gate_reason is not None:
        # Both, when both apply — a reader who is told only one of two reasons will fix that one and
        # expect the gate to lift.
        reason = f"{reason}  {upstream_gate_reason}" if reason else upstream_gate_reason
    # bug-001 — the SAME note the /dti card shows, carried on the calculation rather than rebuilt, so
    # the two gate-reason producers cannot drift. It reaches the AI cross-check through this, which is
    # where a processor read "DTI calculation gated due to missing property tax amount" about a figure
    # the file states twice.
    if reason is not None and unverified_inputs:
        reason = reason + "  " + " ".join(u.sentence for u in unverified_inputs)
    if reason is not None:
        value = {**value, **dict.fromkeys(nullable_headlines)}
    return CalculationEntry(
        value=value,
        breakdown=lines,
        gated=reason is not None,
        gate_reason=reason,
        confidence=_calc_confidence(lines, confidence_of),
    )


def map_dti(dti: DtiCalculation) -> CalculationEntry | None:
    """DTI → CalculationEntry, or None when the back-end ratio isn't computable.

    Fail-closed (LP-318): if a REQUIRED housing input (taxes / insurance) is unknown or absent, the
    DTI is GATED — the ratios are nulled and the reason names the tag (LF-6T3N: no binder → the
    insurance line is unknown → couldnt_check), never a confident too-low number built on a 0.
    """
    if dti.back_end_dti is None:  # no income → the ratio can't be computed
        return None
    lines = [
        _line(i, _dti_from_tag(i.key))
        for i in (*dti.income_items, *dti.housing_items, *dti.debt_items)
    ]
    return _entry(
        {
            "front_end_dti": _money(dti.front_end_dti),
            "back_end_dti": _money(dti.back_end_dti),
            "gross_monthly_income": _money(dti.gross_monthly_income),
            "housing_payment": _money(dti.housing_payment),
            "monthly_debts": _money(dti.monthly_debts),
            "total_monthly_obligations": _money(dti.total_monthly_obligations),
        },
        lines,
        required=_REQUIRED_DTI_TAGS,
        nullable_headlines=("front_end_dti", "back_end_dti"),
        unverified_inputs=dti.unverified_inputs,
        # LP-621 review — the calculator's OWN gate, which this module's breakdown-derived check cannot
        # reproduce. `_gate_reason` looks for a required tag that is absent or unknown; LP-621 gates on
        # something no line expresses — an investment subject whose Fannie treatment is not computable.
        # `dti.gated` was set, `gate_display_ratios` nulled the ratios at the API boundary, and this
        # path read neither, so the rule engine kept receiving the confident ratio the ticket says it
        # stops publishing.
        upstream_gate_reason=dti.gate_reason if dti.gated else None,
    )


def map_ltv(ltv: LtvCalculation) -> CalculationEntry | None:
    """LTV → CalculationEntry, or None when there is no value basis (ratio None)."""
    if ltv.ltv is None:  # no appraised/purchase value basis → ratio not computable
        return None
    lines = [
        _line(i, _LTV_FROM_TAG.get(i.key, _DERIVED)) for i in (*ltv.loan_items, *ltv.value_items)
    ]
    return _entry(
        {
            "ltv": _money(ltv.ltv),
            "cltv": _money(ltv.cltv),
            "hcltv": _money(ltv.hcltv),
            # LP-496 — the exact figures above, the B2-1.2-01 delivered whole percents here. Both
            # are shown: a bare "81" would hide whether the ratio was 80.01 or 80.99.
            "ltv_delivered": _money(ltv.ltv_delivered),
            "cltv_delivered": _money(ltv.cltv_delivered),
            "hcltv_delivered": _money(ltv.hcltv_delivered),
            "value_basis": _money(ltv.value_basis),
            "value_basis_label": ltv.value_basis_label,
            "appraised_value_source": ltv.appraised_value_source,
            "purpose": ltv.purpose,
            "program": ltv.program,
        },
        lines,
    )


def map_mi(mi: MiComputation) -> CalculationEntry:
    """MI → CalculationEntry (always present — ``required`` is always determined)."""
    result = mi.result
    lines = [_line(i, _MI_FROM_TAG.get(i.key, _DERIVED)) for i in mi.inputs]
    return _entry(
        {
            "program": result.program,
            "required": result.required,
            "monthly_premium": _money(result.monthly_premium),
            "annual_rate_bps": _money(result.annual_rate_bps),
            "upfront_premium": _money(result.upfront_premium),
            "cancel_ltv": _money(result.cancel_ltv),
            "duration_label": result.duration_label,
        },
        lines,
    )


def map_reserves(view: CalculatorView) -> CalculationEntry | None:
    """Reserves ``CalculatorView`` → CalculationEntry, or None when not computable.

    Branches on the calculator's structured ``computed`` flag (False when there is no
    PITI divisor → months not computable) — NOT on the ``headline`` display placeholder,
    so a change to that presentation string can't turn a not-computed reserves into a
    fabricated present entry.

    LP-498 review — ``months_available`` IS PROJECTED, and it was not. AS-4 declares
    ``months_available: {calc: [reserves, months_available]}``; this dict carried headline / status /
    program only, so ``_calc_operand``'s ``entry.value.get("months_available")`` returned None, the
    operand failed, and AS-4 resolved to ``couldnt_check`` for every subject on every real file. The
    defect survived activation because every AS-4 test hand-builds the key (fire_path_scenarios,
    test_assets_family) and none routes through ``build_calculations_section`` — so the rule was
    proven against a snapshot shape production never produces. ``months_required`` goes with it: the
    rule reads its requirement from a tag, but a reader comparing the two surfaces needs both here.
    """
    if not view.computed:
        return None
    lines = [_line(i, _RESERVES_FROM_TAG.get(i.key, _DERIVED)) for i in view.inputs]
    return _entry(
        {
            "headline": view.headline,
            "status": view.status,
            "program": view.program,
            "months_available": _money(view.months_available),
            "months_required": _money(view.months_required),
        },
        lines,
    )


async def build_calculations_section(db: AsyncSession, loan_file: LoanFile) -> CalculationsSection:
    """Invoke the four calculators and map each result (or None) into the section.

    Pure invoke + map — no calculation math is reimplemented here.
    """
    cutoff = DEFAULT_CONFIDENCE_CUTOFF
    dti = await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    ltv = await build_ltv_calculation(db, loan_file=loan_file, confidence_cutoff=cutoff)
    mi = await compute_loan_mi(db, loan_file=loan_file, confidence_cutoff=cutoff)
    reserves = await build_reserves_view(db, loan_file=loan_file, cutoff=cutoff)

    return CalculationsSection.present(
        dti=map_dti(dti),
        ltv=map_ltv(ltv),
        mi=map_mi(mi),
        reserves=map_reserves(reserves),
    )
