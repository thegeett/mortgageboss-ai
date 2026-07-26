"""Stage-1 reviewable artifact (LP-210) — the real LF-6T3N snapshot as JSON.

Runs the full pipeline on a REAL loan file (default LF-6T3N) and writes its snapshot
to ``docs/tickets/LP-210-<DISPLAY_ID>-snapshot.json`` (pretty-printed) for human
eyeball review of faithfulness.

**This artifact contains real borrower NPI** — full names, date of birth, and the
financial profile are surfaced in the clear by design (only SSN/account NUMBERS are
masked to last-4 via ``PiiField``). It is therefore **git-ignored — NEVER commit it**;
generate it locally for review and discard. The write is refused if a raw SSN or
long-account-number pattern leaks (a masking-failure backstop — NOT a "no PII" claim).

Because the LP-202 matcher is not yet wired into the pipeline (a flagged Stage-1
gap), this script runs it EXPLICITLY first (calling the existing LP-202 service, not
new pipeline logic) so ``belongs_to`` is populated. It **writes to the DB** (borrower
links) — refused when ``settings.is_production``; run against a scratch/dev DB.

    uv run python -m app.scripts.stage1_artifact [DISPLAY_ID]
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.document import Document
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.services.document_borrower_links import assign_document_borrower_links
from app.verification.snapshot.builder import build_snapshot

# A fixed run_id so re-running is stable (modulo created_at). Non-nil (LP-208 rejects nil).
_ARTIFACT_RUN_ID = UUID("00000000-0000-0000-0000-0000000a1210")
# A raw SSN or a bare long-digit run (an unmasked account number) — the masking-failure
# backstop. NOT a full-PII scan: names / DOB are surfaced in the clear by design.
_RAW_PII = re.compile(r"\d{3}-\d{2}-\d{4}|\b\d{9,}\b")
# The keyed match-hash (``v1:<hex>``) legitimately contains digit runs — strip ONLY those
# hash values before the scan, anchored on the ``v1:`` prefix so a bare 16+ digit account
# number is NOT stripped (a broad ``[0-9a-f]{16,}`` strip would hide exactly that leak).
_MATCH_HASH = re.compile(r"v1:[0-9a-f]+")


async def _run_matcher(db: AsyncSession, loan_file_id: UUID) -> int:
    """Populate document→borrower links via the existing LP-202 service (not new logic)."""
    documents = (
        (
            await db.execute(
                only_active(
                    select(Document).where(
                        Document.loan_file_id == loan_file_id, Document.is_current.is_(True)
                    ),
                    Document,
                ).options(selectinload(Document.extractions))
            )
        )
        .scalars()
        .all()
    )
    linked = 0
    for document in documents:
        rows = await assign_document_borrower_links(db, document)
        linked += len(rows)
    return linked


async def main(display_id: str = "LF-6T3N") -> None:
    if settings.is_production:  # this script WRITES borrower links — never in prod
        raise SystemExit("refusing to run in production (this script writes to the DB)")
    async with async_session_maker() as db:
        loan_file = (
            await db.execute(
                only_active(select(LoanFile).where(LoanFile.display_id == display_id), LoanFile)
            )
        ).scalar_one_or_none()
        if loan_file is None:
            raise SystemExit(f"no active loan file {display_id!r}")

        linked = await _run_matcher(db, loan_file.id)
        await db.commit()

        snapshot = await build_snapshot(
            db, loan_file_id=loan_file.id, run_id=_ARTIFACT_RUN_ID, company_id=loan_file.company_id
        )

    dumped = snapshot.model_dump(mode="json")
    blob = json.dumps(dumped)
    leak = _RAW_PII.search(_MATCH_HASH.sub("", blob))  # strip only the v1: hash values
    if leak:
        raise SystemExit(f"REFUSING to write artifact — raw PII pattern present: {leak.group()!r}")

    out = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "tickets"
        / f"LP-210-{display_id}-snapshot.json"
    )
    out.write_text(json.dumps(dumped, indent=2, sort_keys=True) + "\n")

    resolved = sum(1 for e in snapshot.documents.entries if e.belongs_to)
    print(f"{display_id}: wrote {out.relative_to(Path(__file__).resolve().parents[3])}")
    print(f"  matcher linked {linked} (document,borrower) pairs")
    print(f"  mismo facts: {len(snapshot.mismo.facts)}")
    print(f"  documents: {len(snapshot.documents.entries)} ({resolved} with a resolved borrower)")
    print(f"  calculations present: {snapshot.calculations.is_present}")
    print("  SSN/account NUMBERS masked; names + DOB in the clear — git-ignored, do NOT commit")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
