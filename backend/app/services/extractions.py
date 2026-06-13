"""Extraction service — versioned creation of extraction records (LP-16).

The one tricky bit of extraction versioning is the partial unique index
``UNIQUE (document_id) WHERE is_current`` (ADR-058): at most one row per document
may have ``is_current = true``. So creating a new version must **demote the old
current before inserting the new one**, with a flush in between, or the insert
trips the index. :func:`create_extraction_version` encapsulates that ordering so
callers (the extraction task in LP-39) never have to think about it.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction import Extraction, ExtractionStatus


async def create_extraction_version(
    db: AsyncSession,
    *,
    document_id: UUID,
    extracted_data: dict[str, Any],
    extraction_status: ExtractionStatus,
    model_used: str | None = None,
    tokens_used: int | None = None,
    cost_estimate: float | None = None,
    error_detail: str | None = None,
) -> Extraction:
    """Create the next extraction version for a document, made current.

    Demotes the document's existing current extraction (``is_current = False``),
    computes the next ``version`` (max existing + 1, or 1 for the first), and
    inserts the new row as current.

    Ordering (ADR-058): the old current is demoted **and flushed first**, so the
    partial unique index ``UNIQUE (document_id) WHERE is_current`` is free before
    the new current row is inserted — otherwise the insert would collide with the
    still-current old row. Version numbers are never reused (the max is taken over
    all rows, including soft-deleted ones), so history stays monotonic.

    Uses ``flush`` rather than ``commit`` so the caller controls the transaction.
    """
    # Demote the existing current extraction, if any. Loading the ORM object
    # (rather than a bulk UPDATE) keeps the session's identity map consistent for
    # a caller that still holds a reference to it.
    current = await db.scalar(
        select(Extraction).where(
            Extraction.document_id == document_id,
            Extraction.is_current.is_(True),
        )
    )
    if current is not None:
        current.is_current = False
        # Flush the demotion before inserting the new current row, so the
        # partial unique index is not momentarily violated by two current rows.
        await db.flush()

    # Next version = highest existing version + 1 (over all rows, so numbers are
    # never reused), or 1 if this is the document's first extraction.
    max_version = await db.scalar(
        select(func.max(Extraction.version)).where(Extraction.document_id == document_id)
    )
    next_version = (max_version or 0) + 1

    new_extraction = Extraction(
        document_id=document_id,
        version=next_version,
        is_current=True,
        extracted_data=extracted_data,
        extraction_status=extraction_status,
        model_used=model_used,
        tokens_used=tokens_used,
        cost_estimate=cost_estimate,
        error_detail=error_detail,
    )
    db.add(new_extraction)
    await db.flush()
    return new_extraction
