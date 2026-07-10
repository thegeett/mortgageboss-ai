"""Snapshot builder / orchestrator (LP-208, ADR-245).

Stitches the three Stage-1 assemblers into one frozen LP-204 ``Snapshot``:
``load_mismo_section`` (LP-205), ``build_documents_section`` (LP-206), and
``build_calculations_section`` (LP-207). It calls them, wraps their outputs into
the three sections, stamps metadata, and returns the frozen snapshot.

**Stateless.** Rebuilt from scratch each call — no caching, no mutation of source
data, no side effects (persistence is LP-209). ``run_id`` is **received**, not
minted — a verification run supplies it; the builder never creates run identity.

**Resilient + honest (the partial-failure policy).** One section failing must not
lose the whole snapshot, and a failure must never be swallowed or faked:

* a section that builds → **present** (populated, or a valid **present-empty** one
  — e.g. a file with no documents is a present, empty documents section, not an
  error and not absent);
* a section whose assembler **raises** → **absent with a PII-safe reason**
  (``Section.failed(reason)``, LP-208's addition to LP-204), never a fabricated
  empty section and never a whole-snapshot failure.

The ``reason`` is metadata-safe — the exception's class name only, never its
message (which could carry borrower data).
"""

from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.base import utcnow
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.verification.snapshot.calculations_section import build_calculations_section
from app.verification.snapshot.documents_section import build_documents_section
from app.verification.snapshot.mismo_section import load_mismo_section
from app.verification.snapshot.model import (
    SNAPSHOT_VERSION,
    CalculationsSection,
    DocumentsSection,
    MismoSection,
    Snapshot,
)

logger = structlog.get_logger(__name__)


class LoanFileNotFound(Exception):
    """Raised when the loan_file_id does not resolve to an active loan file."""


def _reason(section: str, exc: Exception) -> str:
    """A PII-safe failure reason — the exception CLASS only, never its message."""
    return f"{section} assembler raised {type(exc).__name__}"


async def _load_loan_file(db: AsyncSession, loan_file_id: UUID) -> LoanFile:
    """Load the active loan file (with the relationships the calculators may touch)."""
    stmt = only_active(select(LoanFile).where(LoanFile.id == loan_file_id), LoanFile).options(
        selectinload(LoanFile.borrowers),
        selectinload(LoanFile.property),
        selectinload(LoanFile.lender),
    )
    loan_file = (await db.execute(stmt)).scalar_one_or_none()
    if loan_file is None:
        raise LoanFileNotFound(f"no active loan file for id {loan_file_id}")
    return loan_file


async def _mismo(db: AsyncSession, loan_file: LoanFile) -> MismoSection:
    try:
        return MismoSection.present(await load_mismo_section(db, loan_file))
    except Exception as exc:  # resilient: a section failure never loses the snapshot
        logger.warning(
            "snapshot_section_failed",
            section="mismo",
            error=type(exc).__name__,
            loan_file_id=str(loan_file.id),
        )
        return MismoSection.failed(_reason("mismo", exc))


async def _documents(db: AsyncSession, loan_file: LoanFile) -> DocumentsSection:
    try:
        return DocumentsSection.present(await build_documents_section(db, loan_file))
    except Exception as exc:
        logger.warning(
            "snapshot_section_failed",
            section="documents",
            error=type(exc).__name__,
            loan_file_id=str(loan_file.id),
        )
        return DocumentsSection.failed(_reason("documents", exc))


async def _calculations(db: AsyncSession, loan_file: LoanFile) -> CalculationsSection:
    try:
        return await build_calculations_section(db, loan_file)
    except Exception as exc:
        logger.warning(
            "snapshot_section_failed",
            section="calculations",
            error=type(exc).__name__,
            loan_file_id=str(loan_file.id),
        )
        return CalculationsSection.failed(_reason("calculations", exc))


async def build_snapshot(db: AsyncSession, *, loan_file_id: UUID, run_id: UUID) -> Snapshot:
    """Build the frozen per-run snapshot for a loan file (stateless; no persistence).

    ``run_id`` is stamped as received — the builder does not mint run identity. Each
    of the three sections is built independently: a failing assembler yields an
    absent-with-reason section, not a lost snapshot.
    """
    loan_file = await _load_loan_file(db, loan_file_id)

    return Snapshot(
        loan_file_id=loan_file.id,
        run_id=run_id,
        created_at=utcnow(),
        snapshot_version=SNAPSHOT_VERSION,
        mismo=await _mismo(db, loan_file),
        documents=await _documents(db, loan_file),
        calculations=await _calculations(db, loan_file),
    )
