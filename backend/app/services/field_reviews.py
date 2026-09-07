"""A processor's verdicts on extracted fields (LP-UI-033).

The reviewer's keyboard loop records a decision per field: accepted, corrected, or
rejected. This is the lifecycle behind it — record, replace, revert — and it is the
DTI/LTV/calculator override lifecycle unchanged (LP-76/77/87): one live row per
subject, soft-delete to revert, the activity log as the immutable trail.

WHAT A VERDICT IS NOT. It is not a change to the extraction. `extracted_data` still
says what the model read, because "what did the model actually say?" is the
question every accuracy investigation starts from. A correction sits beside the
value, and the display resolves the two.

WHAT IT NOW ALSO IS (LP-703). Three of the five verdicts change what the RULE
ENGINE reads: `corrected` replaces a value, `removed` takes a field out, `added`
puts one in. Until LP-703 nothing read any of them — a processor could fix a wrong
gross pay and the DTI was still computed from the model's figure, which AMENDMENTS
A28b recorded plainly. The overlay is applied in `build_document_fields`; this
module is where the decision is recorded and validated.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.documents.schema_fields import fields_for
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.document import Document
from app.models.extraction import Extraction
from app.models.field_review import FieldReview, FieldVerdict
from app.models.helpers import only_active
from app.services.activity_log import log_activity
from app.services.verifications import mark_verification_stale
from app.verification.snapshot.persistence import refuses_at_rest


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


#: The verdicts that carry a value the processor supplied.
_VALUE_BEARING = (FieldVerdict.CORRECTED, FieldVerdict.ADDED)


def extracted_value_of(extraction: Extraction, field_key: str) -> str | None:
    """What the model currently says for ``field_key``, as a string, or None.

    Read at the moment a processor overrules it, so ``replaced_value`` records what
    they were actually looking at rather than what the field held whenever someone
    later thought to ask.

    Only the TYPED CORE's ``{value: ...}`` shape is read. A nested list has no single
    value to overrule, and the reviewer does not offer the operation for one (LP-702).
    """
    data = extraction.extracted_data or {}
    entry = data.get(field_key)
    if not isinstance(entry, dict) or "value" not in entry:
        return None
    value = entry.get("value")
    if value is None or isinstance(value, (list, dict)):
        return None
    return str(value)


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

    A REMOVED verdict requires one too, for the same reason and a sharper one: it
    takes a field out of the snapshot, so the next person sees an absence with no
    account of who created it.

    An ADDED verdict must name a field the document type DECLARES. A key outside the
    schema specs is data no rule can ever read, so accepting free text would let a
    processor type a value into a field that reaches nobody — busy work that looks
    like progress.
    """
    if verdict is FieldVerdict.CORRECTED and not (corrected_value or "").strip():
        raise FieldReviewError("a corrected verdict needs the corrected value")
    if verdict is FieldVerdict.ADDED and not (corrected_value or "").strip():
        raise FieldReviewError("an added verdict needs the value being added")
    if verdict is FieldVerdict.REJECTED and not (note or "").strip():
        raise FieldReviewError("a rejected verdict needs a reason")
    if verdict is FieldVerdict.REMOVED and not (note or "").strip():
        raise FieldReviewError("a removed verdict needs a reason")
    # REFUSED AT THE DOOR, not at the end of the next run. A hand-typed value lands
    # in `Field.value` with no extractor between it and the snapshot, and the
    # persist guard aborts the WHOLE loan file's snapshot for a 9+ digit run — so a
    # processor typing the parcel number off a title commitment (ten digits, on a
    # field `_PII_FIELDS` does not route; nineteen offerable fields share that
    # shape) would silently stop every subsequent verification run from persisting
    # anything, with nothing on screen connecting the two.
    #
    # The rule comes FROM the persist guard rather than being restated here, so a
    # value cannot be accepted at the door and refused at the end.
    if corrected_value is not None and (reason := refuses_at_rest(corrected_value)) is not None:
        raise FieldReviewError(
            f"that value contains {reason}, which cannot be stored in a verification "
            "snapshot. If the field genuinely holds an identifier, it needs routing "
            "through the documents section's PII map before it can be supplied here."
        )
    if verdict not in _VALUE_BEARING and corrected_value is not None:
        # Silently dropping it would leave a value in the row that nothing reads and
        # that a later change might start reading.
        raise FieldReviewError("only a corrected or added verdict carries a value")

    existing = extracted_value_of(extraction, field_key)
    if verdict is FieldVerdict.ADDED:
        declared = fields_for(document.document_type)
        if field_key not in declared:
            raise FieldReviewError(
                f"{field_key!r} is not a field {document.document_type or 'this document type'} "
                "declares, so no rule could read it"
            )
        if existing is not None:
            # Correcting it is the operation that exists for this. Allowing `added`
            # over a value the model produced would make `replaced_value` a lie and
            # lose the model's reading from the audit.
            raise FieldReviewError(f"{field_key!r} was extracted — correct it rather than add it")
    if verdict is FieldVerdict.REMOVED and existing is None:
        raise FieldReviewError(f"{field_key!r} has no extracted value to remove")
    # THE THIRD SIDE OF THE SAME GUARD. REMOVED requires an extracted value and
    # ADDED requires none; CORRECTED required neither, so any key in
    # `extracted_data` could be corrected regardless of its SHAPE. Correcting a
    # nested list — `earnings_lines` — was accepted, and the snapshot then emitted
    # a scalar `Field` for that key while `_list_row_fields` still built the nested
    # list from the extraction: the flat and nested views of one key disagreeing.
    # The reviewer gates its editor on `kind === "scalar"`, so this is reachable
    # only through the API, which is exactly the door a guard is for.
    if verdict is FieldVerdict.CORRECTED and existing is None:
        raise FieldReviewError(
            f"{field_key!r} has no single extracted value to correct — a list or a "
            "nested block is corrected by fixing the document and re-reading it"
        )

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
        corrected_value=corrected_value if verdict in _VALUE_BEARING else None,
        # ONLY WHERE SOMETHING WAS ACTUALLY OVERRULED — a correction or a removal.
        #
        # `None if verdict is ADDED else existing` also wrote it for ACCEPTED and
        # REJECTED, which overrule nothing. Pressing Enter to accept `employee_ssn`
        # on a W-2 therefore copied the raw SSN out of `extracted_data` into this
        # column: the commonest keystroke in the reviewer, creating a second at-rest
        # copy of a raw identifier in a table that otherwise holds one only when a
        # person typed it. The docstring on the column said "(CORRECTED and
        # REMOVED)" all along; the code did not.
        #
        # Derived from `changes_the_snapshot` rather than restated, so a fourth
        # verdict cannot join one list and not the other.
        replaced_value=(
            existing if verdict.changes_the_snapshot and verdict is not FieldVerdict.ADDED else None
        ),
        note=note,
        reviewed_by_user_id=actor_user_id,
    )
    db.add(review)
    await db.flush()

    if verdict.changes_the_snapshot or (
        previous is not None and previous.verdict.changes_the_snapshot
    ):
        # THE FINDINGS ON SCREEN NOW CITE A VALUE THAT IS NO LONGER WHAT THE FILE
        # SAYS. Marking stale is how the file admits that rather than presenting a
        # DTI computed from a figure the processor has just overruled. The second
        # half of the condition matters as much as the first: withdrawing a
        # correction changes the facts back, and a run that ignored it would leave
        # the findings describing a value nobody stands behind any more.
        await mark_verification_stale(db, loan_file_id=document.loan_file_id)

    await log_activity(
        db,
        loan_file_id=document.loan_file_id,
        activity_type=ActivityType.FIELD_REVIEWED,
        summary=f"{verdict.value.capitalize()} {field_key}",
        actor_user_id=actor_user_id,
        # Neither VALUE is in the detail: an activity log is read widely, and both the
        # correction and the value it replaced can be identifiers. The row holds them.
        detail={
            "document_id": str(document.id),
            "extraction_id": str(extraction.id),
            "field_key": field_key,
            "verdict": verdict.value,
            "replaced_previous": previous is not None,
            "changed_the_snapshot": verdict.changes_the_snapshot,
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
    changed_the_snapshot = review.verdict.changes_the_snapshot
    review.deleted_at = utcnow()
    await db.flush()
    if changed_the_snapshot:
        # Undo is a change too. The findings were computed WITH the correction, and
        # withdrawing it puts the model's value back — so the run on screen describes
        # a file that no longer exists, exactly as it would after making one.
        await mark_verification_stale(db, loan_file_id=document.loan_file_id)
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
