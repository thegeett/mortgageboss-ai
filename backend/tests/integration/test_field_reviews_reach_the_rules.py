"""A correction a processor makes reaches the rule engine (LP-703).

THE HALF THAT WAS MISSING. LP-UI-033 stored corrections and nothing read them —
AMENDMENTS A28b recorded it plainly: a processor could fix a wrong gross pay and
the DTI was still computed from the model's figure. The screen showed the
correction; the verification did not.

TESTED THROUGH ``build_snapshot``, NOT ``build_document_fields``. The pure overlay
function has its own unit tests, and they would all have passed while the snapshot
builder never passed an override in — which is precisely the shape of the original
bug, one layer up. What the rule engine reads is the snapshot, so the snapshot,
built from the database the way a real run builds it, is where the claim has to be
checked.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models.field_review import FieldVerdict
from app.services.field_reviews import FieldReviewError, record_review, revert_review
from app.verification.snapshot.builder import build_snapshot
from app.verification.snapshot.fields import FieldSource
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration import factories

#: A pay stub the model read wrongly: it took the YTD column for the period's gross.
PAY_STUB = {
    "gross_pay": {
        "value": "54600.00",
        "source": {"page": 1, "snippet": "YTD Gross 54,600.00"},
        "confidence": 0.91,
    },
    "net_pay": {"value": "3100.00"},
    "employer_name": {"value": "Enterprise Technology Solutions Inc."},
}


async def _seed(db: AsyncSession, data: dict[str, object] | None = None):
    company = await factories.make_company(db)
    loan_file = await factories.make_loan_file(db, company=company)
    document = await factories.make_document(
        db, loan_file=loan_file, company=company, document_type="pay_stub"
    )
    extraction = await factories.make_extraction(db, document=document, data=dict(data or PAY_STUB))
    await db.flush()
    return loan_file, document, extraction


async def _pay_stub_fields(db: AsyncSession, loan_file) -> dict:
    """The document fields a verification run would read, built the way a run builds them."""
    snapshot = await build_snapshot(
        db, loan_file_id=loan_file.id, run_id=uuid4(), company_id=loan_file.company_id
    )
    assert not snapshot.documents.absent, snapshot.documents.reason
    entries = snapshot.documents.entries
    assert len(entries) == 1, "the fixture seeds exactly one document"
    return entries[0].fields


class TestACorrectionReachesTheSnapshot:
    async def test_without_a_correction_the_snapshot_carries_the_models_value(
        self, db: AsyncSession
    ) -> None:
        # THE POSITIVE CONTROL. Without it, a test asserting the corrected value
        # would pass just as well against a builder that always used the correction
        # — or against a fixture whose model value happened to match.
        loan_file, _document, _extraction = await _seed(db)
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["gross_pay"].value == "54600.00"
        assert fields["gross_pay"].source is FieldSource.EXTRACTED

    async def test_the_corrected_value_is_what_the_rules_read(self, db: AsyncSession) -> None:
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["gross_pay"].value == "4200.00"

    async def test_a_corrected_field_says_a_person_supplied_it(self, db: AsyncSession) -> None:
        # Stated versus verified, tracked separately. A finding citing this figure
        # has to be able to say a human put it there, not the model.
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["gross_pay"].source is FieldSource.CORRECTED

    async def test_a_corrected_field_carries_no_confidence(self, db: AsyncSession) -> None:
        # The model rated its own reading at 0.91. That number describes a value the
        # processor has just overruled, and carrying it forward would report the
        # model as fairly sure about a figure it never saw.
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["gross_pay"].confidence is None

    async def test_the_extraction_still_says_what_the_model_said(self, db: AsyncSession) -> None:
        # The overlay is applied as the snapshot is built. `extracted_data` is
        # untouched, because "what did the model actually say?" is the question
        # every accuracy investigation starts from.
        _loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        await db.refresh(extraction)
        assert extraction.extracted_data["gross_pay"]["value"] == "54600.00"

    async def test_other_fields_are_untouched(self, db: AsyncSession) -> None:
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["net_pay"].value == "3100.00"
        assert fields["net_pay"].source is FieldSource.EXTRACTED

    async def test_undo_puts_the_models_value_back(self, db: AsyncSession) -> None:
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        assert (await _pay_stub_fields(db, loan_file))["gross_pay"].value == "4200.00"
        await revert_review(db, document=document, extraction=extraction, field_key="gross_pay")
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["gross_pay"].value == "54600.00"
        assert fields["gross_pay"].source is FieldSource.EXTRACTED


class TestAcceptingAndRejectingChangeNothing:
    """The three original verdicts record an opinion; they are not facts.

    Worth its own class because collapsing the two kinds is the tempting mistake:
    `rejected` reads like "this value is bad", and making it remove the field would
    mean an illegible page silently deletes data.
    """

    @pytest.mark.parametrize(
        ("verdict", "note"),
        [(FieldVerdict.ACCEPTED, None), (FieldVerdict.REJECTED, "the page is illegible")],
    )
    async def test_the_models_value_survives(
        self, db: AsyncSession, verdict: FieldVerdict, note: str | None
    ) -> None:
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=verdict,
            note=note,
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["gross_pay"].value == "54600.00"
        assert fields["gross_pay"].source is FieldSource.EXTRACTED


class TestRemovingAField:
    async def test_a_removed_field_is_ABSENT_not_null(self, db: AsyncSession) -> None:
        # The distinction the whole operation exists for. A rule that needs this
        # field now degrades to `couldnt_check` — "we do not know" — rather than
        # evaluating against a null and reporting "we checked, and it was empty".
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.REMOVED,
            note="this figure is not on the document",
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert "gross_pay" not in fields

    async def test_undo_brings_it_back(self, db: AsyncSession) -> None:
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.REMOVED,
            note="not on the document",
        )
        assert "gross_pay" not in await _pay_stub_fields(db, loan_file)
        await revert_review(db, document=document, extraction=extraction, field_key="gross_pay")
        assert (await _pay_stub_fields(db, loan_file))["gross_pay"].value == "54600.00"

    async def test_a_removal_needs_a_reason(self, db: AsyncSession) -> None:
        _loan_file, document, extraction = await _seed(db)
        with pytest.raises(FieldReviewError, match="reason"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=FieldVerdict.REMOVED,
            )

    async def test_there_has_to_be_something_to_remove(self, db: AsyncSession) -> None:
        _loan_file, document, extraction = await _seed(db)
        with pytest.raises(FieldReviewError, match="no extracted value"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="pay_date",
                verdict=FieldVerdict.REMOVED,
                note="not there",
            )


class TestAddingAField:
    async def test_an_added_field_reaches_the_snapshot(self, db: AsyncSession) -> None:
        loan_file, document, extraction = await _seed(db)
        await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="pay_date",
            verdict=FieldVerdict.ADDED,
            corrected_value="2026-01-31",
        )
        fields = await _pay_stub_fields(db, loan_file)
        assert fields["pay_date"].value == "2026-01-31"
        assert fields["pay_date"].source is FieldSource.CORRECTED

    async def test_a_key_the_document_type_does_not_declare_is_refused(
        self, db: AsyncSession
    ) -> None:
        # A key outside the schema specs is data no rule can ever read, so accepting
        # it would let a processor type a value into a field that reaches nobody.
        _loan_file, document, extraction = await _seed(db)
        with pytest.raises(FieldReviewError, match="declares"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="favourite_colour",
                verdict=FieldVerdict.ADDED,
                corrected_value="blue",
            )

    async def test_adding_over_an_extracted_value_is_refused(self, db: AsyncSession) -> None:
        # Correcting is the operation for that. Allowing `added` here would make
        # `replaced_value` null while a value WAS replaced, losing the model's
        # reading from the audit.
        _loan_file, document, extraction = await _seed(db)
        with pytest.raises(FieldReviewError, match="correct it rather than add it"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="gross_pay",
                verdict=FieldVerdict.ADDED,
                corrected_value="4200.00",
            )

    async def test_an_addition_needs_a_value(self, db: AsyncSession) -> None:
        _loan_file, document, extraction = await _seed(db)
        with pytest.raises(FieldReviewError, match="needs the value"):
            await record_review(
                db,
                document=document,
                extraction=extraction,
                field_key="pay_date",
                verdict=FieldVerdict.ADDED,
            )


class TestWhatTheModelSaidIsRemembered:
    """``replaced_value`` — the column that lets a correction survive re-extraction.

    Not consumed yet: carrying a correction across versions is the follow-up. It is
    captured NOW because it can only be captured now — after the next extraction
    lands, the value the processor overruled is gone from the current version and
    nothing can reconstruct what they were looking at.
    """

    async def test_a_correction_records_what_it_replaced(self, db: AsyncSession) -> None:
        _loan_file, document, extraction = await _seed(db)
        review = await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.CORRECTED,
            corrected_value="4200.00",
        )
        assert review.replaced_value == "54600.00"
        assert review.corrected_value == "4200.00"

    async def test_a_removal_records_it_too(self, db: AsyncSession) -> None:
        _loan_file, document, extraction = await _seed(db)
        review = await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="gross_pay",
            verdict=FieldVerdict.REMOVED,
            note="not on the document",
        )
        assert review.replaced_value == "54600.00"

    async def test_an_addition_replaced_nothing(self, db: AsyncSession) -> None:
        _loan_file, document, extraction = await _seed(db)
        review = await record_review(
            db,
            document=document,
            extraction=extraction,
            field_key="pay_date",
            verdict=FieldVerdict.ADDED,
            corrected_value="2026-01-31",
        )
        assert review.replaced_value is None
