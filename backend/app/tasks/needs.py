"""Needs-update tasks (LP-68/69) — PER-FILE-SERIALIZED needs updates.

Needs updates for a file run under a **per-loan-file Redis lock** so concurrent
arrivals for the SAME file apply ONE AT A TIME (no race on the shared needs state);
DIFFERENT files (different lock keys) update in PARALLEL. Two tasks:

  * ``needs.update_for_document`` (LP-68) — enqueued by the pipeline when a document
    is terminal: the deterministic satisfaction-matching, then (LP-69) re-run the AI
    reasoning (the picture changed).
  * ``needs.propose_ai_needs`` (LP-69) — enqueued at MISMO file creation: the initial
    AI-reasoned proposed needs over the stated data.

Retry-safe: the matching only advances an OPEN need, and the AI ingestion skips
already-present needs, so a re-run never piles up duplicates.
"""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.helpers import only_active
from app.services.needs_ai import apply_ai_needs_for_file_id
from app.services.needs_engine import apply_document_to_needs, loan_file_needs_lock
from app.tasks.base import run_async, task_session
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


async def _load_document(db: AsyncSession, document_id: str) -> Document | None:
    try:
        pk = UUID(document_id)
    except ValueError:
        return None
    document: Document | None = await db.scalar(
        only_active(select(Document).where(Document.id == pk), Document)
    )
    return document


async def _run_needs_update(loan_file_id: str, document_id: str) -> None:
    """Apply a processed document to its file's needs, serialized per loan file.

    Under the per-file lock: (1) the deterministic match (LP-68), then (2) re-run the
    AI reasoning (LP-69) — the picture changed, so propose any newly-implied needs.
    """
    async with loan_file_needs_lock(loan_file_id), task_session() as db:
        document = await _load_document(db, document_id)
        if document is None:
            logger.info("needs_update_document_missing", document_id=document_id)
            return
        await apply_document_to_needs(db, document)  # LP-68 deterministic match
        await apply_ai_needs_for_file_id(db, UUID(loan_file_id))  # LP-69 re-reason
        await db.commit()


async def _run_propose_ai_needs(loan_file_id: str) -> None:
    """Reason over the file and ingest AI-proposed needs, serialized per loan file."""
    async with loan_file_needs_lock(loan_file_id), task_session() as db:
        await apply_ai_needs_for_file_id(db, UUID(loan_file_id))
        await db.commit()


@celery_app.task(name="needs.update_for_document")  # type: ignore[untyped-decorator]
def update_needs_for_document(loan_file_id: str, document_id: str) -> None:
    """Celery task: advance the file's needs for a processed document (LP-68 + LP-69)."""
    run_async(_run_needs_update(loan_file_id, document_id))


@celery_app.task(name="needs.propose_ai_needs")  # type: ignore[untyped-decorator]
def propose_ai_needs(loan_file_id: str) -> None:
    """Celery task: the initial AI-reasoned proposed needs (enqueued at MISMO creation)."""
    run_async(_run_propose_ai_needs(loan_file_id))
