"""Real-file smoke for the documents section assembler (LP-206).

Builds the ``documents`` section for a real loan file (default LF-6T3N), asserts
each active document is present with its type and no raw PII leaks, and prints it
(PII masked) for eyeball review. Read-only; run manually:

    uv run python -m app.scripts.documents_section_smoke [DISPLAY_ID]

NOTE: requires the DB to carry this branch's schema (LP-201 ``extractions.confidence``
columns, LP-202 ``document_borrower_links``). The current dev DB is stamped at a
``phase3_5_1`` Alembic revision that lacks LP-201's columns, so this will error there
until the branch's migrations are applied — the DB-backed pytest suite (test DB via
``create_all``) is the schema-correct coverage.
"""

import asyncio
import re
import sys

from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.documents_section import build_documents_section
from app.verification.snapshot.pii import PiiField

_RAW_RUN = re.compile(r"\d{9,}")  # a 9+ digit run — a raw account/SSN must never appear


async def main(display_id: str = "LF-6T3N") -> None:
    async with async_session_maker() as db:
        loan_file = (
            await db.execute(
                only_active(select(LoanFile).where(LoanFile.display_id == display_id), LoanFile)
            )
        ).scalar_one_or_none()
        if loan_file is None:
            raise SystemExit(f"no active loan file {display_id!r}")
        entries = await build_documents_section(db, loan_file)

    assert entries, "expected at least one active document"
    for entry in entries:
        assert entry.document_type, "each entry has a document_type"
        for key, value in entry.fields.items():
            if isinstance(value, PiiField):
                continue
            assert not _RAW_RUN.search(str(value.value)), (
                f"raw PII leak at {entry.document_type}.{key}"
            )

    print(f"{display_id}: {len(entries)} active documents")
    for entry in entries:
        refs = (
            "null"
            if entry.belongs_to is None
            else ", ".join(f"{r.name}({str(r.borrower_id)[:8]})" for r in entry.belongs_to)
        )
        print(f"  [{entry.document_type}] belongsTo={refs}  ({len(entry.fields)} fields)")
        for key in sorted(entry.fields):
            value = entry.fields[key]
            if isinstance(value, PiiField):
                print(f"      {key} = PII(display={value.display}, hash={value.match_hash})")
            else:
                print(f"      {key} = {value.value!r}  [conf={value.confidence}]")
    print("OK — no raw PII, every active document present")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
