"""A processor's verdicts on extracted fields (LP-UI-033).

The reviewer's keyboard loop records a decision per field: accepted, corrected, or
rejected. This is the lifecycle behind it — record, replace, revert — and it is the
DTI/LTV/calculator override lifecycle unchanged (LP-76/77/87): one live row per
subject, soft-delete to revert, the activity log as the immutable trail.

WHAT A VERDICT IS NOT. It is not a change to the extraction. `extracted_data` still
says what the model read, because "what did the model actually say?" is the
question every accuracy investigation starts from. A correction sits beside the
value, and the display resolves the two.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.document import Document
from app.models.extraction import Extraction
from app.models.field_review import FieldReview, FieldVerdict
from app.models.helpers import only_active
from app.services.activity_log import log_activity


class FieldReviewError(Exception):
    """A verdict that cannot be recorded as asked."""


async def list_reviews(db: AsyncSession, *, extraction_id: UUID) -> list[FieldReview]:
    """Every live verdict on one extraction version, oldest first."""
    result = await db.execute(
        only_active(select(FieldReview), FieldReview)
        .where(FieldReview.extraction_id == extraction_id)
        .order_by(FieldReview.created_at)
    )
    return list(result.scalars().all())


async def _live_review(
    db: AsyncSession, *, extraction_id: UUID, field_key: str
) -> FieldReview | None:
    result = await db.execute(
        only_active(select(FieldReview), FieldReview).where(
            FieldReview.extraction_id == extraction_id,
            FieldReview.field_key == field_key,
        )
    )
    return result.scalars().first()


async def record_review(
    db: AsyncSession,
    *,
    document: Document,
    extraction: Extraction,
    field_key: str,
    verdict: FieldVerdict,
    corrected_value: str | None = None,
    note: str | None = None,
    actor_user_id: UUID | None = None,
) -> FieldReview:
    """Record (or replace) the verdict on one field.

    Replacing SOFT-DELETES the previous verdict rather than mutating it. A processor
    who accepts a field and then corrects it has made two decisions, and an audit
    that shows only the second cannot answer what they thought first.

    A REJECTED verdict requires a note. "I could not verify this" with no reason
    tells the next processor nothing, and the next processor is the whole audience
    for a rejection.
    """
    if verdict is FieldVerdict.CORRECTED and not (corrected_value or "").strip():
        raise FieldReviewError("a corrected verdict needs the corrected value")
    if verdict is FieldVerdict.REJECTED and not (note or "").strip():
        raise FieldReviewError("a rejected verdict needs a reason")
    if verdict is not FieldVerdict.CORRECTED and corrected_value is not None:
        # Silently dropping it would leave a value in the row that nothing reads and
        # that a later change might start reading.
        raise FieldReviewError("only a corrected verdict carries a corrected value")

    previous = await _live_review(db, extraction_id=extraction.id, field_key=field_key)
    if previous is not None:
        previous.deleted_at = utcnow()
        # Flush before inserting: the partial unique index covers live rows, and the
        # new row is live the moment it lands.
        await db.flush()

    review = FieldReview(
        extraction_id=extraction.id,
        field_key=field_key,
        verdict=verdict,
        corrected_value=corrected_value if verdict is FieldVerdict.CORRECTED else None,
        note=note,
        reviewed_by_user_id=actor_user_id,
    )
    db.add(review)
    await db.flush()

    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.FIELD_REVIEWED,
        summary=f"{verdict.value.capitalize()} {field_key}",
        actor_user_id=actor_user_id,
        # The corrected VALUE is deliberately not in the detail: an activity log is
        # read widely and a correction can be an identifier. The row holds it.
        detail={
            "document_id": str(document.id),
            "extraction_id": str(extraction.id),
            "field_key": field_key,
            "verdict": verdict.value,
            "replaced_previous": previous is not None,
        },
    )
    return review


async def revert_review(
    db: AsyncSession,
    *,
    document: Document,
    extraction: Extraction,
    field_key: str,
    actor_user_id: UUID | None = None,
) -> bool:
    """Withdraw the verdict on one field. Returns whether there was one to withdraw."""
    review = await _live_review(db, extraction_id=extraction.id, field_key=field_key)
    if review is None:
        return False
    review.deleted_at = utcnow()
    await db.flush()
    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.FIELD_REVIEW_REVERTED,
        summary=f"Withdrew the verdict on {field_key}",
        actor_user_id=actor_user_id,
        detail={
            "document_id": str(document.id),
            "extraction_id": str(extraction.id),
            "field_key": field_key,
        },
    )
    return True
