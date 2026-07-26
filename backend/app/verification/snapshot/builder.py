"""Snapshot builder / orchestrator (LP-208, ADR-245).

Stitches the three Stage-1 assemblers into one frozen LP-204 ``Snapshot``:
``load_mismo_section`` (LP-205), ``build_documents_section`` (LP-206), and
``build_calculations_section`` (LP-207). It calls them, wraps their outputs into
the three sections, stamps metadata, and returns the frozen snapshot.

**Stateless.** Rebuilt from scratch each call — no caching, no mutation of source
data, no side effects (persistence is LP-209). ``run_id`` is **received**, not
minted — a verification run supplies it; the builder never creates run identity.
The loan file is loaded **company-scoped** (``company_id`` is required, not
inferred) — the builder is the tenant boundary for the snapshot.

**Resilient + honest (the partial-failure policy).** One section failing must not
lose the whole snapshot, and a failure must never be swallowed or faked:

* a section that builds → **present** (populated, or a valid **present-empty** one
  — e.g. a file with no documents is a present, empty documents section, not an
  error and not absent);
* a section whose assembler **raises** → **absent with a PII-safe reason**
  (``Section.failed(reason)``, LP-208's addition to LP-204), logged at ERROR,
  never a fabricated empty section and never a whole-snapshot failure.

Each section runs inside its own **SAVEPOINT** (``db.begin_nested()``) so a DB
error in one section rolls back to that savepoint only — it does NOT poison the
shared session and cascade-fail the later sections (which would report misleading
reasons). The outer transaction and the loaded ``loan_file`` stay valid across
sections.

The ``reason`` is metadata-safe — the exception's class name only, never its
message (which could carry borrower data).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.calculations_section import build_calculations_section
from app.verification.snapshot.documents_section import build_documents_section
from app.verification.snapshot.mismo_section import load_mismo_section
from app.verification.snapshot.model import (
    CalculationsSection,
    DocumentsSection,
    MismoSection,
    Snapshot,
)

logger = structlog.get_logger(__name__)


class LoanFileNotFound(Exception):
    """Raised when the loan_file_id does not resolve to an active, in-company loan file."""


def _reason(section: str, exc: Exception) -> str:
    """A PII-safe failure reason — the exception CLASS only, never its message."""
    return f"{section} assembler raised {type(exc).__name__}"


async def _load_loan_file(db: AsyncSession, loan_file_id: UUID, company_id: UUID) -> LoanFile:
    """Load the active, company-scoped loan file (bare row — assemblers query their own data).

    No relationship eager-loads: the assemblers/calculators re-query every collection
    by ``loan_file_id`` and reach the lender via ``db.get(Lender, loan_file.lender_id)``,
    so eager-loading borrowers/property/lender here would be dead round-trips.
    """
    stmt = only_active(
        select(LoanFile).where(LoanFile.id == loan_file_id, LoanFile.company_id == company_id),
        LoanFile,
    )
    loan_file = (await db.execute(stmt)).scalar_one_or_none()
    if loan_file is None:
        raise LoanFileNotFound(f"no active loan file for id {loan_file_id} in company {company_id}")
    return loan_file


async def _build_section[Payload, Section](
    db: AsyncSession,
    *,
    name: str,
    loan_file_id: UUID,
    assemble: Callable[[], Awaitable[Payload]],
    present: Callable[[Payload], Section],
    failed: Callable[[str], Section],
) -> Section:
    """Build one section resiliently: present on success, absent-with-reason on failure.

    Runs the assembler inside a SAVEPOINT so a DB error rolls back only this section
    (never poisons the shared session for the next one). Any exception → an
    ``absent`` section carrying a PII-safe reason, logged at ERROR (a degraded
    section is alert-worthy) — the whole snapshot is never lost.
    """
    try:
        async with db.begin_nested():
            return present(await assemble())
    except Exception as exc:  # resilient: a section failure never loses the snapshot
        logger.error(
            "snapshot_section_failed",
            section=name,
            error=type(exc).__name__,  # class only — never str(exc) (may carry PII)
            loan_file_id=str(loan_file_id),
        )
        return failed(_reason(name, exc))


async def build_snapshot(
    db: AsyncSession, *, loan_file_id: UUID, run_id: UUID, company_id: UUID
) -> Snapshot:
    """Build the frozen per-run snapshot for a loan file (stateless; no persistence).

    ``run_id`` is stamped as received — the builder does not mint run identity — but
    a nil UUID is rejected (an un-attributable run is a caller error). The loan file
    is loaded company-scoped. Each of the three sections is built independently in
    its own savepoint: a failing assembler yields an absent-with-reason section, not
    a lost snapshot and not a cascade into the other sections.
    """
    if run_id.int == 0:
        raise ValueError("run_id must be a real run identity, not the nil UUID")

    loan_file = await _load_loan_file(db, loan_file_id, company_id)

    return Snapshot(
        loan_file_id=loan_file.id,
        run_id=run_id,
        created_at=utcnow(),
        mismo=await _build_section(
            db,
            name="mismo",
            loan_file_id=loan_file.id,
            assemble=lambda: load_mismo_section(db, loan_file),
            present=MismoSection.present,
            failed=MismoSection.failed,
        ),
        documents=await _build_section(
            db,
            name="documents",
            loan_file_id=loan_file.id,
            assemble=lambda: build_documents_section(db, loan_file),
            present=DocumentsSection.present,
            failed=DocumentsSection.failed,
        ),
        calculations=await _build_section(
            db,
            name="calculations",
            loan_file_id=loan_file.id,
            assemble=lambda: build_calculations_section(db, loan_file),
            present=lambda section: section,  # the calculations assembler returns a Section
            failed=CalculationsSection.failed,
        ),
    )
