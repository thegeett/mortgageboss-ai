"""Validation-aid service (LP-89) — the starter inventory + the verdict capture.

Builds the inventory of EVERY grounded-starter item (each rule LP-82..86 + each calculator
methodology LP-87) joined with the company's recorded verdicts, and records a verdict during
the validation session. HONEST: ``validation_status`` is ``grounded_starter`` unless a verdict
row says otherwise — the absence of a verdict means the item is NOT validated. The verdict
captures Priya's judgment (with attribution); it does not fabricate validation. Company-scoped;
the verdict row itself is the LP-80.5 value-recording audit (actor + timestamps + the value).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.helpers import only_active
from app.models.validation_verdict import ValidationVerdict, VerdictKind
from app.schemas.validation_aid import (
    InventoryItem,
    ValidationInventory,
    VerdictInput,
    VerdictView,
)

# The grounded-starter calculator methodologies (LP-87) — the non-rule starter items. Each is
# a domain-judgment value Priya validates (the constants live in app/services/calculators.py).
_CALCULATOR_ITEMS: list[dict[str, str | None]] = [
    {
        "item_id": "calc.pmi_rate",
        "description": "Conventional PMI annual rate (the real rate is a credit/LTV card)",
        "value": "55",
        "unit": "bps",
        "citation": "PMI rate card (starter placeholder)",
    },
    {
        "item_id": "calc.fha_annual_mip_rate",
        "description": "FHA annual MIP rate (most 30-year borrowers; the rule is the cap)",
        "value": "55",
        "unit": "bps",
        "citation": "HUD Handbook 4000.1 Appendix 1.0 (rate table)",
    },
    {
        "item_id": "calc.fha_retirement_haircut",
        "description": "FHA reserves count only this % of vested retirement balances",
        "value": "60",
        "unit": "percent",
        "citation": "HUD Handbook 4000.1 II.A.4",
    },
    {
        "item_id": "calc.conforming_loan_limit",
        "description": "FHFA conforming baseline loan limit (max-loan constraint)",
        "value": "806500",
        "unit": "usd",
        "citation": "FHFA conforming limit (2025/26 baseline — changes annually + by county)",
    },
    {
        "item_id": "calc.required_reserve_months",
        "description": "Required reserve months (DU/program/property-driven)",
        "value": "2",
        "unit": "months",
        "citation": "DU / program / Eligibility Matrix (starter floor)",
    },
    {
        "item_id": "calc.self_employed_add_backs",
        "description": "Self-employed add-backs averaged over 2 years (Form 1084)",
        "value": "depreciation, depletion, amortization/casualty, business-use-of-home",
        "unit": None,
        "citation": "Fannie Mae Cash Flow Analysis (Form 1084)",
    },
]

_KIND_TO_STATUS = {
    VerdictKind.VALIDATED: "validated",
    VerdictKind.CORRECTED: "corrected",
    VerdictKind.FLAGGED_REMOVE: "flagged_remove",
}


def _rule_items() -> list[InventoryItem]:
    """Every grounded-starter rule (Conventional + FHA + cross-source) as inventory items."""
    from app.verification.cross_source.rules import CROSS_SOURCE_RULES
    from app.verification.rules.conventional import CONVENTIONAL_RULES
    from app.verification.rules.fha import FHA_RULES

    items: list[InventoryItem] = []
    for rule in (*CONVENTIONAL_RULES, *FHA_RULES):
        items.append(
            InventoryItem(
                item_id=rule.rule_id,
                item_kind="rule",
                program=rule.applicability.program.value if rule.applicability.program else None,
                category=rule.category.value,
                description=rule.description,
                value=str(rule.condition.value),
                op=rule.condition.op.value,
                unit=rule.condition.unit,
                citation=rule.source.citation,
                source_type=rule.source.type,
                to_verify=rule.source.to_verify,
                starter=rule.starter,
                validation_status="grounded_starter",
                verdict=None,
            )
        )
    for xrule in CROSS_SOURCE_RULES:
        items.append(
            InventoryItem(
                item_id=xrule.rule_id,
                item_kind="cross_source",
                program=xrule.program.value if xrule.program else None,
                category=xrule.category.value,
                description=xrule.template,
                value=str(xrule.threshold.value) if xrule.threshold else None,
                op=xrule.threshold.op.value if xrule.threshold else None,
                unit=xrule.threshold.unit if xrule.threshold else None,
                citation="Internal (graduated from AI cross-source)",
                source_type="internal",
                to_verify=False,
                starter=xrule.starter,
                validation_status="grounded_starter",
                verdict=None,
            )
        )
    return items


def _calculator_items() -> list[InventoryItem]:
    return [
        InventoryItem(
            item_id=str(item["item_id"]),
            item_kind="calculator",
            program=None,
            category="calculator",
            description=str(item["description"]),
            value=item["value"],
            op=None,
            unit=item["unit"],
            citation=item["citation"],
            source_type="methodology",
            to_verify=True,
            starter=True,
            validation_status="grounded_starter",
            verdict=None,
        )
        for item in _CALCULATOR_ITEMS
    ]


async def _verdicts_by_item(
    db: AsyncSession, company_id: UUID
) -> tuple[dict[str, ValidationVerdict], list[ValidationVerdict]]:
    """The company's verdicts keyed by item_id, plus the ADD_NEW proposals (item_id null)."""
    stmt = only_active(
        select(ValidationVerdict).where(ValidationVerdict.company_id == company_id),
        ValidationVerdict,
    )
    rows = (await db.execute(stmt)).scalars().all()
    by_item = {r.item_id: r for r in rows if r.item_id is not None}
    additions = [r for r in rows if r.kind is VerdictKind.ADD_NEW]
    return by_item, additions


def _verdict_view(v: ValidationVerdict) -> VerdictView:
    return VerdictView(
        kind=v.kind.value,
        corrected_value=v.corrected_value,
        title=v.title,
        note=v.note,
        recorded_at=v.updated_at.isoformat() if v.updated_at else None,
    )


async def build_inventory(db: AsyncSession, *, company_id: UUID) -> ValidationInventory:
    """The full grounded-starter inventory + the company's recorded verdicts (LP-89)."""
    items = _rule_items() + _calculator_items()
    by_item, additions = await _verdicts_by_item(db, company_id)

    counts = {"validated": 0, "corrected": 0, "flagged_remove": 0}
    for item in items:
        verdict = by_item.get(item.item_id)
        if verdict is not None:
            item.validation_status = _KIND_TO_STATUS.get(verdict.kind, "grounded_starter")
            item.verdict = _verdict_view(verdict)
            if item.validation_status in counts:
                counts[item.validation_status] += 1

    grounded = sum(1 for i in items if i.validation_status == "grounded_starter")
    return ValidationInventory(
        total=len(items),
        grounded_starter=grounded,
        validated=counts["validated"],
        corrected=counts["corrected"],
        flagged_remove=counts["flagged_remove"],
        additions=[_verdict_view(a) for a in additions],
        items=items,
    )


async def record_verdict(
    db: AsyncSession,
    *,
    company_id: UUID,
    data: VerdictInput,
    actor_user_id: UUID,
) -> ValidationVerdict:
    """Record (or update) Priya's verdict on an item — the captured judgment (LP-89).

    For a known item (``item_id`` set) the verdict is upserted (one active per company+item).
    For an ADD_NEW proposal (``item_id`` null) a new row is always created. The row IS the
    audit trail (actor + timestamps + the corrected value). ``flush`` only.
    """
    kind = VerdictKind(data.kind)
    existing: ValidationVerdict | None = None
    if data.item_id is not None:
        stmt = select(ValidationVerdict).where(
            ValidationVerdict.company_id == company_id,
            ValidationVerdict.item_id == data.item_id,
        )
        existing = (await db.execute(stmt)).scalars().first()

    if existing is not None:
        existing.kind = kind
        existing.corrected_value = data.corrected_value
        existing.title = data.title
        existing.note = data.note
        existing.recorded_by_user_id = actor_user_id
        existing.deleted_at = None
        await db.flush()
        return existing

    verdict = ValidationVerdict(
        company_id=company_id,
        item_id=data.item_id,
        kind=kind,
        corrected_value=data.corrected_value,
        title=data.title,
        note=data.note,
        recorded_by_user_id=actor_user_id,
    )
    db.add(verdict)
    await db.flush()
    return verdict
