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
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.documents.staleness import evaluate_staleness
from app.models.document import Document, DocumentStatus
from app.models.extraction import Extraction
from app.models.finding import Finding, FindingResolutionStatus, FindingStatus
from app.models.helpers import only_active
from app.models.loan_file import LoanFile, LoanFileStatus
from app.models.needs_item import NeedsItem, NeedsItemStatus
from app.models.user import User
from app.services.aggression import active_cutoff


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


# Only actionable findings block; green is a passed check. Mirrors
# `finding_blocking._BLOCKING_SEVERITIES`.
_BLOCKING_SEVERITIES = (FindingStatus.RED, FindingStatus.YELLOW)

# Terminal statuses have nothing to be done about them; saying so calmly is the
# honest answer, not "Clear".
_TERMINAL = {LoanFileStatus.CLOSED, LoanFileStatus.WITHDRAWN}

# A need is satisfied when nobody has to collect anything more for it.
_SATISFIED_NEEDS = {NeedsItemStatus.VERIFIED, NeedsItemStatus.WAIVED}

# Still waiting on a DOCUMENT. Mirrors `NEEDS_GROUP`'s `needs_action` bucket in
# `frontend/lib/loan-files/needs.ts`, which is what the file's own needs screen
# counts — `received` belongs to `in_review`, because the document arrived and
# what is outstanding is the reading of it, not the collecting. Counting
# `total - satisfied` instead put `received` in the waiting set, so the dashboard
# and the file screen reported different numbers for the same idea.
_AWAITING_NEEDS = {
    NeedsItemStatus.PENDING,
    NeedsItemStatus.REQUESTED,
    NeedsItemStatus.REJECTED,
}

# Arrived, not yet verified. Outstanding work, but not outstanding COLLECTION.
_IN_REVIEW_NEEDS = {NeedsItemStatus.RECEIVED}


async def attention_for_files(
    db: AsyncSession,
    loan_files: Sequence[LoanFile],
    *,
    user: User,
    today: date | None = None,
) -> dict[UUID, FileAttention]:
    """Derive one `FileAttention` per file, in three queries total.

    `user` is required rather than optional: whether a finding blocks depends on
    the confidence cutoff in force, and that is the file's override or this
    user's default (LP-79). A page-wide count that ignored it would disagree with
    every file screen it links to.
    """
    ids = [file.id for file in loan_files]
    if not ids:
        return {}

    blocking = await _blocking_finding_counts(db, loan_files, user=user)
    counts = await _needs_counts(db, ids)
    documents = await _current_documents(db, ids)

    return {
        file.id: _decide(
            file,
            blocking=blocking.get(file.id, 0),
            documents=documents.get(file.id, []),
            needs=counts.get(file.id, _NeedsCounts()),
            today=today,
        )
        for file in loan_files
    }


def _decide(
    file: LoanFile,
    *,
    blocking: int,
    documents: list[Document],
    needs: "_NeedsCounts",
    today: date | None,
) -> FileAttention:
    """Pick the single most important thing wrong with one file.

    Ordered by what stops the file moving, not by severity in the abstract: a
    rule that blocks submission outranks a document that failed to read, which
    outranks one that is merely old.
    """
    progress = {"needs_total": needs.total, "needs_satisfied": needs.satisfied}

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

    # BEFORE the empty-documents line, deliberately. A file opened this morning
    # has no documents and eight needs, and "No documents yet" is both the less
    # useful sentence and a NEUTRAL tone on the most actionable row on the page.
    # "No documents yet" is the honest answer only when nothing is being waited on.
    if needs.awaiting:
        noun = "document" if needs.awaiting == 1 else "documents"
        return FileAttention(
            tone=AttentionTone.ATTENTION,
            label=f"Waiting on {needs.awaiting} {noun}",
            **progress,
        )

    if needs.in_review:
        # Arrived and unread. Not "Nothing outstanding" — the reading is the work.
        noun = "document" if needs.in_review == 1 else "documents"
        return FileAttention(
            tone=AttentionTone.ATTENTION,
            label=f"{needs.in_review} {noun} to review",
            **progress,
        )

    if not documents:
        return FileAttention(tone=AttentionTone.NEUTRAL, label="No documents yet", **progress)

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


async def _blocking_finding_counts(
    db: AsyncSession, loan_files: Sequence[LoanFile], *, user: User
) -> dict[UUID, int]:
    """Open in-scope findings per file — the SAME definition the file screen uses.

    `app/services/finding_blocking.py` owns what "blocks submission" means:
    resolution OPEN, severity red or yellow, and confidence at or above the
    cutoff in force. This mirrors that predicate rather than restating it, because
    a dashboard that counts blocking findings differently from the screen it links
    to is worse than either count being wrong on its own — the processor cannot
    tell which one to believe.

    The first version filtered `evaluation_outcome == OPEN` and ignored confidence,
    which was wrong in BOTH directions: it counted low-confidence hunches the dial
    deliberately excludes, and it missed AI cross-source findings, which carry a
    severity but no rule-engine outcome.

    Still one query. The cutoff is per FILE (its override, else the user default),
    so the comparison happens here rather than in SQL — over the page's candidate
    findings, not per row.
    """
    ids = [file.id for file in loan_files]
    stmt = only_active(
        select(Finding.loan_file_id, Finding.confidence).where(
            Finding.loan_file_id.in_(ids),
            Finding.resolution_status == FindingResolutionStatus.OPEN,
            Finding.status.in_(_BLOCKING_SEVERITIES),
        ),
        Finding,
    )
    cutoffs = {file.id: active_cutoff(file, user) for file in loan_files}
    counts: dict[UUID, int] = defaultdict(int)
    for loan_file_id, confidence in (await db.execute(stmt)).all():
        if confidence is not None and confidence >= cutoffs[loan_file_id]:
            counts[loan_file_id] += 1
    return dict(counts)


@dataclass(frozen=True)
class _NeedsCounts:
    """One file's needs, split the way the needs screen splits them."""

    total: int = 0
    satisfied: int = 0
    awaiting: int = 0
    in_review: int = 0


async def _needs_counts(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, _NeedsCounts]:
    """Needs per file, from one grouped count."""
    stmt = (
        select(NeedsItem.loan_file_id, NeedsItem.status, func.count())
        .where(NeedsItem.loan_file_id.in_(ids), NeedsItem.deleted_at.is_(None))
        .group_by(NeedsItem.loan_file_id, NeedsItem.status)
    )
    totals: dict[UUID, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for loan_file_id, status, count in (await db.execute(stmt)).all():
        bucket = totals[loan_file_id]
        bucket[0] += count
        if status in _SATISFIED_NEEDS:
            bucket[1] += count
        if status in _AWAITING_NEEDS:
            bucket[2] += count
        if status in _IN_REVIEW_NEEDS:
            bucket[3] += count
    return {
        loan_file_id: _NeedsCounts(total=b[0], satisfied=b[1], awaiting=b[2], in_review=b[3])
        for loan_file_id, b in totals.items()
    }


async def _current_documents(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, list[Document]]:
    """Current documents for the page, with the extraction staleness needs."""
    stmt = (
        select(Document)
        .where(
            Document.loan_file_id.in_(ids),
            Document.deleted_at.is_(None),
            Document.is_current.is_(True),
        )
        # ONLY the current extraction. `selectinload(Document.extractions)` loads
        # every version ever made, for every document, for every file on the page
        # — and `_oldest_stale` then discards all but the current one. Prior
        # versions are kept for audit and are unbounded in principle, so this was
        # a page-size-times-version-count load to answer a question about one row.
        .options(selectinload(Document.extractions.and_(Extraction.is_current)))
    )
    by_file: dict[UUID, list[Document]] = defaultdict(list)
    for document in (await db.execute(stmt)).scalars().all():
        by_file[document.loan_file_id].append(document)
    return dict(by_file)
