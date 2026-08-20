"""Backfill `stated_owned_properties` from each file's ORIGINAL MISMO (LP-596).

WHY THIS EXISTS. LP-596 taught the parser to read `OWNED_PROPERTY` — the 1003's real-estate-owned
schedule — and projected it into the snapshot, which is what makes it visible to the rule engine at
all. But import is ONE-SHOT: a file imported before that change has no `stated_owned_properties` rows,
and re-running verification never re-parses the XML. So on every existing loan file the schedule stays
absent and AS-4 / DT-6 / DT-8 keep answering from a checkbox or declining to answer, on files whose
application states the fact outright.

This is the same situation, and the same remedy, as `backfill_mismo_property_indicators` (LP-510).
What is retained is the original file, at `mismo_imports.raw_file_path`, so this re-parses that.

A ONE-OFF TASK, NOT A MIGRATION, deliberately: it does object-storage I/O per row (network,
credentials, partial failure), which does not belong inside a DDL transaction. It follows the
`bootstrap-admin` / `add-user` / `query` shape — a container override on the migrate task definition.

IDEMPOTENT AND NARROW. A loan file that ALREADY has rows is skipped entirely — never topped up, never
de-duplicated. Re-running repairs what a partial run missed and changes nothing else. It writes only
`stated_owned_properties`; it does not touch liabilities, properties, or any derived conclusion.

Usage (as a one-off ECS task)::

    uv run python -m app.scripts.backfill_mismo_owned_properties           # REPORT ONLY
    BACKFILL_APPLY=1 uv run python -m app.scripts.backfill_mismo_owned_properties   # write

Report-only by default: it prints exactly what it would change, so the write is a second, deliberate
step rather than a side effect of looking.
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
from app.models.stated_financials import StatedOwnedProperty
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
    schedule_absent: int = 0
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

        # ANY existing row means this file has been done. Deliberately not a top-up: a partial
        # schedule would be worse than none, because a rule counting financed properties would
        # count a subset and report a confident wrong number.
        existing = await db.scalar(
            select(func.count())
            .select_from(StatedOwnedProperty)
            .where(
                StatedOwnedProperty.loan_file_id == mismo_import.loan_file_id,
                StatedOwnedProperty.deleted_at.is_(None),
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

        if not parsed.owned_properties:
            # A purchase with no REO states none, legitimately. Recorded, not a failure.
            out.schedule_absent += 1
            continue

        for owned in parsed.owned_properties:
            db.add(
                StatedOwnedProperty(
                    loan_file_id=mismo_import.loan_file_id,
                    is_subject=owned.is_subject,
                    disposition_status=owned.disposition_status,
                    lien_upb=owned.lien_upb,
                    unit_count=owned.unit_count,
                    rental_income_gross=owned.rental_income_gross,
                    rental_income_net=owned.rental_income_net,
                    current_usage_type=owned.current_usage_type,
                    usage_type=owned.usage_type,
                    estimated_value=owned.estimated_value,
                )
            )
        out.filled_files += 1
        out.filled_rows += len(parsed.owned_properties)
        retained = sum(1 for o in parsed.owned_properties if o.disposition_status == "Retain")
        out.details.append(
            f"{display_id}: {len(parsed.owned_properties)} owned properties ({retained} retained)"
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

    print("--- LP-596 backfill: stated_owned_properties ---")
    print(f"mode                     : {'APPLY (committed)' if apply else 'REPORT ONLY'}")
    print(f"mismo imports seen       : {out.imports_seen}")
    print(f"  files filled           : {out.filled_files}  ({out.filled_rows} rows)")
    print(f"  already present        : {out.already_present}")
    print(f"  export states no REO   : {out.schedule_absent}")
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
