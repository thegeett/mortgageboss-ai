"""DTI calculator service (LP-76) — auto-populate, override, couple to findings.

This is the DB-facing half of the DTI calculator. It:

1. **Auto-populates** the itemized inputs from the file's structured data — income
   from stated income, debts from stated liabilities, the housing payment from the
   loan terms (computed P&I) + extracted taxes / insurance / HOA. The calculator
   opens **already filled** with the file's real numbers (the "better than
   ChatGPT": no re-entry), reading the *same* structured data the rules engine
   evaluates.
2. Applies the processor's **overrides** (persisted, audited) on top — overrides
   take precedence; the auto values are a starting point, not a cage.
3. Computes the ratios via the pure deterministic engine (:mod:`app.verification.dti`).
4. Resolves the **effective program limit** side-by-side (LP-74's rule + any lender
   overlay).
5. **Couples to findings** (LP-75): the unresolved-findings alert queries open
   in-scope findings; and because the calculation reads the structured data live,
   applying a finding (which adds e.g. a liability) makes the next calculation
   recompute — LP-76 is a recompute consumer of the apply hook.

Pure math lives in :mod:`app.verification.dti`; this module only gathers data and
maps it onto the response. Money is ``Decimal``; tenant scoping is via the loan
file (the caller resolves it within the company first); no PII (no SSNs) is read.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.borrower import Borrower
from app.models.document import Document
from app.models.dti_override import DtiOverride
from app.models.extraction import Extraction
from app.models.helpers import only_active
from app.models.lender import Lender, LoanProgram
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedIncomeItem, StatedLiability
from app.schemas.dti import (
    DtiCalculation,
    DtiFindingsStatus,
    DtiLimit,
    DtiLineItem,
    DtiOverrideInput,
    UnverifiedInput,
)
from app.services.activity_log import log_activity
from app.services.finding_blocking import open_in_scope_findings
from app.services.mi import compute_loan_mi
from app.verification.confidence import DEFAULT_CONFIDENCE_CUTOFF
from app.verification.dti import (
    BACK_END_FORMULA,
    FRONT_END_FORMULA,
    DtiLine,
    compute_dti,
    monthly_principal_interest,
)
from app.verification.registry import default_registry

# --- Stable field keys for the housing components (the PITI + MI + HOA lines) -
#: Money is carried to cents. Same constant and rounding as every calculator (verification/dti.py,
#: ltv, mi, reserves) — see `_extracted_monthly` for why an unrounded division is not merely untidy.
_CENTS = Decimal("0.01")

HOUSING_PRINCIPAL_INTEREST = "housing.principal_interest"
HOUSING_TAXES = "housing.taxes"
HOUSING_INSURANCE = "housing.insurance"
HOUSING_MORTGAGE_INSURANCE = "housing.mortgage_insurance"
HOUSING_HOA = "housing.hoa"

# LP-375 — the REQUIRED housing inputs whose absence must FAIL-CLOSED (absent≠0), mirroring the snapshot
# path's ``_REQUIRED_DTI_TAGS`` (calculations_section.py): a missing tax figure or hazard binder understates
# the housing payment → the DTI would be confidently too-low. HOA/MI legitimately 0 → NOT required. Kept as
# the line KEYS here (the display path's currency) so services/dti.py needs no import from the snapshot
# layer (which imports THIS module — the dependency is one-directional).
_REQUIRED_HOUSING_KEYS = frozenset({HOUSING_TAXES, HOUSING_INSURANCE})

_BACK_END_RULE_IDS = {
    LoanProgram.CONVENTIONAL: "conv.dti.back_end_max",
    LoanProgram.FHA: "fha.dti.back_end_max",
}


# --------------------------------------------------------------------------- #
# Auto-population — the structured-data inputs (before overrides)
# --------------------------------------------------------------------------- #


class _AutoLine:
    """An auto-populated input line (key, label, auto amount, source) pre-override.

    ``unknown`` (LP-413): the input's figure could not be derived AND the line must FAIL-CLOSED (gate the
    calc), NOT default to 0. It carries the gate for a line that is NOT a static ``_REQUIRED_HOUSING_KEYS``
    member but is unknown on THIS file — an HOA statement present with a dues amount but an unstated /
    unrecognized frequency (we must not assume monthly, the 12x risk, nor drop it to 0, an understatement).
    Absent-HOA (no dues) stays ``unknown=False`` → a legitimate $0 line."""

    __slots__ = ("auto", "excluded_reason", "key", "label", "source", "unknown")

    def __init__(
        self,
        key: str,
        label: str,
        auto: Decimal | None,
        source: str,
        *,
        unknown: bool = False,
        excluded_reason: str | None = None,
    ) -> None:
        self.key = key
        self.label = label
        self.auto = auto
        self.source = source
        self.unknown = unknown
        # LP-568: set → the line is SHOWN but not summed, and this says why. Distinct from
        # ``unknown`` (a figure we could not derive) and from a $0 line (a figure that is zero):
        # the amount here is known and real, it simply does not survive closing.
        self.excluded_reason = excluded_reason


async def _auto_income_lines(db: AsyncSession, loan_file_id: UUID) -> list[_AutoLine]:
    """Stated income, itemized per income item (label by type + borrower first name)."""
    stmt = only_active(
        select(StatedIncomeItem, Borrower.first_name)
        .join(Borrower, StatedIncomeItem.borrower_id == Borrower.id)
        .where(Borrower.loan_file_id == loan_file_id),
        StatedIncomeItem,
    ).order_by(Borrower.borrower_position, StatedIncomeItem.created_at)
    lines: list[_AutoLine] = []
    for item, first_name in (await db.execute(stmt)).all():
        kind = (item.income_type or "Income").strip()
        who = (first_name or "Borrower").strip()
        lines.append(
            _AutoLine(f"income.{item.id}", f"{kind} — {who}", item.monthly_amount, "stated")
        )
    return lines


# LP-569 review — the two MISMO indicators do NOT mean the same thing, and collapsing them into one
# reason put words in the export's mouth. `LiabilityPayoffStatusIndicator` says the obligation is
# retired at closing; `LiabilityExclusionIndicator` says omit it from liability totals (paid by
# another party, a duplicate trade line). Both keep the payment out of the ratio, but a line reading
# "paid off at closing" on the strength of an exclusion flag asserts a payoff the file never stated.
_EXCLUSION_REASONS = {
    "mismo_payoff": "paid off at closing",
    "mismo_exclusion": "excluded from liabilities per the application",
    "processor": "paid off at closing",
}
_DEFAULT_EXCLUSION_REASON = "not counted"


async def _auto_debt_lines(db: AsyncSession, loan_file_id: UUID) -> list[_AutoLine]:
    """Stated liabilities, itemized per liability (each monthly obligation)."""
    stmt = only_active(
        select(StatedLiability).where(StatedLiability.loan_file_id == loan_file_id),
        StatedLiability,
    ).order_by(StatedLiability.created_at)
    lines: list[_AutoLine] = []
    for liab in (await db.execute(stmt)).scalars().all():
        kind = (liab.liability_type or "Liability").strip()
        label = f"{kind} — {liab.holder_name}" if liab.holder_name else kind
        # LP-568 — a liability paid off at closing does not belong in the back-end ratio. DTI is
        # forward-looking: it measures what is owed AFTER this loan funds. On a refinance the
        # mortgage being replaced is the clearest case (counting it charges the same house twice,
        # once as `housing_payment` and once here), and a purchase has the same shape via a
        # departing residence or a debt cleared to qualify.
        #
        # `is True` is deliberate — None means "not established" and must keep counting. Silence
        # is the safe direction here: over-counting fails a good file visibly, under-counting
        # passes a bad one quietly.
        lines.append(
            _AutoLine(
                f"debt.{liab.id}",
                label,
                liab.monthly_payment,
                "stated",
                excluded_reason=(
                    _EXCLUSION_REASONS.get(liab.payoff_source or "", _DEFAULT_EXCLUSION_REASON)
                    if liab.paid_off_at_closing is True
                    else None
                ),
            )
        )
    return lines


async def _auto_housing_lines(
    db: AsyncSession,
    loan_file: LoanFile,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> list[_AutoLine]:
    """The housing payment components: PITI (computed P&I + extracted T&I) + MI + HOA.

    The mortgage-insurance line CONSUMES the LP-87 MI calculator's monthly premium (LP-91) —
    program-aware (FHA MIP always; Conventional PMI when LTV > 80%) and from the single shared
    source (:func:`app.services.mi.compute_loan_mi`), so PITI no longer omits mandatory MI.
    Only the *monthly* premium enters PITI; the FHA UFMIP is financed into the loan (not a
    monthly DTI item). The auto value is overrideable (a processor DtiOverride still wins).
    """
    pi = monthly_principal_interest(
        loan_file.note_amount or loan_file.loan_amount,
        loan_file.note_rate_percent,
        loan_file.amortization_months,
    )
    taxes = await _extracted_monthly(
        db, loan_file.id, "property_tax_bill", "annual_tax_amount", annual=True
    )
    insurance = await _extracted_monthly(
        db, loan_file.id, "homeowners_insurance", "annual_premium", annual=True
    )
    # LP-413: (monthly | None, present_but_unconvertible). The second flag GATES the HOA line when a dues
    # amount is present but its frequency is unstated/unrecognized — never a silent monthly assumption
    # (a 12x overstatement) and never a silent drop to 0 (an understatement, the worse failure mode).
    hoa, hoa_unconvertible = await _extracted_hoa_monthly(db, loan_file.id)
    mi = await compute_loan_mi(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)
    return [
        _AutoLine(HOUSING_PRINCIPAL_INTEREST, "Principal & interest", pi, "computed"),
        _AutoLine(HOUSING_TAXES, "Property taxes", taxes, "extracted"),
        _AutoLine(HOUSING_INSURANCE, "Homeowners insurance", insurance, "extracted"),
        # Consumed from the MI calculator (single source of truth) — "computed", no longer the
        # old manual/$0 line that silently omitted MI and understated the DTI.
        _AutoLine(
            HOUSING_MORTGAGE_INSURANCE,
            "Mortgage insurance (MI)",
            mi.result.monthly_premium,
            "computed",
        ),
        _AutoLine(HOUSING_HOA, "HOA dues", hoa, "extracted", unknown=hoa_unconvertible),
    ]


async def _current_extracted_data(
    db: AsyncSession, loan_file_id: UUID, document_type: str
) -> dict[str, Any] | None:
    """The current extraction payload for the newest document of a type, or None."""
    stmt = (
        only_active(
            select(Extraction)
            .join(Document, Extraction.document_id == Document.id)
            .where(
                Document.loan_file_id == loan_file_id,
                Document.document_type == document_type,
                Extraction.is_current.is_(True),
            ),
            Document,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    extraction = (await db.execute(stmt)).scalars().first()
    return extraction.extracted_data if extraction is not None else None


def _typed_value(data: dict[str, Any] | None, field: str) -> Decimal | None:
    """Read a typed-core ``{value}`` Decimal off an extraction payload."""
    if data is None:
        return None
    node = data.get(field)
    if not isinstance(node, dict):
        return None
    raw = node.get("value")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None


async def _unverified_housing_inputs(
    db: AsyncSession, loan_file_id: UUID, gated_labels: list[str]
) -> tuple[UnverifiedInput, ...]:
    """Figures the FILE STATES for a gated housing input, which are not acceptable verification.

    bug-001. A real file gated on "Property taxes is unknown" while stating the annual tax outright
    in two documents — $5,579, on a UWM dashboard and a Property Explorer report, both automated
    valuations over county assessor data. The gate is RIGHT: an estimator's figure must not set a
    DTI, and `_extracted_monthly` reads the tax BILL for exactly that reason. What was wrong is being
    told the number is missing, going to look, and finding it twice.

    This does not feed the calculation and cannot ungate it. It lets the gate SAY what the file
    contains, and gives the card the `field_key` + `monthly_amount` to offer it as a ONE-CLICK
    OVERRIDE — which records the processor's id and a note naming the source, so accepting an
    estimate is a decision on the record rather than an assumption the calculator made quietly.
    """
    if "Property taxes" not in gated_labels:
        return ()
    annual = _typed_value(
        await _current_extracted_data(db, loan_file_id, "home_value_estimate"),
        "annual_property_taxes",
    )
    if annual is None or annual <= 0:
        return ()
    return (
        UnverifiedInput(
            field_key=HOUSING_TAXES,
            label="Property taxes",
            monthly_amount=(annual / Decimal(12)).quantize(_CENTS, rounding=ROUND_HALF_UP),
            annual_amount=annual.quantize(_CENTS, rounding=ROUND_HALF_UP),
            source_label="the home value estimate",
            sentence=(
                f"The home value estimate states annual property taxes of ${annual:,.2f}. That is an "
                "automated valuation's estimate, not verification — upload the property tax bill."
            ),
        ),
    )


async def _extracted_monthly(
    db: AsyncSession, loan_file_id: UUID, document_type: str, field: str, *, annual: bool
) -> Decimal | None:
    """A monthly amount from an extracted (possibly annual) figure, or None.

    A NON-POSITIVE figure is NOT derivable → None (LP-375). This feeds only the REQUIRED housing inputs
    (property taxes / homeowners insurance), where a $0 is implausible and — exactly like an ABSENT
    figure (absent≠0) — must FAIL-CLOSED to "unknown", never a confident too-low DTI resting on a
    fabricated 0. This is the single source both gates read: the display ``unknown`` flag and the
    snapshot ``_is_unknown`` both key off ``auto_amount is None``, so returning None here gates BOTH.
    A processor who knows a figure is genuinely 0 can still override the line explicitly (an override
    is trusted)."""
    value = _typed_value(await _current_extracted_data(db, loan_file_id, document_type), field)
    if value is None:
        return None
    # QUANTIZED TO CENTS. An unrounded `annual / 12` reaches the snapshot as e.g.
    # 104.1666666666666666666666667, and the PII-at-rest guard reads that 25-digit fractional run as an
    # unmasked account number and refuses to persist the ENTIRE snapshot (its lookahead exempts only the
    # integer part of a decimal). That cost LF-3CVT its snapshot the moment a homeowners binder landed.
    # Quantized on BOTH branches: an already-monthly extracted figure is a no-op, and a malformed one is
    # fixed. Kept identical to the housing.insurance_monthly / housing.taxes_monthly TAGS, which round
    # the same way — the tags are documented as agreeing-or-abstaining and never looser than this
    # calculation, and rounding one side but not the other would break that by a fraction of a cent.
    #
    # LP-616 — AND THE NON-POSITIVE GATE READS THE ROUNDED FIGURE. It used to run first, on the annual
    # value, so a $0.05 annual premium passed it and then rounded to 0.00 — a confident zero handed to
    # the DTI, which is the fabricated 0 the docstring above says this gate exists to prevent. Both
    # gates key off `auto_amount is None`, so the zero had to become a None to reach them.
    # `quantize` raises InvalidOperation past the context's 28 digits (a 30-digit account number
    # mis-extracted into an amount field), which is a value this function cannot derive a monthly from.
    try:
        monthly = (
            (value / Decimal(12)).quantize(_CENTS, rounding=ROUND_HALF_UP)
            if annual
            else value.quantize(_CENTS, rounding=ROUND_HALF_UP)
        )
    except InvalidOperation:
        return None
    return monthly if monthly > 0 else None


# LP-413 — the HOA dues-frequency → months-covered map (the divisor to a monthly figure). Kept BYTE-
# IDENTICAL to the housing.hoa_monthly TAG's map (tag_materialization/derived.py ``_HOA_FREQUENCY_MONTHS``,
# ADR-328) so this calculation is never LOOSER than the tag: both recognize exactly this set and both fail
# closed on everything else. A drift-guard test asserts the two stay equal (widen them TOGETHER, or the calc
# would compute where the tag abstains). NO default entry — an unmapped frequency is NOT silently monthly.
_HOA_FREQUENCY_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semiannual": 6,
    "semi-annual": 6,
    "annual": 12,
    "annually": 12,
}


async def _extracted_hoa_monthly(
    db: AsyncSession, loan_file_id: UUID
) -> tuple[Decimal | None, bool]:
    """HOA dues normalized to monthly using the stated dues frequency → (monthly | None, unconvertible).

    LP-413 — the fix for a LIVE 12x miscalculation. The old code did ``divisor.get(frequency, 1)``: an
    unstated or unrecognized frequency silently became MONTHLY, so a "600" that is actually annual entered
    the DTI as $600/mo — a 12x overstatement of housing expense in a number that drives qualification, with
    no cross-check. It now maps ONLY the recognized frequencies and, for a dues amount present with an
    unstated/unrecognized frequency, returns ``(None, True)`` — a signal the caller uses to GATE the calc
    (the LP-375 fail-closed channel). In a CALCULATION "fail closed" cannot be an unknown number, so it is
    the degraded/gated state, NOT a smaller number (ADR-329):

      * NO dues amount            → (None, False): there is no HOA figure → a legitimate $0 HOA line (a
                                    no-HOA property), never a gate.
      * dues + recognized freq    → (dues ÷ months, False): the normal path, UNCHANGED for every recognized
                                    frequency.
      * dues + unstated/unknown   → (None, True): DO NOT assume monthly (the 12x overstatement) and DO NOT
        freq                        drop to 0 (an understatement — the worse failure mode, which makes a
                                    borrower look MORE qualified); GATE instead (honest / degraded).

    A processor who knows the true amount can still override the HOA line (an override is trusted, clears
    the gate). Never LOOSER than the housing.hoa_monthly tag (same map, both fail closed — ADR-328/329)."""
    data = await _current_extracted_data(db, loan_file_id, "hoa_statement")
    dues = _typed_value(data, "dues_amount")
    if dues is None:
        return None, False  # no HOA figure — a legitimate $0 line, not a gate
    frequency = ""
    node = (data or {}).get("dues_frequency")
    if isinstance(node, dict) and isinstance(node.get("value"), str):
        frequency = node["value"].strip().lower()
    months = _HOA_FREQUENCY_MONTHS.get(frequency)
    if months is None:
        # Present dues, unconvertible frequency: fail closed (gate), never assume monthly, never drop to 0.
        return None, True
    # Cents, matching the housing.hoa_monthly tag's identical division — see `_extracted_monthly`.
    return (dues / Decimal(months)).quantize(_CENTS, rounding=ROUND_HALF_UP), False


# --------------------------------------------------------------------------- #
# The calculation — auto + overrides → ratios + limit + findings
# --------------------------------------------------------------------------- #


async def _active_overrides(db: AsyncSession, loan_file_id: UUID) -> dict[str, Decimal]:
    stmt = only_active(
        select(DtiOverride).where(DtiOverride.loan_file_id == loan_file_id), DtiOverride
    )
    return {row.field_key: row.value for row in (await db.execute(stmt)).scalars().all()}


def _to_items(
    autos: Sequence[_AutoLine], overrides: dict[str, Decimal]
) -> tuple[list[DtiLineItem], list[DtiLine]]:
    """Build response line items + the engine lines (effective = override ?? auto ?? 0)."""
    items: list[DtiLineItem] = []
    engine_lines: list[DtiLine] = []
    for auto in autos:
        override = overrides.get(auto.key)
        effective = override if override is not None else (auto.auto or Decimal(0))
        # LP-569 review — AN OVERRIDE RE-INCLUDES THE LINE. The exclusion is a claim about the file
        # ("this debt is retired at closing"); a processor who overrides the line is disputing that
        # claim, and the endpoint already accepts, persists and audits the override. Dropping it
        # from the math anyway meant the figure was echoed back while the DTI never moved, with no
        # way to re-include a debt wrongly flagged. Same precedent as the fail-closed housing gate:
        # "an override on the line clears the gate (a processor-supplied figure is trusted)".
        excluded = auto.excluded_reason is not None and override is None
        items.append(
            DtiLineItem(
                key=auto.key,
                label=auto.label,
                auto_amount=auto.auto,
                override_amount=override,
                amount=effective,
                source="override" if override is not None else auto.source,
                overridden=override is not None,
                # LP-375: a REQUIRED input that could not be derived and was not overridden → its ``amount``
                # of 0 is a fail-closed placeholder, NOT an extracted $0.00. The display renders "unknown".
                # LP-413 extends this to a line the auto-populator explicitly marked ``unknown`` on THIS file
                # (a present-but-unconvertible HOA) — a data-driven gate, not static key membership. An
                # override on the line clears the gate (a processor-supplied figure is trusted).
                unknown=(
                    override is None
                    and (auto.unknown or (auto.auto is None and auto.key in _REQUIRED_HOUSING_KEYS))
                ),
                excluded=excluded,
                excluded_reason=auto.excluded_reason if excluded else None,
            )
        )
        # LP-568: the ITEM is still emitted (a processor must see the line and why it dropped
        # out — a debt that silently vanishes is worse than one counted wrongly), but it never
        # reaches the engine, so it cannot enter a total.
        if not excluded:
            engine_lines.append(DtiLine(key=auto.key, label=auto.label, amount=effective))
    return items, engine_lines


async def build_dti_calculation(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> DtiCalculation:
    """Assemble the full, transparent DTI calculation for one loan file.

    Auto-populates from the structured data, applies overrides, computes the
    ratios deterministically, resolves the effective limit, and attaches the
    unresolved-findings alert. Reads only — the caller has resolved the file
    within the company (tenant scoping).
    """
    income_auto = await _auto_income_lines(db, loan_file.id)
    housing_auto = await _auto_housing_lines(db, loan_file, confidence_cutoff)
    debt_auto = await _auto_debt_lines(db, loan_file.id)
    overrides = await _active_overrides(db, loan_file.id)

    income_items, income_lines = _to_items(income_auto, overrides)
    housing_items, housing_lines = _to_items(housing_auto, overrides)
    debt_items, debt_lines = _to_items(debt_auto, overrides)

    result = compute_dti(income_lines, housing_lines, debt_lines)

    # LP-375 — FAIL-CLOSED gating: a REQUIRED housing input (taxes/insurance) unknown (auto None, not
    # overridden) marks the calc GATED. The ratios are LEFT computed here on purpose — the snapshot path
    # (calculations_section.map_dti) re-derives the gate from the line amounts and would treat a None
    # back-end ratio as "no income" (its short-circuit), flipping its honest gated entry to ABSENT. The
    # DISPLAY nulls the ratios instead (``gate_display_ratios`` at the API boundary), so the /dti card
    # agrees with the engine WITHOUT this shared function altering the snapshot path.
    gated_labels = [item.label for item in housing_items if item.unknown]
    gated = bool(gated_labels)
    # bug-001 — name what the file DOES state for a gated input, so the gate reads as caution rather
    # than as a system that cannot see its own documents.
    unverified = await _unverified_housing_inputs(db, loan_file.id, gated_labels)
    gate_reason = (
        "calculation gated (fail-closed): "
        + "; ".join(f"{label} is unknown" for label in gated_labels)
        + ("  " + " ".join(u.sentence for u in unverified) if unverified else "")
        if gated
        else None
    )

    lender_slug = await _lender_slug(db, loan_file)
    limit = _resolve_limit(loan_file.loan_program, lender_slug, result.back_end_pct)

    in_scope = await open_in_scope_findings(
        db, loan_file_id=loan_file.id, confidence_cutoff=confidence_cutoff
    )

    return DtiCalculation(
        front_end_dti=result.front_end_pct,
        back_end_dti=result.back_end_pct,
        gated=gated,
        gate_reason=gate_reason,
        unverified_inputs=unverified,
        gross_monthly_income=result.gross_monthly_income,
        housing_payment=result.housing_payment,
        monthly_debts=result.monthly_debts,
        total_monthly_obligations=result.total_monthly_obligations,
        income_items=income_items,
        housing_items=housing_items,
        debt_items=debt_items,
        front_end_formula=FRONT_END_FORMULA,
        back_end_formula=BACK_END_FORMULA,
        program=loan_file.loan_program.value if loan_file.loan_program else None,
        limit=limit,
        findings=DtiFindingsStatus(unresolved=len(in_scope) > 0, open_in_scope_count=len(in_scope)),
    )


def gate_display_ratios(calc: DtiCalculation) -> DtiCalculation:
    """The DISPLAY view of a gated DTI (LP-375): NULL the headline ratios (never a confident number
    resting on a fabricated 0) and mark the limit ``unknown``, so the /dti card agrees with the honest
    snapshot gate. Applied at the API boundary rather than in :func:`build_dti_calculation` because the
    snapshot path (``calculations_section.map_dti``) re-gates from the line amounts and needs the computed
    ratio to reach it (its ``back_end_dti is None`` guard means "no income", not "gated"). A no-op when
    the calc is not gated."""
    if not calc.gated:
        return calc
    return calc.model_copy(
        update={
            "front_end_dti": None,
            "back_end_dti": None,
            "limit": calc.limit.model_copy(update={"status": "unknown"}),
        }
    )


def _resolve_limit(
    program: LoanProgram | None, lender_slug: str | None, back_end_pct: Decimal | None
) -> DtiLimit:
    """The effective back-end DTI cap (LP-74's rule + overlay), with pass/over status."""
    if program is None:
        return DtiLimit(
            back_end_max=None, source="unknown", lender_slug=None, rule_id=None, status="unknown"
        )
    rules = default_registry().resolve(program=program, lender_slug=lender_slug)
    rule_id = _BACK_END_RULE_IDS.get(program)
    rule = next((r for r in rules if r.rule_id == rule_id), None)
    if rule is None:
        return DtiLimit(
            back_end_max=None, source="unknown", lender_slug=None, rule_id=rule_id, status="unknown"
        )
    cap = rule.condition.value
    status = "unknown" if back_end_pct is None else "pass" if back_end_pct <= cap else "over"
    return DtiLimit(
        back_end_max=cap,
        source="overlay" if rule.overlay_applied else "program_default",
        lender_slug=rule.overlay_applied,
        rule_id=rule.rule_id,
        status=status,
    )


async def _lender_slug(db: AsyncSession, loan_file: LoanFile) -> str | None:
    if loan_file.lender_id is None:
        return None
    lender = await db.get(Lender, loan_file.lender_id)
    return lender.slug if lender is not None else None


# --------------------------------------------------------------------------- #
# Overrides — set / clear, persisted + audited
# --------------------------------------------------------------------------- #


class UnknownDtiFieldError(Exception):
    """The override field_key does not match any current calculator input."""


async def _auto_amount_for(db: AsyncSession, loan_file: LoanFile, field_key: str) -> Decimal | None:
    """The auto-populated value for one field_key (for the audit's prior value)."""
    autos = (
        await _auto_income_lines(db, loan_file.id)
        + await _auto_housing_lines(db, loan_file)
        + await _auto_debt_lines(db, loan_file.id)
    )
    for auto in autos:
        if auto.key == field_key:
            return auto.auto
    raise UnknownDtiFieldError(field_key)


async def set_dti_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    field_key: str,
    data: DtiOverrideInput,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> DtiCalculation:
    """Set (or revive) an override on one DTI input field, audited; then recompute.

    Validates the field against the current inputs, records the prior value
    (override-or-auto) in the activity log, upserts the override row (precedence +
    persistence), and returns the recomputed calculation (at the caller's aggression
    cutoff, LP-79). Raises :class:`UnknownDtiFieldError` for an unknown field.
    """
    prior_auto = await _auto_amount_for(db, loan_file, field_key)  # also validates the key

    existing = await _get_override_row(db, loan_file.id, field_key)
    prior_value = existing.value if existing is not None and not existing.is_deleted else prior_auto
    if existing is not None:
        existing.value = data.amount
        existing.note = data.note
        existing.actor_user_id = actor_user_id
        existing.deleted_at = None
    else:
        db.add(
            DtiOverride(
                loan_file_id=loan_file.id,
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
        activity_type=ActivityType.DTI_OVERRIDDEN,
        summary=f"DTI input overridden: {field_key}",
        actor_user_id=actor_user_id,
        detail={
            "field_key": field_key,
            "from": _money_str(prior_value),
            "to": _money_str(data.amount),
            "note": data.note,
        },
    )
    return await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)


async def clear_dti_override(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    field_key: str,
    actor_user_id: UUID,
    confidence_cutoff: float = DEFAULT_CONFIDENCE_CUTOFF,
) -> DtiCalculation:
    """Clear an override (revert to the auto value), audited; then recompute."""
    existing = await _get_override_row(db, loan_file.id, field_key)
    if existing is None or existing.is_deleted:
        return await build_dti_calculation(
            db, loan_file=loan_file, confidence_cutoff=confidence_cutoff
        )
    prior = existing.value
    existing.deleted_at = utcnow()
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DTI_OVERRIDDEN,
        summary=f"DTI override cleared: {field_key}",
        actor_user_id=actor_user_id,
        detail={"field_key": field_key, "from": _money_str(prior), "to": None, "cleared": True},
    )
    return await build_dti_calculation(db, loan_file=loan_file, confidence_cutoff=confidence_cutoff)


async def _get_override_row(
    db: AsyncSession, loan_file_id: UUID, field_key: str
) -> DtiOverride | None:
    """The override row for a (file, field_key), including a soft-deleted one."""
    stmt = select(DtiOverride).where(
        DtiOverride.loan_file_id == loan_file_id, DtiOverride.field_key == field_key
    )
    return (await db.execute(stmt)).scalars().first()


def _money_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
