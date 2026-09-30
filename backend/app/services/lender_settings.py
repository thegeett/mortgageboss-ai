"""Lender settings for conditions (LP-925, S3-11): entered once per lender, used on every file.

The mortgagee clause (the column, used in insurance emails), the upload cutoff, what the upload asks per
condition, who does what at this lender, and the lender's codes seen on sheets but not yet in the library.
`lender_condition_settings` (LP-920) reads the same `condition_settings` keys this writes, so a change
here is what the next plan, draft and package use.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conditions.library import load_library
from app.models.condition import Condition
from app.models.condition_round import ConditionRound
from app.models.lender import Lender
from app.models.lender_condition_code import LenderCodeStatus, LenderConditionCode

UPLOAD_FIELDS = ("note", "name_of_source", "date_verified")


class SettingsRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def settings_for(db: AsyncSession, *, lender: Lender) -> dict[str, Any]:
    """The lender's condition settings as S3-11 shows them: stored, else the canonical defaults."""
    from app.services.condition_plan import lender_condition_settings

    current = asdict(lender_condition_settings(lender))
    clause = lender.mortgagee_clause
    from_letter = False
    if not clause:
        clause = await _clause_from_letters(db, lender)
        from_letter = clause is not None
    return {
        "mortgagee_clause": clause,
        "clause_from_letter": from_letter,
        "upload_cutoff": current["upload_cutoff"],
        "upload_cutoff_tz": current["upload_cutoff_tz"],
        "upload_fields": list(current["upload_fields"]),
        "lender_orders_final_inspection": current["lender_orders_final_inspection"],
        "lender_verifies_business_existence": current["lender_verifies_business_existence"],
        "lender_orders_title_insurance_payoffs": current["lender_orders_title_insurance_payoffs"],
        "new_files_lender_processing": current["new_files_lender_processing"],
    }


async def _clause_from_letters(db: AsyncSession, lender: Lender) -> str | None:
    """ "Filled from the approval letter": the newest letter from this lender that printed a clause."""
    rows = (
        await db.execute(
            select(ConditionRound.header)
            .join(Condition, Condition.last_seen_round_id == ConditionRound.id)
            .where(Condition.lender_id == lender.id)
            .order_by(ConditionRound.created_at.desc())
            .limit(20)
        )
    ).scalars()
    for header in rows:
        clause = (header or {}).get("mortgagee_clause")
        if clause:
            return str(clause)
    return None


async def save_settings(db: AsyncSession, *, lender: Lender, data: dict[str, Any]) -> None:
    """Save changes. Flushes; the caller commits."""
    fields = [f for f in data.get("upload_fields") or [] if f in UPLOAD_FIELDS]
    if "note" not in fields:
        raise SettingsRefused("Every lender's upload takes a note per condition.")
    cutoff = data.get("upload_cutoff")
    if cutoff is not None and not _is_time(cutoff):
        raise SettingsRefused("The upload cutoff is a time like 20:00.")
    lender.condition_settings = {
        "upload_cutoff": cutoff,
        "upload_cutoff_tz": data.get("upload_cutoff_tz") or "America/New_York",
        "upload_fields": fields,
        "lender_orders_final_inspection": bool(data.get("lender_orders_final_inspection")),
        "lender_verifies_business_existence": bool(data.get("lender_verifies_business_existence")),
        "lender_orders_title_insurance_payoffs": bool(
            data.get("lender_orders_title_insurance_payoffs")
        ),
        "new_files_lender_processing": bool(data.get("new_files_lender_processing")),
    }
    clause = (data.get("mortgagee_clause") or "").strip()
    lender.mortgagee_clause = clause or None
    await db.flush()


def _is_time(value: str) -> bool:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        return False
    return True


async def codes_to_review(db: AsyncSession, *, lender: Lender) -> list[dict[str, Any]]:
    """Codes seen on this lender's sheets that a person has to give a meaning (or already has)."""
    rows = list(
        (
            await db.execute(
                select(LenderConditionCode)
                .where(
                    LenderConditionCode.lender_id == lender.id,
                    LenderConditionCode.status.in_(
                        (LenderCodeStatus.OBSERVED_UNMAPPED, LenderCodeStatus.MAPPED)
                    ),
                )
                .order_by(LenderConditionCode.last_seen_at.desc(), LenderConditionCode.code)
            )
        ).scalars()
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        example = (
            await db.execute(
                select(Condition.verbatim_text)
                .where(Condition.lender_id == lender.id, Condition.lender_code == row.code)
                .order_by(Condition.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        files = await db.scalar(
            select(func.count(func.distinct(Condition.loan_file_id))).where(
                Condition.lender_id == lender.id, Condition.lender_code == row.code
            )
        )
        out.append(
            {
                "code": row.code,
                "example_wording": (example or row.label or "")[:300],
                "files": int(files or 0),
                "canonical_type_id": row.canonical_type_id,
            }
        )
    return out


async def map_code(
    db: AsyncSession, *, lender: Lender, code: str, canonical_type_id: str | None
) -> None:
    """She gives a code its meaning: new imports use it from then on (existing conditions keep theirs)."""
    if canonical_type_id is not None and load_library().get(canonical_type_id) is None:
        raise SettingsRefused(f"{canonical_type_id} is not a type in the library.")
    row = (
        await db.execute(
            select(LenderConditionCode).where(
                LenderConditionCode.lender_id == lender.id, LenderConditionCode.code == code
            )
        )
    ).scalar_one_or_none()
    if row is None or row.status is LenderCodeStatus.SEEDED:
        raise SettingsRefused("That code is not one waiting for review.")
    row.canonical_type_id = canonical_type_id
    row.status = (
        LenderCodeStatus.MAPPED if canonical_type_id else LenderCodeStatus.OBSERVED_UNMAPPED
    )
    row.last_seen_at = row.last_seen_at or datetime.now(UTC)
    await db.flush()


def library_types() -> list[dict[str, str]]:
    return [
        {"id": t.id, "name": t.name, "label": t.label}
        for t in sorted(load_library().types.values(), key=lambda t: t.id)
    ]
