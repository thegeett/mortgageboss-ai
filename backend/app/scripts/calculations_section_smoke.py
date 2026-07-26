"""Real-file smoke for the calculations section assembler (LP-207).

Invokes the four calculators for a real loan file (default LF-6T3N) and prints the
mapped section — each calculation's value + breakdown (with source tags) or None.
Read-only; run manually:

    uv run python -m app.scripts.calculations_section_smoke [DISPLAY_ID]

NOTE: requires this branch's schema — DTI reads extractions, and the current dev DB
is stamped at a ``phase3_5_1`` revision lacking LP-201's ``extractions.confidence``
columns, so this errors there until the branch's migrations are applied. The
DB-backed pytest suite (test DB via ``create_all``) is the schema-correct coverage.
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.calculations_section import build_calculations_section


async def main(display_id: str = "LF-6T3N") -> None:
    async with async_session_maker() as db:
        loan_file = (
            await db.execute(
                only_active(select(LoanFile).where(LoanFile.display_id == display_id), LoanFile)
            )
        ).scalar_one_or_none()
        if loan_file is None:
            raise SystemExit(f"no active loan file {display_id!r}")
        section = await build_calculations_section(db, loan_file)

    print(f"{display_id}: calculations")
    for name in ("dti", "ltv", "mi", "reserves"):
        entry = getattr(section, name)
        if entry is None:
            print(f"  [{name}] = None (not computed)")
            continue
        print(f"  [{name}] value={entry.value}")
        for line in entry.breakdown:
            print(f"      {line.key} · {line.label} = {line.amount}  [source={line.source}]")
    print("OK")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
