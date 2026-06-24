"""Document versioning service (Model C, LP-71) — explicit replace.

Model C: new uploads are NORMAL — current + standalone, with NO replacement
assumption (multiples are normal — a set of pay stubs / months of statements are not
replacements). Replacement is **explicit**: the processor deliberately supersedes a
specific document with a new upload. The old becomes HISTORICAL (``is_current`` False),
the new becomes CURRENT, BOTH are kept for audit (sharing a ``version_group``), and the
need the old satisfied re-evaluates against the new current version (LP-68).
"""

from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.helpers import only_active
from app.services.needs_engine import reopen_needs_satisfied_by

logger = structlog.get_logger(__name__)


async def supersede_document(
    db: AsyncSession, *, old_document: Document, new_document: Document
) -> None:
    """Make ``new_document`` the current version that supersedes ``old_document``.

    ``old_document`` must be the current version (you replace what's current). The old
    goes historical; the new joins the old's version group (originating at the first
    document), takes the next version ordinal, and links back via
    ``supersedes_document_id``. The need the old satisfied is re-opened so the new
    document re-satisfies it on processing. Both rows are retained (audit). Uses
    ``flush``; the caller commits + enqueues the new document's processing.
    """
    # The group originates at the first document of the chain.
    group_id = old_document.version_group_id or old_document.id

    old_document.is_current = False
    old_document.version_group_id = group_id

    new_document.is_current = True
    new_document.version_group_id = group_id
    new_document.version = old_document.version + 1
    new_document.supersedes_document_id = old_document.id

    # The need the old document satisfied must re-evaluate against the current version.
    await reopen_needs_satisfied_by(db, document_id=old_document.id)

    await db.flush()
    logger.info(
        "document_superseded",
        old_document_id=str(old_document.id),
        new_document_id=str(new_document.id),
        version=new_document.version,
    )


async def version_count(db: AsyncSession, *, document: Document) -> int:
    """How many active documents are in this document's version group (1 if standalone)."""
    if document.version_group_id is None:
        return 1
    stmt = select(func.count(Document.id)).where(
        Document.version_group_id == document.version_group_id
    )
    count = await db.scalar(only_active(stmt, Document))
    return int(count or 1)


async def version_counts_for_group_ids(
    db: AsyncSession, *, group_ids: set[UUID]
) -> dict[UUID, int]:
    """Active document counts per version group (one query) — for the list response."""
    if not group_ids:
        return {}
    stmt = (
        select(Document.version_group_id, func.count(Document.id))
        .where(Document.version_group_id.in_(group_ids))
        .group_by(Document.version_group_id)
    )
    rows = (await db.execute(only_active(stmt, Document))).all()
    return {gid: int(n) for gid, n in rows if gid is not None}
