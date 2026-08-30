"""A processor's verdict on one extracted field (LP-UI-033).

The lifecycle — record, replace, revert — and the two rules that make a verdict
worth having: a rejection carries a reason, and a correction never touches the
extraction.
"""

from __future__ import annotations

import pytest
from app.models.activity_log import ActivityLog, ActivityType
from app.models.document import Document
from app.models.extraction import Extraction
from app.models.field_review import FieldVerdict
from app.services.field_reviews import (
    FieldReviewError,
    list_reviews,
    record_review,
    revert_review,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

DATA = {
    "gross_pay": {"value": "4200.00", "source": {"page": 1, "snippet": "Gross Pay 4,200.00"}},
    "net_pay": {"value": "3100.00"},
}


async def _subject(db: AsyncSession) -> tuple[Document, Extraction]:
    company = await factories.make_company(db)
    loan_file = await factories.make_loan_file(db, company=company)
    document = await factories.make_document(db, loan_file=loan_file, company=company)
    extraction = await factories.make_extraction(db, document=document, data=DATA)
    await db.flush()
    return document, extraction


class TestRecording:
    async def test_an_accepted_field_is_recorded(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        review = await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        assert review.verdict is FieldVerdict.ACCEPTED
        assert review.corrected_value is None
        assert [r.field_key for r in await list_reviews(db, extraction_id=extraction.id)] == [
            "gross_pay"
        ]

    async def test_a_correction_does_not_touch_the_extraction(self, db: AsyncSession) -> None:
        # THE POINT OF THE WHOLE DESIGN. "What did the model actually say?" is the
        # question every accuracy investigation starts from; overwriting the value
        # to record the correction destroys the evidence to store the verdict.
        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4250.00",
        )
        await db.refresh(extraction)
        assert extraction.extracted_data["gross_pay"]["value"] == "4200.00"

    async def test_re_deciding_replaces_rather_than_adds(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        for verdict in (FieldVerdict.ACCEPTED, FieldVerdict.REJECTED):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=verdict,
                note="illegible" if verdict is FieldVerdict.REJECTED else None,
            )
        live = await list_reviews(db, extraction_id=extraction.id)
        assert len(live) == 1
        assert live[0].verdict is FieldVerdict.REJECTED

    async def test_the_replaced_verdict_is_kept_not_mutated(self, db: AsyncSession) -> None:
        # A processor who accepts and then rejects has made two decisions, and an
        # audit showing only the second cannot say what they thought first.
        document, extraction = await _subject(db)
        first = await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.REJECTED,
            note="the page is a scan",
        )
        await db.refresh(first)
        assert first.verdict is FieldVerdict.ACCEPTED  # unchanged
        assert first.deleted_at is not None  # withdrawn, not rewritten

    async def test_two_fields_are_independent(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        for field in ("gross_pay", "net_pay"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key=field,
                verdict=FieldVerdict.ACCEPTED,
            )
        assert len(await list_reviews(db, extraction_id=extraction.id)) == 2


class TestTheRulesThatMakeItWorthHaving:
    async def test_a_rejection_needs_a_reason(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        with pytest.raises(FieldReviewError, match="reason"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=FieldVerdict.REJECTED,
            )

    @pytest.mark.parametrize("value", [None, "", "   "])
    async def test_a_correction_needs_the_corrected_value(
        self, db: AsyncSession, value: str | None
    ) -> None:
        document, extraction = await _subject(db)
        with pytest.raises(FieldReviewError, match="corrected value"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=FieldVerdict.CORRECTED,
                corrected_value=value,
            )

    async def test_an_acceptance_cannot_smuggle_a_corrected_value(self, db: AsyncSession) -> None:
        # Dropping it silently would leave a value in the row that nothing reads
        # and that a later change might start reading.
        document, extraction = await _subject(db)
        with pytest.raises(FieldReviewError, match="only a corrected"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=FieldVerdict.ACCEPTED,
                corrected_value="4250.00",
            )


class TestReverting:
    async def test_a_verdict_can_be_withdrawn(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        assert await revert_review(
            db, document=document, extraction=extraction, field_key="gross_pay"
        )
        assert await list_reviews(db, extraction_id=extraction.id) == []

    async def test_reverting_nothing_says_so_rather_than_failing(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        assert not await revert_review(
            db, document=document, extraction=extraction, field_key="gross_pay"
        )

    async def test_a_field_can_be_reviewed_again_after_a_revert(self, db: AsyncSession) -> None:
        # The partial unique index covers LIVE rows only; a revert must not lock the
        # field out for the rest of the extraction's life.
        document, extraction = await _subject(db)
        for _ in range(3):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=FieldVerdict.ACCEPTED,
            )
            await revert_review(db, document=document, extraction=extraction, field_key="gross_pay")
        assert await list_reviews(db, extraction_id=extraction.id) == []


class TestTheAuditTrail:
    async def test_every_verdict_is_logged_without_the_corrected_value(
        self, db: AsyncSession
    ) -> None:
        # An activity log is read widely, and a correction can be an identifier —
        # correct an SSN field and the correction IS an SSN. The row holds it.
        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4250.00",
        )
        entries = (
            (
                await db.execute(
                    select(ActivityLog).where(ActivityLog.loan_file_id == document.loan_file_id)
                )
            )
            .scalars()
            .all()
        )
        logged = [e for e in entries if e.activity_type is ActivityType.FIELD_REVIEWED]
        assert len(logged) == 1
        assert logged[0].detail["field_key"] == "gross_pay"
        assert logged[0].detail["verdict"] == "corrected"
        assert "4250.00" not in str(logged[0].detail)
        assert "4250.00" not in logged[0].summary

    async def test_a_revert_is_logged_too(self, db: AsyncSession) -> None:
        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        await revert_review(db, document=document, extraction=extraction, field_key="gross_pay")
        entries = (
            (
                await db.execute(
                    select(ActivityLog).where(ActivityLog.loan_file_id == document.loan_file_id)
                )
            )
            .scalars()
            .all()
        )
        assert any(e.activity_type is ActivityType.FIELD_REVIEW_REVERTED for e in entries)


class TestReExtraction:
    """What a re-extraction does to a verdict (LP-UI-033 review).

    ADR-393 says a superseded version's reviews "go with it" via the ON DELETE
    CASCADE on `extractions`. THE CASCADE NEVER FIRES. Re-extraction does not
    delete anything: `create_extraction_version` demotes the current row
    (`is_current = False`) and inserts a new one, because prior versions are kept
    for audit (`app/models/extraction.py`). No code path deletes an Extraction.

    The BEHAVIOUR the ADR wants is still correct, and these tests pin it: a verdict
    is keyed on `extraction_id`, so a new version simply has none of its own. That
    is a different mechanism with a different failure mode, and the difference
    matters — anyone who changed re-extraction to update a row IN PLACE would keep
    the verdicts, and the cascade the ADR points at would not save them.
    """

    async def test_a_re_extraction_leaves_every_field_unreviewed(self, db: AsyncSession) -> None:
        from app.models.extraction import ExtractionStatus
        from app.services.extractions import create_extraction_version

        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        assert len(await list_reviews(db, extraction_id=extraction.id)) == 1

        fresh = await create_extraction_version(
            db,
            document_id=document.id,
            extracted_data={"gross_pay": {"value": "9999.00"}},
            extraction_status=ExtractionStatus.SUCCEEDED,
        )
        await db.flush()

        # THE ASSERTION THAT MATTERS: the new figure carries nobody's name.
        assert await list_reviews(db, extraction_id=fresh.id) == []

    async def test_the_superseded_versions_verdict_survives_as_history(
        self, db: AsyncSession
    ) -> None:
        """The other half, and the one that shows the cascade is not what runs.

        If reviews were really deleted with their extraction, this would be empty.
        It is not: the row stays attached to the version it was recorded against,
        which is what an accuracy investigation needs — "someone accepted THIS
        value" is only answerable while both the value and the verdict exist.
        """
        from app.models.extraction import ExtractionStatus
        from app.services.extractions import create_extraction_version

        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        await create_extraction_version(
            db,
            document_id=document.id,
            extracted_data={"gross_pay": {"value": "9999.00"}},
            extraction_status=ExtractionStatus.SUCCEEDED,
        )
        await db.flush()
        await db.refresh(extraction)

        assert extraction.is_current is False
        assert [r.field_key for r in await list_reviews(db, extraction_id=extraction.id)] == [
            "gross_pay"
        ]

    async def test_deleting_the_extraction_does_cascade(self, db: AsyncSession) -> None:
        """The cascade is real — it just is not on the re-extraction path.

        Worth pinning so the FK is not removed as dead weight: a document delete
        cascades to its extractions, and their reviews have to go too.
        """
        from app.models.field_review import FieldReview

        document, extraction = await _subject(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.ACCEPTED,
        )
        await db.flush()
        await db.delete(extraction)
        await db.flush()

        remaining = (
            await db.scalars(select(FieldReview).where(FieldReview.extraction_id == extraction.id))
        ).all()
        assert list(remaining) == []
