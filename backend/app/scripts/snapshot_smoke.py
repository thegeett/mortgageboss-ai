"""Real-file smoke for the whole snapshot builder (LP-208).

Builds the COMPLETE snapshot for a real loan file (default LF-6T3N) — the first time
all three sections exist together — and prints it with PII masked. Read-only; run
manually:

    uv run python -m app.scripts.snapshot_smoke [DISPLAY_ID]

NOTE: needs this branch's schema (documents + calculations read extractions; the dev
DB is stamped at a ``phase3_5_1`` revision lacking LP-201's ``extractions.confidence``
columns), so this errors there until the branch's migrations are applied. The
DB-backed pytest suite (test DB via ``create_all``) is the schema-correct coverage.
"""

import asyncio
import sys
from uuid import uuid4

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.pii import PiiField


def _fmt(value: object) -> str:
    if isinstance(value, PiiField):
        return f"PII(display={value.display}, hash={value.match_hash})"
    return f"{getattr(value, 'value', value)!r} [conf={getattr(value, 'confidence', None)}]"


async def main(display_id: str = "LF-6T3N") -> None:
    async with async_session_maker() as db:
        loan_file = (
            await db.execute(
                only_active(select(LoanFile).where(LoanFile.display_id == display_id), LoanFile)
            )
        ).scalar_one_or_none()
        if loan_file is None:
            raise SystemExit(f"no active loan file {display_id!r}")
        snap = await build_snapshot(
            db, loan_file_id=loan_file.id, run_id=uuid4(), company_id=loan_file.company_id
        )

    print(f"snapshot v{snap.snapshot_version}  loan_file={snap.loan_file_id}  run={snap.run_id}")
    print(f"created_at={snap.created_at.isoformat()}")

    print(
        f"\nMISMO  present={snap.mismo.is_present} reason={snap.mismo.reason} ({len(snap.mismo.facts)} facts)"
    )
    for key in sorted(snap.mismo.facts):
        print(f"  {key} = {_fmt(snap.mismo.facts[key])}")

    print(
        f"\nDOCUMENTS  present={snap.documents.is_present} reason={snap.documents.reason} ({len(snap.documents.entries)})"
    )
    for entry in snap.documents.entries:
        refs = None if entry.belongs_to is None else [r.name for r in entry.belongs_to]
        print(f"  [{entry.document_type}] belongsTo={refs} ({len(entry.fields)} fields)")

    print(
        f"\nCALCULATIONS  present={snap.calculations.is_present} reason={snap.calculations.reason}"
    )
    for name in ("dti", "ltv", "mi", "reserves"):
        entry = getattr(snap.calculations, name)
        print(f"  {name} = {'None' if entry is None else entry.value}")
    print("\nOK — whole snapshot built")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
