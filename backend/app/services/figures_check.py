"""The figures check (LP-924): what accepted evidence changes in the file's numbers, proposed, never applied
by itself.

README rule 6: figures change only when she applies them. This module WORKS OUT the change by code —
verified assets from the statements a condition accepted, the monthly insurance from the declarations the
file holds, the housing ratio and DTI from the file's own DTI calculator run with the proposed insurance
as an in-memory override (LP-643's preview path, so the ratio shown is the ratio applying produces) — and
compares the DTI move with Fannie Mae B3-2-10's DU tolerances. `apply` writes through the existing
edits (the stated asset, the DTI calculator's insurance override), each with its own audit.

NOTHING HERE IS STORED UNTIL SHE APPLIES. The proposal is recomputed from the file on every read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity_log import ActivityType
from app.models.condition import Condition
from app.models.condition_evidence import ConditionEvidence
from app.models.condition_item import ConditionItem
from app.models.condition_vocabulary import ConditionItemStatus, EvidenceCheck
from app.models.document import Document
from app.models.loan_file import LoanFile
from app.models.stated_financials import StatedAsset

logger = structlog.get_logger(__name__)

B3_2_10 = "Fannie Mae B3-2-10"
#: S3-09 prints the months with an en dash ("Jul to Aug" joined by one), written as an escape.
_DASH = "\u2013"
#: B3-2-10: DU must be re-run when the DTI rises above this from at or under it …
DTI_CEILING = Decimal("45")
#: … or rises by this many percentage points or more.
DTI_POINTS = Decimal("3")
#: Reserves short of what DU required and below this share of it.
RESERVES_SHARE = Decimal("0.90")
_DEPOSITORY = frozenset({"checkingaccount", "savingsaccount", "checking", "savings"})

ASSETS = "verified_assets"
INSURANCE = "monthly_insurance"
HOUSING_RATIO = "housing_ratio"
DTI = "dti"


class FiguresChanged(Exception):
    """What she saw is no longer what the file would get."""


@dataclass(frozen=True)
class Change:
    """One row of S3-09's table. `applies` is False for the ratios, which follow from the others."""

    key: str
    label: str
    in_file: Decimal | None
    from_evidence: Decimal
    source: str
    unit: str  # "money" | "percent"
    applies: bool
    condition_codes: tuple[str, ...] = ()
    note: str | None = None


@dataclass
class FiguresCheck:
    changes: list[Change] = field(default_factory=list)
    #: S3-09's "Assets now cover closing": (verified, required), when both are known.
    covers: tuple[Decimal, Decimal] | None = None
    du_rerun: bool = False
    du_reasons: list[str] = field(default_factory=list)
    #: Tolerances the file could not check (no input), said rather than assumed passed.
    du_not_checked: list[str] = field(default_factory=list)

    @property
    def applicable(self) -> list[Change]:
        return [change for change in self.changes if change.applies]


def du_rerun_reasons(
    *,
    old_dti: Decimal | None,
    new_dti: Decimal | None,
    income_used: Decimal | None = None,
    income_verified: Decimal | None = None,
    reserves_required: Decimal | None = None,
    reserves_verified: Decimal | None = None,
) -> tuple[list[str], list[str]]:
    """B3-2-10 by code: `(reasons DU must be re-run, tolerances not checked)`. Pure.

    The plan's Done-when examples (§5 LP-924): 44% → 46% needs a re-run (it crosses 45%); 46% → 48% does
    not (already over 45%, and up 2 points). Whether B3-2-10 treats 45% as a crossing or a level is
    STOP AND ASK 2 in the progress file: this follows the Done-when, which only the crossing satisfies.
    """
    reasons: list[str] = []
    not_checked: list[str] = []
    if old_dti is None or new_dti is None:
        not_checked.append("the DTI (one of the ratios could not be computed)")
    else:
        if old_dti <= DTI_CEILING < new_dti:
            reasons.append(f"the DTI rises above 45% ({old_dti}% → {new_dti}%)")
        if new_dti - old_dti >= DTI_POINTS:
            reasons.append(f"the DTI rises {new_dti - old_dti} points")
    if income_used is not None and income_verified is not None and income_verified < income_used:
        reasons.append("the verified income is lower than the income DU used")
    if (
        reserves_required is not None
        and reserves_verified is not None
        and reserves_verified < reserves_required
        and reserves_verified < reserves_required * RESERVES_SHARE
    ):
        reasons.append("the verified reserves are short of what DU required, and below 90% of it")
    return reasons, not_checked


async def _funds_evidence(
    db: AsyncSession, loan_file_id: UUID
) -> list[tuple[Condition, ConditionItem, list[Document]]]:
    """Items that prove funds to close and are DONE, with the documents they accepted."""
    rows = list(
        (
            await db.execute(
                select(ConditionEvidence).where(ConditionEvidence.loan_file_id == loan_file_id)
            )
        ).scalars()
    )
    by_item: dict[UUID, list[ConditionEvidence]] = {}
    for row in rows:
        by_item.setdefault(row.item_id, []).append(row)
    out: list[tuple[Condition, ConditionItem, list[Document]]] = []
    for item_id, evidence in by_item.items():
        item = await db.get(ConditionItem, item_id)
        if (
            item is None
            or item.deleted_at is not None
            or item.status is not ConditionItemStatus.DONE
            or EvidenceCheck.COVERS_REQUIRED_FUNDS.value not in (item.checks or [])
        ):
            continue
        condition = await db.get(Condition, item.condition_id)
        if condition is None:
            continue
        documents = list(
            (
                await db.execute(
                    select(Document)
                    .options(selectinload(Document.extractions))
                    .where(
                        Document.id.in_({e.document_id for e in evidence}),
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        out.append((condition, item, documents))
    return out


async def _stated_depository(db: AsyncSession, loan_file_id: UUID) -> list[StatedAsset]:
    return [
        asset
        for asset in (
            await db.execute(
                select(StatedAsset).where(
                    StatedAsset.loan_file_id == loan_file_id, StatedAsset.deleted_at.is_(None)
                )
            )
        ).scalars()
        if (asset.asset_type or "").replace(" ", "").lower() in _DEPOSITORY
    ]


async def _declarations(
    db: AsyncSession, loan_file_id: UUID
) -> tuple[Document, Decimal, date | None] | None:
    """The latest effective homeowners insurance declarations the file holds, and its monthly premium."""
    from app.services.condition_evidence import _date, _decimal, _extraction_data, _value

    documents = (
        await db.execute(
            select(Document)
            .options(selectinload(Document.extractions))
            .where(
                Document.loan_file_id == loan_file_id,
                Document.document_type == "homeowners_insurance",
                Document.deleted_at.is_(None),
            )
        )
    ).scalars()
    best: tuple[Document, Decimal, date | None] | None = None
    for document in documents:
        data = _extraction_data(document) or {}
        annual = _decimal(_value(data, "annual_premium"))
        if annual is None:
            continue
        effective = _date(_value(data, "effective_date"))
        monthly = (annual / 12).quantize(Decimal("0.01"))
        if best is None or (effective or date.min) > (best[2] or date.min):
            best = (document, monthly, effective)
    return best


async def _condition_for_policy(
    db: AsyncSession, loan_file_id: UUID, effective: date | None
) -> Condition | None:
    """The condition whose push-back names this policy's start date (6178 in round 1, LP-934 M2)."""
    if effective is None:
        return None
    conditions = (
        await db.execute(
            select(Condition).where(
                Condition.loan_file_id == loan_file_id, Condition.deleted_at.is_(None)
            )
        )
    ).scalars()
    for condition in conditions:
        push_back = (condition.reading or {}).get("push_back") or {}
        if push_back.get("policy_starts") == effective.isoformat():
            return condition
    return None


async def figures_check(db: AsyncSession, *, loan_file: LoanFile) -> FiguresCheck:
    """S3-09: the changes accepted evidence makes to the file's figures. Reads only."""
    from app.services.condition_evidence import _extraction_data, _verified, statement_from
    from app.services.dti import HOUSING_INSURANCE, build_dti_calculation

    check = FiguresCheck()

    # --- verified assets (7086) -----------------------------------------------------------
    for condition, _item, documents in await _funds_evidence(db, loan_file.id):
        statements = [(d, statement_from(_extraction_data(d))) for d in documents]
        verified = _verified(statements)
        if verified is None:
            continue
        stated = await _stated_depository(db, loan_file.id)
        in_file = sum((a.value or Decimal("0") for a in stated), Decimal("0")) if stated else None
        required = _required(condition)
        if required is not None:
            check.covers = (verified, required)
        if in_file == verified:
            continue
        latest = max(statements, key=lambda pair: pair[1].end or date.min)[1]
        months = (
            f" {latest.start.strftime('%b')}{_DASH}{latest.end.strftime('%b')}"
            if latest.start and latest.end and latest.start.month != latest.end.month
            else ""
        )
        source = (
            f"{condition.lender_code} · {latest.bank or 'Statement'} ··{latest.last4}{months}"
            if latest.last4
            else f"{condition.lender_code} · statements"
        )
        check.changes.append(
            Change(
                key=ASSETS,
                label="Verified assets",
                in_file=in_file,
                from_evidence=verified,
                source=source,
                unit="money",
                applies=True,
                condition_codes=(condition.lender_code or "",),
            )
        )

    # --- monthly insurance (6178), and the ratios it moves ------------------------------------
    before = await build_dti_calculation(db, loan_file=loan_file)
    insurance_now = next(
        (line.amount for line in before.housing_items if line.key == HOUSING_INSURANCE), None
    )
    declarations = await _declarations(db, loan_file.id)
    extra: dict[str, Decimal] = {}
    if declarations is not None and insurance_now is not None and declarations[1] != insurance_now:
        document, monthly, effective = declarations
        concerned = await _condition_for_policy(db, loan_file.id, effective)
        source = (
            f"{concerned.lender_code} · new declarations page"
            if concerned is not None
            else (document.document_name or "declarations page")
        )
        check.changes.append(
            Change(
                key=INSURANCE,
                label="Monthly homeowners insurance",
                in_file=insurance_now,
                from_evidence=monthly,
                source=source,
                unit="money",
                applies=True,
                condition_codes=(concerned.lender_code or "",) if concerned else (),
                note=str(document.id),
            )
        )
        extra[HOUSING_INSURANCE] = monthly

    after = (
        await build_dti_calculation(db, loan_file=loan_file, extra_overrides=extra)
        if extra
        else before
    )
    old_front, new_front = before.front_end_dti, after.front_end_dti
    old_back, new_back = before.back_end_dti, after.back_end_dti
    if extra and old_front is not None and new_front is not None and old_front != new_front:
        check.changes.append(
            Change(
                HOUSING_RATIO, "Housing ratio", old_front, new_front, "computed", "percent", False
            )
        )
    if extra and old_back is not None and new_back is not None and old_back != new_back:
        delta = new_back - old_back
        check.changes.append(
            Change(
                DTI,
                "Debt-to-income (DTI)",
                old_back,
                new_back,
                f"computed · {'+' if delta >= 0 else ''}{delta} points",
                "percent",
                False,
            )
        )
    reasons, not_checked = du_rerun_reasons(old_dti=old_back, new_dti=new_back)
    check.du_rerun = bool(reasons)
    check.du_reasons = reasons
    check.du_not_checked = not_checked if extra else []
    return check


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _required(condition: Condition) -> Decimal | None:
    from app.services.condition_evidence import _decimal

    return _decimal(
        ((condition.reading or {}).get("figures") or {}).get("shortfall", {}).get("required")
    )


async def apply(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    expected: list[dict[str, str]],
    actor_user_id: UUID,
) -> FiguresCheck:
    """ "Apply N changes": only if the file would still get exactly what she saw. Flushes."""
    from app.schemas.dti import DtiOverrideInput
    from app.services.activity_log import log_activity
    from app.services.dti import HOUSING_INSURANCE, set_dti_override
    from app.services.verifications import mark_verification_stale

    check = await figures_check(db, loan_file=loan_file)
    # BOTH SIDES OF EVERY ROW (LP-924 review, F1). The first version compared `from_evidence` only,
    # so a stated figure edited between her reading "$11,062.18 → $41,914.42" and pressing Apply was
    # overwritten without a word. The row she reads is the promise, so the whole row is compared.
    shown = {(row.get("key"), row.get("in_file"), row.get("from_evidence")) for row in expected}
    current = {
        (change.key, _str(change.in_file), str(change.from_evidence)) for change in check.changes
    }
    if not check.applicable or shown != current:
        raise FiguresChanged("The figures changed — look again before applying.")

    codes: list[str] = []
    for change in check.applicable:
        codes.extend(code for code in change.condition_codes if code and code not in codes)
        if change.key == ASSETS:
            await _apply_assets(
                db, loan_file=loan_file, value=change.from_evidence, actor_user_id=actor_user_id
            )
        elif change.key == INSURANCE:
            await set_dti_override(
                db,
                loan_file=loan_file,
                field_key=HOUSING_INSURANCE,
                data=DtiOverrideInput(
                    amount=change.from_evidence,
                    note=f"From the declarations page ({change.source}), applied from the figures check",
                ),
                actor_user_id=actor_user_id,
            )
    count = len(check.applicable)
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_UPDATED,
        summary=f"Applied {count} change{'s' if count != 1 else ''} from accepted evidence"
        + (f" ({', '.join(codes)})" if codes else ""),
        actor_user_id=actor_user_id,
        # Keys and conditions only: the figures are in each edit's own audit line.
        detail={
            "section": "figures_check",
            "keys": [c.key for c in check.applicable],
            "conditions": codes,
        },
    )
    await mark_verification_stale(db, loan_file_id=loan_file.id)
    await db.flush()
    logger.info("figures_check_applied", loan_file_id=str(loan_file.id), changes=count)
    return await figures_check(db, loan_file=loan_file)


async def _apply_assets(
    db: AsyncSession, *, loan_file: LoanFile, value: Decimal, actor_user_id: UUID
) -> None:
    """Update the one stated depository asset, else add one — the stated-assets edit, with its audit."""
    from app.services.activity_log import audit_value, log_activity

    stated = await _stated_depository(db, loan_file.id)
    if len(stated) == 1:
        asset = stated[0]
        before = asset.value
        asset.value = value
        detail: dict[str, Any] = {
            "section": "stated_asset",
            "action": "edit",
            "changes": [{"field": "value", "from": audit_value(before), "to": audit_value(value)}],
        }
        summary = "Edited a stated asset"
    else:
        asset = StatedAsset(loan_file_id=loan_file.id, asset_type="CheckingAccount", value=value)
        db.add(asset)
        detail = {
            "section": "stated_asset",
            "action": "add",
            "values": {"asset_type": "CheckingAccount", "value": audit_value(value)},
        }
        summary = "Added a stated asset"
    await db.flush()
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_UPDATED,
        summary=summary,
        actor_user_id=actor_user_id,
        detail=detail,
    )


def as_dict(check: FiguresCheck) -> dict[str, Any]:
    return {
        "changes": [
            {
                "key": c.key,
                "label": c.label,
                "in_file": c.in_file,
                "from_evidence": c.from_evidence,
                "source": c.source,
                "unit": c.unit,
                "applies": c.applies,
                "condition_codes": list(c.condition_codes),
            }
            for c in check.changes
        ],
        "apply_count": len(check.applicable),
        "covers": {"verified": check.covers[0], "required": check.covers[1]}
        if check.covers
        else None,
        "du_rerun": check.du_rerun,
        "du_reasons": check.du_reasons,
        "du_not_checked": check.du_not_checked,
        "citation": B3_2_10,
    }
