"""Backfill `properties.in_project` / `is_pud` from each file's ORIGINAL MISMO (LP-510).

WHY THIS EXISTS. LP-509-B1 taught the parser to capture `PropertyInProjectIndicator` and `PUDIndicator`,
which is what decides `property.type` when a MISMO export states none — and every export seen so far
states none. But import is ONE-SHOT: a file imported before that change has the two columns NULL, and
re-running verification never re-parses the XML. So on every existing loan file `property.type` stays
absent and CO-1 / CO-3 / CO-4 / IH-7 keep reporting "the property type has not been determined" — four
findings asking a processor for something the file already contains.

The values were never in the database to migrate: they are not in `catch_all` either (checked against a
real export — the property section's leaves are not swept there). What IS retained is the original file,
at `mismo_imports.raw_file_path`, so this re-parses that with the fixed parser.

A ONE-OFF TASK, NOT A MIGRATION, deliberately: this does object-storage I/O per row (network,
credentials, partial failure), which does not belong inside a DDL transaction. It follows the
`bootstrap-admin` / `add-user` / `query` shape — a container override on the migrate task definition.

IDEMPOTENT AND NARROW. It only ever fills a NULL, never overwrites a value, so a re-run repairs what a
partial run missed and changes nothing else. It does not touch `property_type` — the derivation from
these indicators is the tag layer's job (`derived._property_type`), and writing a conclusion into the
column would bake today's rule into the data.

Usage (as a one-off ECS task)::

    uv run python -m app.scripts.backfill_mismo_property_indicators           # REPORT ONLY
    BACKFILL_APPLY=1 uv run python -m app.scripts.backfill_mismo_property_indicators   # write

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
from app.models.loan_file import LoanFile
from app.models.mismo_import import MismoImport
from app.models.property import Property
from app.storage import get_storage_backend

logger = structlog.get_logger(__name__)

_TRUE = {"1", "true", "yes", "on"}


@dataclass
class Outcome:
    """What the run found, so the printed summary is derived from the work rather than narrated."""

    imports_seen: int = 0
    no_raw_file: int = 0
    unreadable: int = 0
    no_property: int = 0
    already_set: int = 0
    parser_states_nothing: int = 0
    filled: int = 0
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

        prop = await db.scalar(
            select(Property).where(
                Property.loan_file_id == mismo_import.loan_file_id,
                Property.deleted_at.is_(None),
            )
        )
        if prop is None:
            out.no_property += 1
            continue
        if prop.in_project is not None and prop.is_pud is not None:
            out.already_set += 1
            continue

        try:
            raw = await storage.read(mismo_import.raw_file_path)
            parsed = parse_mismo(raw)
        except Exception as exc:  # one bad file must not stop the batch
            out.unreadable += 1
            out.details.append(f"{display_id}: could not re-parse ({type(exc).__name__}: {exc})")
            continue

        parsed_property = parsed.property
        in_project = getattr(parsed_property, "in_project", None) if parsed_property else None
        is_pud = getattr(parsed_property, "is_pud", None) if parsed_property else None
        if in_project is None and is_pud is None:
            # The export genuinely states neither. Recorded, not treated as a failure — some do not.
            out.parser_states_nothing += 1
            out.details.append(f"{display_id}: the export states neither indicator")
            continue

        # Fill ONLY what is missing. A value already in the column wins over the re-parse, so a manual
        # correction is never silently reverted by re-running this.
        if prop.in_project is None and in_project is not None:
            prop.in_project = in_project
        if prop.is_pud is None and is_pud is not None:
            prop.is_pud = is_pud
        out.filled += 1
        out.details.append(
            f"{display_id}: in_project={in_project} is_pud={is_pud}"
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

    print("--- LP-510 backfill: properties.in_project / is_pud ---")
    print(f"mode                     : {'APPLY (committed)' if apply else 'REPORT ONLY'}")
    print(f"mismo imports seen       : {out.imports_seen}")
    print(f"  filled                 : {out.filled}")
    print(f"  already set            : {out.already_set}")
    print(f"  export states neither  : {out.parser_states_nothing}")
    print(f"  no raw file retained   : {out.no_raw_file}")
    print(f"  could not re-parse     : {out.unreadable}")
    print(f"  no property row        : {out.no_property}")
    if out.details:
        print("\ndetail:")
        for line in out.details:
            print(f"  {line}")
    if not apply and out.filled:
        print("\nNothing was written. Re-run with BACKFILL_APPLY=1 to commit.")
    # A file that could not be re-parsed is the one case worth a non-zero exit: it is the only outcome
    # that leaves a gap this task was meant to close and that a re-run will not fix by itself.
    return 1 if out.unreadable else 0


def main() -> None:
    try:
        sys.exit(asyncio.run(_run()))
    except KeyboardInterrupt:  # pragma: no cover - operator interrupt
        sys.exit(130)


if __name__ == "__main__":
    main()
