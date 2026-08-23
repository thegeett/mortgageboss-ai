"""Backfill `stated_housing_expenses` from each file's ORIGINAL MISMO (LP-627).

WHY THIS EXISTS. LP-627 taught the parser to read HOUSING_EXPENSES — the 1003's proposed PITI
breakdown — and projected it into the snapshot. But import is ONE-SHOT: a file imported before that
change has no rows, and re-running verification never re-parses the XML. So on every existing loan file
the DTI keeps reporting "Property taxes / unknown — missing or unusable input" while the application
states the figure outright. On LF-ABRS that is $541.67 a month, on a ratio sitting at 44.8% against a
45% limit.

The same situation and remedy as `backfill_mismo_owned_properties` (LP-596) and
`backfill_stated_employment` (LP-624) — the third time one mechanism has needed one.

IDEMPOTENT AND NARROW. A loan file that already has rows is SKIPPED entirely, never topped up: a
partial breakdown is worse than none, because a card showing taxes but not insurance reads as complete.

STATED, NOT VERIFIED. These rows never satisfy the fail-closed housing gate; they feed the
unverified-input offer beside the AVM estimate.

Usage (as a one-off ECS task)::

    uv run python -m app.scripts.backfill_stated_housing_expenses           # REPORT ONLY
    BACKFILL_APPLY=1 uv run python -m app.scripts.backfill_stated_housing_expenses   # write
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.mismo.parser import parse_mismo
from app.models.loan_file import LoanFile
from app.models.mismo_import import MismoImport
from app.models.stated_financials import StatedHousingExpense
from app.storage import get_storage_backend

logger = structlog.get_logger(__name__)

_TRUE = {"1", "true", "yes", "on"}


@dataclass
class Outcome:
    """What the run found, so the printed summary is derived from the work rather than narrated."""

    imports_seen: int = 0
    no_raw_file: int = 0
    unreadable: int = 0
    already_present: int = 0
    none_stated: int = 0
    filled_files: int = 0
    filled_rows: int = 0
    details: list[str] = field(default_factory=list)


async def _backfill(db: AsyncSession, *, apply: bool) -> Outcome:
    out = Outcome()
    storage = get_storage_backend()

    rows = (
        await db.execute(
            select(MismoImport, LoanFile.display_id)
            .join(LoanFile, LoanFile.id == MismoImport.loan_file_id)
            .order_by(MismoImport.created_at)
        )
    ).all()

    for mismo_import, display_id in rows:
        out.imports_seen += 1
        if not mismo_import.raw_file_path:
            out.no_raw_file += 1
            out.details.append(f"{display_id}: no raw_file_path — nothing to re-parse")
            continue

        existing = await db.scalar(
            select(func.count())
            .select_from(StatedHousingExpense)
            .where(
                StatedHousingExpense.loan_file_id == mismo_import.loan_file_id,
                StatedHousingExpense.deleted_at.is_(None),
            )
        )
        if existing:
            out.already_present += 1
            continue

        try:
            raw = await storage.read(mismo_import.raw_file_path)
            parsed = parse_mismo(raw)
        except Exception as exc:  # one bad file must not stop the batch
            out.unreadable += 1
            out.details.append(f"{display_id}: could not re-parse ({type(exc).__name__}: {exc})")
            continue

        if not parsed.housing_expenses:
            out.none_stated += 1
            continue

        for expense in parsed.housing_expenses:
            db.add(
                StatedHousingExpense(
                    loan_file_id=mismo_import.loan_file_id,
                    expense_type=expense.expense_type,
                    timing=expense.timing,
                    payment_amount=expense.payment_amount,
                )
            )
        # FLUSH: the session runs autoflush=False, so the count() above would not see these pending
        # inserts and a file with two MismoImport rows would have its breakdown written twice —
        # doubling a housing payment, which is the exact failure the skip-if-present guard prevents.
        await db.flush()
        out.filled_files += 1
        out.filled_rows += len(parsed.housing_expenses)
        tax = next(
            (
                e.payment_amount
                for e in parsed.housing_expenses
                if e.expense_type == "RealEstateTax" and e.timing == "Proposed"
            ),
            None,
        )
        out.details.append(
            f"{display_id}: {len(parsed.housing_expenses)} expense(s)"
            + (f", proposed tax {tax}/mo" if tax is not None else "")
            + ("" if apply else "  (report only — not written)")
        )

    if apply:
        await db.commit()
    else:
        await db.rollback()
    return out


async def _run() -> int:
    apply = os.getenv("BACKFILL_APPLY", "").strip().lower() in _TRUE

    async with async_session_maker() as db:
        out = await _backfill(db, apply=apply)

    print("--- LP-627 backfill: stated housing expenses ---")
    print(f"mode                     : {'APPLY (committed)' if apply else 'REPORT ONLY'}")
    print(f"mismo imports seen       : {out.imports_seen}")
    print(f"  files filled           : {out.filled_files}  ({out.filled_rows} rows)")
    print(f"  already present        : {out.already_present}")
    print(f"  export states none     : {out.none_stated}")
    print(f"  no raw file retained   : {out.no_raw_file}")
    print(f"  could not re-parse     : {out.unreadable}")
    for line in out.details:
        print(f"    {line}")
    if not apply and out.filled_files:
        print("\nRe-run with BACKFILL_APPLY=1 to write.")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
