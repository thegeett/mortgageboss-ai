"""Opening a round from an arriving sheet (LP-905 section 1, spec §6).

The service, not the endpoint: what a round looks like the instant a sheet lands, before anything has
read it. The endpoint's own tests live beside the other API tests; these pin the properties the spec
states about the row itself.
"""

from __future__ import annotations

import pymupdf
import pytest
from app.models.activity_log import ActivityLog, ActivityType
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import (
    ConditionRoundCompleteness,
    ConditionRoundStatus,
    ConditionSheetFormat,
    ConditionSourceKind,
)
from app.services.condition_rounds import (
    ConditionSheetRejected,
    SheetBytes,
    create_round_from_sheet,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.models.conftest_helpers import make_company, make_loan_file


def _pdf(text: str = "LOAN APPROVAL CONDITIONS - RIVERA - 1226500417") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72.0, 100.0), text, fontsize=9)
    return bytes(document.tobytes())


async def _round(db: AsyncSession, *, content: bytes | None = None, **kwargs: object):  # type: ignore[no-untyped-def]
    company = await make_company(db)
    loan_file = await make_loan_file(db, company=company)
    return await create_round_from_sheet(
        db,
        loan_file=loan_file,
        sheet=SheetBytes(
            content=content if content is not None else _pdf(),
            source_kind=ConditionSourceKind.PDF_UPLOAD,
        ),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_a_new_round_starts_parsing_and_unread(db_session: AsyncSession) -> None:
    """⚠️ THE ROUND EXISTS BEFORE IT IS READ. `status` is PARSING and `sheet_format` is the GENERIC
    default until the task fills them in — which is what lets the endpoint answer 202 immediately
    with a row the UI can poll (screen S1-02) instead of holding the request open across a parse."""
    round_ = await _round(db_session)

    assert round_.status is ConditionRoundStatus.PARSING
    assert round_.sheet_format is ConditionSheetFormat.GENERIC
    assert round_.draft_rows is None
    assert round_.header is None
    assert round_.date_printed is None
    assert round_.round_number is None


async def test_the_round_is_dated_by_arrival_because_nothing_has_read_it(
    db_session: AsyncSession,
) -> None:
    """⚠️ `round_date` IS NOT NULL WITH NO DEFAULT. Until the sheet is read there is no printed
    date, so the round is dated by arrival and `date_printed` stays null. Omitting it fails the
    insert outright — the same shape as the `display_id` defect that hid LP-904's guards."""
    round_ = await _round(db_session)

    assert round_.round_date is not None
    assert round_.date_printed is None


async def test_the_source_records_how_it_arrived(db_session: AsyncSession) -> None:
    """`sources` is a LIST from the first arrival, because LP-907 appends the PDF to a pasted round
    rather than replacing what was there."""
    round_ = await _round(db_session)

    assert len(round_.sources) == 1
    source = round_.sources[0]
    assert source["kind"] == ConditionSourceKind.PDF_UPLOAD.value
    assert source["storage_path"].startswith("condition-sheets/")
    assert "at" in source


async def test_the_storage_path_is_server_controlled(db_session: AsyncSession) -> None:
    """⚠️ NEVER DERIVED FROM THE UPLOAD'S FILENAME. A real sheet's filename routinely carries the
    borrower's surname and the loan number, so building a path from it would write NPI into the
    storage layout itself."""
    round_ = await _round(db_session)
    path = round_.sources[0]["storage_path"]

    assert path.startswith(f"condition-sheets/{round_.company_id}/{round_.loan_file_id}/")
    assert path.endswith(".pdf")


async def test_completeness_defaults_to_full_and_can_be_set(db_session: AsyncSession) -> None:
    """ADR-404: only a FULL round's absences mean anything. A processor uploading the lender's
    letter is giving us the whole list unless they say otherwise."""
    full = await _round(db_session)
    assert full.completeness is ConditionRoundCompleteness.FULL

    partial = await _round(db_session, completeness=ConditionRoundCompleteness.PARTIAL)
    assert partial.completeness is ConditionRoundCompleteness.PARTIAL


async def test_arrival_writes_a_round_received_event(db_session: AsyncSession) -> None:
    """Every state change writes a `condition_event` (spec §9.6), and the detail carries metadata
    only — never the sheet's text."""
    round_ = await _round(db_session)

    events = (
        (
            await db_session.execute(
                select(ConditionEvent).where(ConditionEvent.round_id == round_.id)
            )
        )
        .scalars()
        .all()
    )

    assert [e.kind for e in events] == [ConditionEventKind.ROUND_RECEIVED]
    assert events[0].company_id == round_.company_id
    assert set(events[0].detail) == {"source_kind", "bytes"}


async def test_arrival_writes_a_timeline_entry(db_session: AsyncSession) -> None:
    """Spec §LP-905: "Condition sheet received" on the file timeline.

    ⚠️ ITS OWN ACTIVITY TYPE, not DOCUMENT_UPLOADED. A condition sheet is not a borrower document —
    it never enters classify → extract → needs — and filing it under "document uploaded" would
    invite exactly the confusion ADR-403's boundary exists to prevent.
    """
    round_ = await _round(db_session)

    entries = (
        (
            await db_session.execute(
                select(ActivityLog).where(ActivityLog.loan_file_id == round_.loan_file_id)
            )
        )
        .scalars()
        .all()
    )
    conditions = [e for e in entries if e.activity_type is ActivityType.CONDITION_SHEET_RECEIVED]

    assert len(conditions) == 1
    assert conditions[0].summary == "Condition sheet received"
    assert conditions[0].detail["round_id"] == str(round_.id)


async def test_no_document_row_is_created(db_session: AsyncSession) -> None:
    """⚠️ THE BOUNDARY ADR-403 EXISTS FOR. The sheet is stored, not documented: no `Document` row
    means it cannot enter classify → extract → needs, cannot be matched against a need, and cannot
    be classified against a 166-type borrower taxonomy that has no bucket for it."""
    from app.models.document import Document

    round_ = await _round(db_session)

    documents = (
        (
            await db_session.execute(
                select(Document).where(Document.loan_file_id == round_.loan_file_id)
            )
        )
        .scalars()
        .all()
    )

    assert documents == []


async def test_a_non_pdf_is_refused_with_a_reason(db_session: AsyncSession) -> None:
    """⚠️ `assess` RETURNS SAFE FOR AN IMAGE TOO — "an image has no executable structure to strip
    and no pages to render — it IS the raster". So the state alone does not mean PDF, and a reader
    keyed only on it would accept a screenshot of a sheet and fail deep inside the parser, where the
    message means nothing to a processor."""
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with pytest.raises(ConditionSheetRejected) as caught:
        await _round(db_session, content=png)

    # ⚠️ ASSERT THE PROPERTY, NOT A WORD, AND NOT A HARDCODED CLAIM EITHER. This assertion has been
    # wrong twice. First it looked for the literal "PDF", which the message never contained. Then it
    # required "application/pdf" — true only while the service HARDCODED that as the declared type;
    # once the declared type came from the caller (review Q1) this path stopped mentioning it at all.
    #
    # The durable property is the one a processor acts on: the message names what they ACTUALLY
    # sent. Nothing is declared here, so `assess` cannot report a mismatch and the PDF-only check
    # below it is what refuses.
    reason = caught.value.reason
    assert "image/png" in reason, reason


async def test_the_refusal_quotes_what_the_sender_CLAIMED(db_session: AsyncSession) -> None:
    """⚠️ THE DECLARED TYPE BELONGS TO THE CALLER (review Q1), and this is why it matters.

    `assess`'s mismatch message is a claim about the SENDER — "this is not what it said it was". The
    service used to hardcode `application/pdf` as the declared type, which made that sentence true
    for an upload and false for a forwarded email: a real PDF attached as `application/octet-stream`
    would have been told it "says it is application/pdf" when it said no such thing.

    Same bytes, three declarations, three honest messages.
    """
    from app.services.condition_rounds import _reject_unless_pdf

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    with pytest.raises(ConditionSheetRejected) as claimed_pdf:
        _reject_unless_pdf(png, declared_content_type="application/pdf")
    assert "says it is application/pdf" in claimed_pdf.value.reason

    with pytest.raises(ConditionSheetRejected) as claimed_nothing_useful:
        _reject_unless_pdf(png, declared_content_type="application/octet-stream")
    # It never claimed to be a PDF, so it is not accused of having claimed one.
    assert "says it is application/pdf" not in claimed_nothing_useful.value.reason
    assert "image/png" in claimed_nothing_useful.value.reason


async def test_rubbish_is_refused_rather_than_stored(db_session: AsyncSession) -> None:
    with pytest.raises(ConditionSheetRejected):
        await _round(db_session, content=b"this is not a file of any kind")
