"""Backfill the stated EMPLOYMENT record from each file's original MISMO (LP-624).

WHY THIS EXISTS. LP-624 taught the parser to read the whole `EMPLOYMENT` block — status,
self-employment, classification, position, start and end dates, monthly income — where before it read
only `FullName` and let the rest fall to `catch_all`, which the snapshot does not read. Import is
ONE-SHOT: a file imported before that change has employer rows carrying a name and nothing else, and
re-running verification never re-parses the XML. So on every existing loan file IN-4 keeps abstaining
for want of dates the application states, IN-7 cannot judge a job change that happened, and the needs
AI keeps inferring self-employment a `false` indicator would settle.

The same situation and the same remedy as `backfill_mismo_owned_properties` (LP-596), which is the
ticket that fixed the identical defect one section over.

DIFFERENT FROM LP-596 IN ONE WAY, and it matters: that backfill skipped a file with ANY existing row,
because a partial real-estate schedule is worse than none. Here the rows ALREADY EXIST and are merely
empty, so skipping on presence would skip every file. This UPDATES the existing rows in place, matched
by employer name, and writes only the columns LP-624 added — it never creates, deletes or renames an
employer, so a file whose names have been edited keeps them.

A ONE-OFF TASK, NOT A MIGRATION: it does object-storage I/O per row (network, credentials, partial
failure), which does not belong inside a DDL transaction.

Usage (as a one-off ECS task)::

    uv run python -m app.scripts.backfill_stated_employment           # REPORT ONLY
    BACKFILL_APPLY=1 uv run python -m app.scripts.backfill_stated_employment   # write

Report-only by default: it prints exactly what it would change, so the write is a second, deliberate
step rather than a side effect of looking.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.mismo.parser import parse_mismo
from app.models.borrower import Borrower
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.mismo_import import MismoImport
from app.models.stated_financials import StatedEmployer
from app.storage import get_storage_backend

logger = structlog.get_logger(__name__)

_TRUE = {"1", "true", "yes", "on"}


@dataclass
class Outcome:
    """What the run found, so the printed summary is derived from the work rather than narrated."""

    imports_seen: int = 0
    no_raw_file: int = 0
    unreadable: int = 0
    no_employment_stated: int = 0
    already_filled: int = 0
    updated_files: int = 0
    updated_rows: int = 0
    unmatched_names: int = 0
    details: list[str] = field(default_factory=list)


def _is_filled(row: StatedEmployer) -> bool:
    """Whether this row already carries LP-624's fields, so a re-run is a no-op."""
    return any(
        value is not None
        for value in (row.start_date, row.end_date, row.self_employed, row.position)
    )


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

        try:
            raw = await storage.read(mismo_import.raw_file_path)
            parsed = parse_mismo(raw)
        except Exception as exc:  # one bad file must not stop the batch
            out.unreadable += 1
            out.details.append(f"{display_id}: could not re-parse ({type(exc).__name__}: {exc})")
            continue

        stated = [e for pb in parsed.borrowers for e in pb.employers if e.name]
        if not stated:
            out.no_employment_stated += 1
            continue

        existing = (
            await db.scalars(
                only_active(
                    select(StatedEmployer)
                    .join(Borrower, StatedEmployer.borrower_id == Borrower.id)
                    .where(Borrower.loan_file_id == mismo_import.loan_file_id),
                    StatedEmployer,
                )
            )
        ).all()
        if existing and all(_is_filled(row) for row in existing):
            out.already_filled += 1
            continue

        # Matched by NAME, which is the only thing both sides carry. A name the export no longer states
        # is left exactly as it is rather than guessed at by position — an employer edited by a
        # processor must not be overwritten from a stale export.
        by_name = {(e.name or "").strip().casefold(): e for e in stated}
        touched = 0
        for row in existing:
            source = by_name.get((row.employer_name or "").strip().casefold())
            if source is None:
                out.unmatched_names += 1
                continue
            row.is_current = source.is_current
            row.self_employed = source.self_employed
            row.classification = source.classification
            row.position = source.position
            row.start_date = source.start_date
            row.end_date = source.end_date
            row.monthly_income = source.monthly_income
            row.special_relationship = source.special_relationship
            touched += 1

        if touched:
            await db.flush()
            out.updated_files += 1
            out.updated_rows += touched
            current = sum(1 for e in stated if e.is_current)
            out.details.append(
                f"{display_id}: {touched} employment record(s) filled ({current} current)"
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

    print("--- LP-624 backfill: stated employment record ---")
    print(f"mode                       : {'APPLY (committed)' if apply else 'REPORT ONLY'}")
    print(f"mismo imports seen         : {out.imports_seen}")
    print(f"  files updated            : {out.updated_files}  ({out.updated_rows} rows)")
    print(f"  already filled           : {out.already_filled}")
    print(f"  export states no employer: {out.no_employment_stated}")
    print(f"  name not in export       : {out.unmatched_names}")
    print(f"  no raw file retained     : {out.no_raw_file}")
    print(f"  could not re-parse       : {out.unreadable}")
    for line in out.details:
        print(f"    {line}")
    if not apply and out.updated_files:
        print("\nRe-run with BACKFILL_APPLY=1 to write.")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
