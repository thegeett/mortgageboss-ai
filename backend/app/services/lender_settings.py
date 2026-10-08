"""Lender settings for conditions (LP-925, S3-11): entered once per lender, used on every file.

The mortgagee clause (the column, used in insurance emails), the upload cutoff, what the upload asks per
condition, and who does what at this lender. LP-965 removed the lender's "Codes to review": nothing is
mapped per lender code any more (ADR-419).
`lender_condition_settings` (LP-920) reads the same `condition_settings` keys this writes, so a change
here is what the next plan, draft and package use.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.condition import Condition
from app.models.condition_round import ConditionRound
from app.models.lender import Lender

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
