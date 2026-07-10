"""Stage-1 reviewable artifact (LP-210) — the real LF-6T3N snapshot as masked JSON.

Runs the full pipeline on a REAL loan file (default LF-6T3N) and writes its snapshot
to ``docs/tickets/LP-210-<DISPLAY_ID>-snapshot.json`` (pretty-printed, PII masked —
display + match_hash only, never raw) for human eyeball review of faithfulness.

Because the LP-202 matcher is not yet wired into the pipeline (a flagged Stage-1
gap), this script runs it EXPLICITLY first (calling the existing LP-202 service, not
new pipeline logic) so ``belongs_to`` is populated in the artifact. It then builds
the snapshot (LP-208), verifies no raw PII is present, and writes the masked JSON.

    uv run python -m app.scripts.stage1_artifact [DISPLAY_ID]

Writes to the DB (borrower links via the matcher). Run against a scratch/dev DB.
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.models.document import Document
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.services.document_borrower_links import assign_document_borrower_links
from app.verification.snapshot.builder import build_snapshot

# A fixed run_id so re-running produces a byte-identical artifact (modulo created_at).
_ARTIFACT_RUN_ID = UUID("00000000-0000-0000-0000-0000000a1210")
_RAW_PII = re.compile(r"\d{3}-\d{2}-\d{4}|\b\d{9,}\b")


async def _run_matcher(db: object, loan_file_id: object) -> int:
    """Populate document→borrower links via the existing LP-202 service (not new logic)."""
    documents = (
        (
            await db.execute(  # type: ignore[attr-defined]
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
        rows = await assign_document_borrower_links(db, document)  # type: ignore[arg-type]
        linked += len(rows)
    return linked


async def main(display_id: str = "LF-6T3N") -> None:
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
    leak = _RAW_PII.search(re.sub(r"[0-9a-f]{16,}", "", blob))  # ignore hex match-hashes
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
    print("  PII masked, no raw value in the artifact")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "LF-6T3N"))
