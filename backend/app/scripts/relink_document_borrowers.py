"""Re-run borrower matching over documents already extracted (bug-001).

WHY THIS EXISTS. Borrower linking happens ONCE, in `process_document`, at the moment the extraction
succeeds — `assign_document_borrower_links` is never called again, and re-running verification does
not re-link. So a fix to the MATCHER only reaches documents uploaded AFTER it deploys: every file
already in the system keeps the links (or the absences) the old matcher produced.

bug-001 made that concrete. On a real submission the application spelled the borrower's given name
`Vidulasrri` and every pay stub, W-2 and bank statement printed `VIDULA SRRI` — the matcher rejected
the space and linked 2 of 13 documents. Roughly fifteen per-borrower rules then reported a
documentation gap ("no income documents are currently attributed to this borrower") on a file
carrying two W-2s. Deploying the matcher fix alone would have left that file exactly as it was.

NO RE-EXTRACTION. `assign_document_borrower_links` reads the document's CURRENT extraction; it does
not call a model. This is a re-match over data already on disk — cheap, and it cannot change any
extracted value.

A ONE-OFF TASK, NOT A MIGRATION, following `backfill_mismo_owned_properties`: it is service logic
over many rows, not DDL.

IDEMPOTENT. The linker opens with an unconditional DELETE for the document and rewrites — a re-match
is authoritative, which is the service's existing contract. Running twice produces the same rows.

⚠️ IT CAN REMOVE LINKS, and that is correct: a document whose links the OLD matcher created wrongly
should lose them. The report names every change in both directions so the write is a decision rather
than a surprise.

⚠️ SKIPS A DOCUMENT WHOSE EXTRACTION FAILED — the same guard `process_document` applies, and for the
same reason (LP-569): the linker's DELETE runs before it looks for names, so a call that succeeds
while finding nothing commits the wipe. A failed extraction is an ABSENCE OF DATA, not a
determination that the document names nobody, and a correctly-linked document must not lose its link
to one.

Usage (as a one-off ECS task)::

    uv run python -m app.scripts.relink_document_borrowers                 # REPORT ONLY
    BACKFILL_APPLY=1 uv run python -m app.scripts.relink_document_borrowers   # write
    RELINK_FILE=LF-ABRS uv run python -m app.scripts.relink_document_borrowers   # one file

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
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.models.document import Document
from app.models.document_borrower_link import DocumentBorrowerLink
from app.models.extraction import ExtractionStatus
from app.models.loan_file import LoanFile
from app.services.document_borrower_links import assign_document_borrower_links

logger = structlog.get_logger(__name__)

_TRUE = {"1", "true", "yes", "on"}


@dataclass
class Outcome:
    """What the run found, so the summary is derived from the work rather than narrated."""

    documents_seen: int = 0
    extraction_failed: int = 0
    unchanged: int = 0
    gained: int = 0
    lost: int = 0
    changed_files: set[str] = field(default_factory=set)
    details: list[str] = field(default_factory=list)


async def _relink(db: AsyncSession, *, apply: bool, only_file: str | None) -> Outcome:
    out = Outcome()

    stmt = (
        select(Document, LoanFile.display_id)
        .join(LoanFile, LoanFile.id == Document.loan_file_id)
        .where(Document.deleted_at.is_(None), Document.is_current.is_(True))
        .options(selectinload(Document.extractions))
        .order_by(LoanFile.display_id, Document.created_at)
    )
    if only_file:
        stmt = stmt.where(LoanFile.display_id == only_file)

    for document, display_id in (await db.execute(stmt)).all():
        out.documents_seen += 1

        current = next((e for e in document.extractions if e.is_current), None)
        if current is None or current.extraction_status is ExtractionStatus.FAILED:
            out.extraction_failed += 1
            continue

        before = set(
            (
                await db.scalars(
                    select(DocumentBorrowerLink.borrower_id).where(
                        DocumentBorrowerLink.document_id == document.id
                    )
                )
            ).all()
        )
        rows = await assign_document_borrower_links(db, document)
        after = {row.borrower_id for row in rows}

        if before == after:
            out.unchanged += 1
            continue
        out.changed_files.add(display_id)
        if len(after) > len(before):
            out.gained += 1
        else:
            out.lost += 1
        method = ", ".join(sorted({str(r.method) for r in rows})) or "none"
        out.details.append(
            f"{display_id}  {document.document_type or 'untyped':<28} "
            f"{len(before)} -> {len(after)} link(s)  [{method}]"
            + ("" if apply else "   (report only — not written)")
        )

    if apply:
        await db.commit()
    else:
        await db.rollback()
    return out


async def _run() -> int:
    apply = os.getenv("BACKFILL_APPLY", "").strip().lower() in _TRUE
    only_file = os.getenv("RELINK_FILE", "").strip() or None

    async with async_session_maker() as db:
        out = await _relink(db, apply=apply, only_file=only_file)

    print("--- bug-001 re-link: document -> borrower ---")
    print(f"mode                     : {'APPLY (committed)' if apply else 'REPORT ONLY'}")
    print(f"scope                    : {only_file or 'every loan file'}")
    print(f"documents seen           : {out.documents_seen}")
    print(f"  links GAINED           : {out.gained}")
    print(f"  links LOST             : {out.lost}")
    print(f"  unchanged              : {out.unchanged}")
    print(f"  skipped (extraction failed): {out.extraction_failed}")
    print(f"  loan files affected    : {len(out.changed_files)}")
    for line in out.details:
        print(f"    {line}")
    if not apply and (out.gained or out.lost):
        print("\nRe-run with BACKFILL_APPLY=1 to write.")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
