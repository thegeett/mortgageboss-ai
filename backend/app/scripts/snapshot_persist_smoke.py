"""Real-file smoke for snapshot persistence (LP-209).

Builds (LP-208) + persists + loads the snapshot for a real loan file (default
LF-6T3N), asserts the load equals the build, and prints the stored row's metadata.
Writes to the DB (a new run row) — run against a scratch/dev DB only:

    uv run python -m app.scripts.snapshot_persist_smoke [DISPLAY_ID]

NOTE: needs this branch's schema (LP-201/202/209 migrations). The current dev DB is
stamped at a ``phase3_5_1`` revision lacking them; the DB-backed pytest suite (test
DB via ``create_all``) is the schema-correct coverage.
"""

import asyncio
import sys
from uuid import uuid4

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.persistence import load_snapshot, persist_snapshot


async def main(display_id: str = "LF-6T3N") -> None:
    run_id = uuid4()
    async with async_session_maker() as db:
        loan_file = (
            await db.execute(
                only_active(select(LoanFile).where(LoanFile.display_id == display_id), LoanFile)
            )
        ).scalar_one_or_none()
        if loan_file is None:
            raise SystemExit(f"no active loan file {display_id!r}")

        built = await build_snapshot(
            db, loan_file_id=loan_file.id, run_id=run_id, company_id=loan_file.company_id
        )
        record = await persist_snapshot(db, built)
        await db.commit()
        loaded = await load_snapshot(db, run_id)

    assert loaded == built, "load did not equal build — round-trip is lossy"
    print(
        f"persisted run={record.run_id} loan_file={record.loan_file_id} v{record.snapshot_version}"
    )
    print(f"  mismo facts: {len(built.mismo.facts)} (present={built.mismo.is_present})")
    print(f"  documents: {len(built.documents.entries)} (present={built.documents.is_present})")
    print(f"  calculations present={built.calculations.is_present}")
    print("OK — built, persisted, and loaded == built (PII masked at rest)")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
