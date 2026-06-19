"""Needs-update task (LP-68) — the PER-FILE-SERIALIZED needs update.

When a document is processed, its needs update runs here — a Celery task that
acquires a **per-loan-file Redis lock** before applying the satisfaction-matching.
This is the race fix: real processing dumps batches of documents for a file, and a
naive "doc arrives → update needs" without serialization would race on the file's
shared needs state (lost updates, double-satisfaction). With the lock, concurrent
arrivals for the SAME file apply ONE AT A TIME; DIFFERENT files (different lock
keys) update in PARALLEL.

The pipeline (:mod:`app.tasks.document_processing`) enqueues this after a document
reaches a terminal status; the actual matching is
:func:`app.services.needs_engine.apply_document_to_needs`. Retry-safe: the matching
only advances an OPEN need, so a re-run never double-advances.
"""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.helpers import only_active
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
    """Apply a processed document to its file's needs, serialized per loan file."""
    # The lock (same file serial, different files parallel) wraps the session.
    async with loan_file_needs_lock(loan_file_id), task_session() as db:
        document = await _load_document(db, document_id)
        if document is None:
            logger.info("needs_update_document_missing", document_id=document_id)
            return
        await apply_document_to_needs(db, document)
        await db.commit()


@celery_app.task(name="needs.update_for_document")  # type: ignore[untyped-decorator]
def update_needs_for_document(loan_file_id: str, document_id: str) -> None:
    """Celery task: advance the file's matching need for a processed document (LP-68)."""
    run_async(_run_needs_update(loan_file_id, document_id))
