"""What is actually wrong with a loan file, in one line (LP-UI-013).

The pipeline's Attention column answers the question a processor opens the
dashboard to ask: *which of these needs me, and why*. A status alone cannot —
"In processing" is true of a file waiting on nothing and of a file whose pay stub
failed extraction six days ago.

**Why this lives on the server.** The string is derived from four domains
(findings, documents, staleness, needs). Deriving it in the browser would mean
those queries *per row* — forty files, five queries each — so LP-UI-013 asks for
a field on the summary instead. Every lookup here is one aggregate across the
whole page, never one per file: the cost is four queries for a page of any size.

**What it deliberately does not cover.** Two of the mockup's example strings need
machinery that does not exist yet or is too expensive to run per row:
underwriting conditions ("2 lender conditions past due") are Phase 4.5, and the
calculator-derived lines ("Reserves fall short by 1.1 mo", "Appraisal below
contract price") each require running a calculator per file. Both are recorded on
the ticket rather than faked.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.documents.staleness import evaluate_staleness
from app.models.document import Document, DocumentStatus
from app.models.finding import EvaluationOutcome, Finding, FindingResolutionStatus
from app.models.loan_file import LoanFile, LoanFileStatus
from app.models.needs_item import NeedsItem, NeedsItemStatus


class AttentionTone(StrEnum):
    """The four tones the pipeline's left stripe encodes.

    Deliberately the same vocabulary as the frontend's `lib/status.ts` — a
    processor should not learn a fifth meaning for amber on this screen.
    """

    BLOCKING = "blocking"
    ATTENTION = "attention"
    VERIFIED = "verified"
    NEUTRAL = "neutral"


class FileAttention(BaseModel):
    """One row's answer, plus the needs progress the column renders beside it."""

    tone: AttentionTone
    label: str
    needs_total: int
    needs_satisfied: int


# Terminal statuses have nothing to be done about them; saying so calmly is the
# honest answer, not "Clear".
_TERMINAL = {LoanFileStatus.CLOSED, LoanFileStatus.WITHDRAWN}

# A need is satisfied when nobody has to collect anything more for it.
_SATISFIED_NEEDS = {NeedsItemStatus.VERIFIED, NeedsItemStatus.WAIVED}


async def attention_for_files(
    db: AsyncSession, loan_files: Sequence[LoanFile], *, today: date | None = None
) -> dict[UUID, FileAttention]:
    """Derive one `FileAttention` per file, in four queries total."""
    ids = [file.id for file in loan_files]
    if not ids:
        return {}

    blocking = await _open_finding_counts(db, ids)
    needs_total, needs_satisfied = await _needs_progress(db, ids)
    documents = await _current_documents(db, ids)

    return {
        file.id: _decide(
            file,
            blocking=blocking.get(file.id, 0),
            documents=documents.get(file.id, []),
            needs_total=needs_total.get(file.id, 0),
            needs_satisfied=needs_satisfied.get(file.id, 0),
            today=today,
        )
        for file in loan_files
    }


def _decide(
    file: LoanFile,
    *,
    blocking: int,
    documents: list[Document],
    needs_total: int,
    needs_satisfied: int,
    today: date | None,
) -> FileAttention:
    """Pick the single most important thing wrong with one file.

    Ordered by what stops the file moving, not by severity in the abstract: a
    rule that blocks submission outranks a document that failed to read, which
    outranks one that is merely old.
    """
    progress = {"needs_total": needs_total, "needs_satisfied": needs_satisfied}

    if file.status in _TERMINAL:
        label = "Closed" if file.status is LoanFileStatus.CLOSED else "Withdrawn"
        return FileAttention(tone=AttentionTone.NEUTRAL, label=label, **progress)

    if blocking:
        noun = "finding blocks" if blocking == 1 else "findings block"
        return FileAttention(
            tone=AttentionTone.BLOCKING, label=f"{blocking} {noun} submission", **progress
        )

    failed = next((doc for doc in documents if doc.status is DocumentStatus.FAILED), None)
    if failed is not None:
        return FileAttention(
            tone=AttentionTone.ATTENTION,
            label=f"{_document_label(failed)} failed extraction",
            **progress,
        )

    stale = _oldest_stale(documents, today=today)
    if stale is not None:
        document, days = stale
        return FileAttention(
            tone=AttentionTone.ATTENTION,
            label=f"{_document_label(document)} is {days} days old",
            **progress,
        )

    if not documents:
        return FileAttention(tone=AttentionTone.NEUTRAL, label="No documents yet", **progress)

    if needs_total and needs_satisfied < needs_total:
        outstanding = needs_total - needs_satisfied
        noun = "document" if outstanding == 1 else "documents"
        return FileAttention(
            tone=AttentionTone.ATTENTION,
            label=f"Waiting on {outstanding} {noun}",
            **progress,
        )

    return FileAttention(tone=AttentionTone.VERIFIED, label="Nothing outstanding", **progress)


def _document_label(document: Document) -> str:
    """A processor's name for the document, never the raw enum."""
    if document.document_type:
        return document.document_type.replace("_", " ").capitalize()
    return "A document"


def _oldest_stale(
    documents: Sequence[Document], *, today: date | None
) -> tuple[Document, int] | None:
    """The stalest unresolved document and its age in days, or None.

    Staleness is computed rather than stored (`app/documents/staleness.py`), so
    it cannot be a SQL aggregate — it is derived here over the documents already
    loaded for the failed-extraction check, not in a second pass.
    """
    worst: tuple[Document, int] | None = None
    for document in documents:
        extraction = next((e for e in document.extractions if e.is_current), None)
        staleness = evaluate_staleness(document, extraction, today=today)
        if not staleness.is_stale or staleness.as_of_date is None:
            continue
        days = ((today or date.today()) - staleness.as_of_date).days
        if worst is None or days > worst[1]:
            worst = (document, days)
    return worst


async def _open_finding_counts(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, int]:
    """Findings that a rule fired and nobody has dispositioned, per file."""
    stmt = (
        select(Finding.loan_file_id, func.count())
        .where(
            Finding.loan_file_id.in_(ids),
            Finding.deleted_at.is_(None),
            Finding.evaluation_outcome == EvaluationOutcome.OPEN,
            Finding.resolution_status == FindingResolutionStatus.OPEN,
        )
        .group_by(Finding.loan_file_id)
    )
    return {row[0]: row[1] for row in (await db.execute(stmt)).all()}


async def _needs_progress(
    db: AsyncSession, ids: Sequence[UUID]
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    """(total, satisfied) needs per file, from one grouped count."""
    stmt = (
        select(NeedsItem.loan_file_id, NeedsItem.status, func.count())
        .where(NeedsItem.loan_file_id.in_(ids), NeedsItem.deleted_at.is_(None))
        .group_by(NeedsItem.loan_file_id, NeedsItem.status)
    )
    total: dict[UUID, int] = defaultdict(int)
    satisfied: dict[UUID, int] = defaultdict(int)
    for loan_file_id, status, count in (await db.execute(stmt)).all():
        total[loan_file_id] += count
        if status in _SATISFIED_NEEDS:
            satisfied[loan_file_id] += count
    return dict(total), dict(satisfied)


async def _current_documents(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, list[Document]]:
    """Current documents for the page, with the extraction staleness needs."""
    stmt = (
        select(Document)
        .where(
            Document.loan_file_id.in_(ids),
            Document.deleted_at.is_(None),
            Document.is_current.is_(True),
        )
        .options(selectinload(Document.extractions))
    )
    by_file: dict[UUID, list[Document]] = defaultdict(list)
    for document in (await db.execute(stmt)).scalars().all():
        by_file[document.loan_file_id].append(document)
    return dict(by_file)
