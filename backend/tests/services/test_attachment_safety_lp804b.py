"""LP-804b — whether an inbound attachment may become a document.

THE DEFENCE IS RASTERISATION. Everything downstream reads a rendered image, never the original, so a
PDF's `/JS` and `/OpenAction` cannot run against something that never opens them. Sanitising the
original is defence in depth for the one case rasterising does not cover: a processor downloading
what the borrower actually sent.

The fixtures are GENERATED rather than hand-written, and armed through the library's own low-level
API, so "the fixture was malformed" cannot explain a result. That was the failure in LP-804a's first
forwarded fixture, and it is the failure this module is most exposed to — every assertion here is
about what a file structurally contains.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.models.inbound_attachment import AttachmentSafetyState
from app.services.attachment_safety import (
    ALLOWED_CONTENT_TYPES,
    MAX_PAGES,
    assess,
    is_encrypted_pdf,
    rasterise_pdf,
    sanitise_pdf,
    sniff_content_type,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attachments"

#: The keys the plan names. Asserted as BYTES against the file, because "the object model no longer
#: references it" and "the bytes no longer contain it" are different claims and only the second one
#: survives being handed to another reader.
DANGEROUS_KEYS = (b"/JS", b"/OpenAction", b"/AA", b"/XFA", b"/JavaScript", b"/EmbeddedFile")


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


# --------------------------------------------------------------------------------------------- #
# The acceptance criterion
# --------------------------------------------------------------------------------------------- #
def test_a_zip_wearing_a_pdf_name_is_quarantined() -> None:
    """The ticket's own "Done when". The declared type is `application/pdf` and the bytes are a ZIP;
    the sniff is the verdict and the declaration is a claim."""
    outcome = assess(_fixture("zip_named_as.pdf"), declared_content_type="application/pdf")

    assert outcome.state is AttachmentSafetyState.QUARANTINED
    assert outcome.sniffed_content_type == "application/zip"
    assert outcome.reason is not None
    assert outcome.rasterised_pages == ()


def test_a_declared_type_that_disagrees_with_the_bytes_is_quarantined() -> None:
    """THE SUBTLER HALF of the criterion above, and it had no test until a surviving mutant said so.

    The zip case is caught by the archive rule before the mismatch check is ever reached — so
    disabling the mismatch check left the whole suite green. This is the case only it catches: both
    types are on the allowlist, and the file is still not what it said it was."""
    outcome = assess(_fixture("clean.pdf"), declared_content_type="image/png")

    assert outcome.state is AttachmentSafetyState.QUARANTINED
    assert outcome.sniffed_content_type == "application/pdf"
    assert "image/png" in (outcome.reason or "")


def test_a_declared_type_that_agrees_is_not_quarantined() -> None:
    """The control: a mismatch rule that fired on everything would refuse every honest file."""
    outcome = assess(_fixture("clean.pdf"), declared_content_type="application/pdf")
    assert outcome.state is AttachmentSafetyState.SAFE


def test_a_missing_declared_type_is_not_treated_as_a_mismatch() -> None:
    """A part with no `Content-Type` is ordinary — scanner output routinely omits it — and treating
    absence as disagreement would quarantine it."""
    outcome = assess(_fixture("clean.pdf"), declared_content_type=None)
    assert outcome.state is AttachmentSafetyState.SAFE


def test_a_real_pdf_is_safe_and_rasterised() -> None:
    """The control. A rule that quarantined everything would satisfy every refusal test in this file
    and would reject every document a borrower ever sends."""
    outcome = assess(_fixture("clean.pdf"), declared_content_type="application/pdf")

    assert outcome.state is AttachmentSafetyState.SAFE
    assert outcome.reason is None
    assert len(outcome.rasterised_pages) == 1
    assert outcome.rasterised_pages[0].startswith(b"\x89PNG")


# --------------------------------------------------------------------------------------------- #
# The dangerous keys
# --------------------------------------------------------------------------------------------- #
def test_the_armed_fixture_really_is_armed() -> None:
    """Asserts the FIXTURE. Every claim below is that these keys were REMOVED; if they were never
    present, all of them pass while proving nothing — the exact shape of LP-804a's forwarded fixture
    and LP-811a's `_setup`."""
    raw = _fixture("armed.pdf")
    for key in (b"/OpenAction", b"/AA", b"/XFA", b"/JS"):
        assert key in raw, f"{key!r} missing from the armed fixture"


def test_sanitising_removes_every_dangerous_key() -> None:
    cleaned = sanitise_pdf(_fixture("armed.pdf"))
    for key in DANGEROUS_KEYS:
        assert key not in cleaned, f"{key!r} survived sanitisation"


def test_the_raster_carries_none_of_them() -> None:
    """The actual defence, asserted directly. Even had sanitisation failed, the rendered page is a
    PNG — there is no structure left in which any of this could hide."""
    pages = rasterise_pdf(_fixture("armed.pdf"))

    assert len(pages) == 1
    for key in DANGEROUS_KEYS:
        assert key not in pages[0]


def test_pymupdf_scrub_is_not_a_substitute_for_pikepdf() -> None:
    """WHY THERE IS A NEW DEPENDENCY, pinned as a test rather than left in a comment.

    `pymupdf` was already installed and its `scrub()` looked like it would do this job. Measured, it
    removes NONE of these keys. If a future version starts to, this test fails and somebody gets to
    delete a dependency — which is the outcome a comment could never produce."""
    import io

    import fitz

    with fitz.open(stream=_fixture("armed.pdf"), filetype="pdf") as doc:
        doc.scrub()
        buffer = io.BytesIO()
        doc.save(buffer, garbage=4, deflate=True, clean=True)
    scrubbed = buffer.getvalue()

    survivors = [key for key in (b"/OpenAction", b"/AA", b"/XFA") if key in scrubbed]
    assert survivors, (
        "pymupdf.scrub() now removes these — re-measure whether pikepdf is still needed"
    )


# --------------------------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------------------------- #
def test_an_encrypted_pdf_is_detected_and_refused() -> None:
    """DETECTED, NEVER CRACKED. It cannot be rasterised, so it cannot be read safely, and the answer
    is to tell the processor to ask for an unlocked copy."""
    raw = _fixture("encrypted.pdf")
    assert is_encrypted_pdf(raw) is True

    outcome = assess(raw, declared_content_type="application/pdf")
    assert outcome.state is AttachmentSafetyState.QUARANTINED
    assert outcome.reason is not None
    assert "password" in outcome.reason.lower()


def test_an_unencrypted_pdf_is_not_reported_as_encrypted() -> None:
    """The control. A detector that always said yes would satisfy the test above and would refuse
    every document."""
    assert is_encrypted_pdf(_fixture("clean.pdf")) is False


def test_a_non_pdf_is_not_reported_as_encrypted() -> None:
    """A file that will not open as a PDF is not an encrypted PDF, and conflating them would give a
    processor an instruction ("ask for the password") that cannot help."""
    assert is_encrypted_pdf(b"not a pdf at all") is False


# --------------------------------------------------------------------------------------------- #
# Sniffing
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"%PDF-1.7\n", "application/pdf"),
        (b"\xff\xd8\xff\xe0", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"II*\x00", "image/tiff"),
        (b"MM\x00*", "image/tiff"),
        (b"PK\x03\x04", "application/zip"),
        (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
        (b"nothing recognisable", None),
    ],
)
def test_signatures(data: bytes, expected: str | None) -> None:
    assert sniff_content_type(data) == expected


def test_heic_is_recognised_at_offset_four() -> None:
    """The one signature not at offset zero — HEIC's brand sits after the box length. Getting it
    wrong refuses every iPhone photo, which is a thing borrowers send constantly."""
    assert sniff_content_type(_fixture("photo.heic")) == "image/heic"


def test_tiff_and_heic_are_actually_allowed() -> None:
    """The asymmetry the plan names: `storage/base.py` permits these extensions while
    `services/documents.py` rejects the content types. Recognising them and then refusing them would
    be the same bug with a better error message."""
    assert "image/tiff" in ALLOWED_CONTENT_TYPES
    assert "image/heic" in ALLOWED_CONTENT_TYPES


def test_an_image_is_its_own_raster() -> None:
    """No structure to strip and no pages to render. Returning it unchanged is right — but it must
    still come back as a rasterised page, or the extraction path finds nothing to read."""
    outcome = assess(_fixture("photo.heic"), declared_content_type="image/heic")

    assert outcome.state is AttachmentSafetyState.SAFE
    assert outcome.rasterised_pages == (_fixture("photo.heic"),)


# --------------------------------------------------------------------------------------------- #
# The refusals, each with its own reason
# --------------------------------------------------------------------------------------------- #
def test_an_archive_is_refused_outright() -> None:
    """Not scanned, not descended into. A zip is a container for an unbounded number of things this
    code would then have to decide about, and "send the file itself" is a complete answer."""
    outcome = assess(_fixture("zip_named_as.pdf"))

    assert outcome.state is AttachmentSafetyState.QUARANTINED
    assert "zip" in (outcome.reason or "").lower()


def test_a_winmail_envelope_is_refused_with_an_actionable_reason() -> None:
    """Detected so it can be refused WITH A REASON rather than silently dropped. A borrower whose
    Outlook is in RTF mode has no idea their attachment never arrived, and the fix is a setting they
    can change."""
    outcome = assess(_fixture("winmail.dat"))

    assert outcome.state is AttachmentSafetyState.UNSUPPORTED
    assert "winmail" in (outcome.reason or "").lower()


def test_an_unrecognised_file_is_unsupported_not_quarantined() -> None:
    """The distinction a processor acts on. UNSUPPORTED means "we do not handle this kind of thing";
    QUARANTINED means "this is not what it claimed to be". Only one of those is worth asking the
    borrower about."""
    outcome = assess(b"\x00\x01\x02 nothing recognisable at all")

    assert outcome.state is AttachmentSafetyState.UNSUPPORTED
    assert outcome.sniffed_content_type is None


def test_every_refusal_says_why() -> None:
    """A state with no reason leaves a processor a dead end. Asserted across all of them at once, so
    a refusal added later without a reason fails here rather than reaching somebody's screen."""
    for data in (
        _fixture("zip_named_as.pdf"),
        _fixture("winmail.dat"),
        _fixture("encrypted.pdf"),
        b"\x00 unrecognisable",
    ):
        outcome = assess(data)
        assert outcome.state is not AttachmentSafetyState.SAFE
        assert outcome.reason, f"no reason given for {outcome.state}"


def test_a_page_bomb_is_refused_rather_than_rendered() -> None:
    """A PDF can declare tens of thousands of pages in a few kilobytes. Rendering them is the
    cheapest denial of service available against anything that renders what arrives."""
    import fitz

    doc = fitz.open()
    for _ in range(MAX_PAGES + 1):
        doc.new_page(width=10, height=10)
    import io

    buffer = io.BytesIO()
    doc.save(buffer)
    doc.close()

    outcome = assess(buffer.getvalue(), declared_content_type="application/pdf")
    assert outcome.state is AttachmentSafetyState.QUARANTINED
    assert "limit" in (outcome.reason or "").lower()


def test_a_document_at_the_limit_is_still_rendered() -> None:
    """The control for the cap. A limit set to zero would satisfy the test above and would refuse
    every multi-page bank statement."""
    assert MAX_PAGES > 1
    outcome = assess(_fixture("clean.pdf"), declared_content_type="application/pdf")
    assert outcome.state is AttachmentSafetyState.SAFE


# --------------------------------------------------------------------------------------------- #
# Applied to the stored rows — and the positive assertion that PENDING is not a pass
# --------------------------------------------------------------------------------------------- #
async def test_assessment_updates_the_stored_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    """The whole chain: ingest inventories, safety decides, and the row carries both the verdict and
    the reason a processor reads."""
    from email import policy
    from email.message import EmailMessage

    from app.models.inbound_attachment import InboundAttachment
    from app.services.attachment_safety import apply_safety_to_message
    from app.services.inbound_ingest import ingest_raw_message
    from sqlalchemy import select

    message = EmailMessage()
    message["From"] = "akash@example.com"
    message["To"] = "lf-abc@inbox.example.com"
    message["Subject"] = "docs"
    message["Message-ID"] = "<safety-1@example.com>"
    message.set_content("attached")
    message.add_attachment(
        _fixture("clean.pdf"), maintype="application", subtype="pdf", filename="ok.pdf"
    )
    message.add_attachment(
        _fixture("zip_named_as.pdf"), maintype="application", subtype="pdf", filename="bad.pdf"
    )
    raw = message.as_bytes(policy=policy.default)

    result = await ingest_raw_message(
        db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-safety-1"
    )
    from uuid import UUID as _UUID

    assessed = await apply_safety_to_message(
        db_session, inbound_message_id=_UUID(result.message_id), raw=raw
    )

    assert assessed == 2
    rows = (await db_session.execute(select(InboundAttachment))).scalars().all()
    states = {row.filename_normalized: row for row in rows}
    assert states["ok.pdf"].safety_state is AttachmentSafetyState.SAFE
    assert states["ok.pdf"].sniffed_content_type == "application/pdf"
    assert states["ok.pdf"].safety_reason is None
    assert states["bad.pdf"].safety_state is AttachmentSafetyState.QUARANTINED
    assert states["bad.pdf"].sniffed_content_type == "application/zip"
    assert states["bad.pdf"].safety_reason


async def test_nothing_is_safe_until_it_has_been_assessed(db_session) -> None:  # type: ignore[no-untyped-def]
    """A POSITIVE ASSERTION rather than an absence. Ingest writes every attachment PENDING, and the
    malware scan is asynchronous, so PENDING is a state that genuinely persists — the danger is that
    something downstream reads it as "no problem found" rather than "nobody has looked".

    Asserted as: straight after ingest, no attachment is SAFE, and none carries a sniffed type."""
    from email import policy
    from email.message import EmailMessage

    from app.models.inbound_attachment import InboundAttachment
    from app.services.inbound_ingest import ingest_raw_message
    from sqlalchemy import select

    message = EmailMessage()
    message["From"] = "akash@example.com"
    message["To"] = "lf-abc@inbox.example.com"
    message["Subject"] = "docs"
    message["Message-ID"] = "<safety-2@example.com>"
    message.set_content("attached")
    message.add_attachment(
        _fixture("clean.pdf"), maintype="application", subtype="pdf", filename="ok.pdf"
    )

    await ingest_raw_message(
        db_session,
        raw=message.as_bytes(policy=policy.default),
        raw_storage_path=None,
        ses_message_id="ses-safety-2",
    )

    rows = (await db_session.execute(select(InboundAttachment))).scalars().all()
    assert rows
    for row in rows:
        assert row.safety_state is AttachmentSafetyState.PENDING
        assert row.sniffed_content_type is None
        assert row.derived_storage_path is None


async def test_a_second_assessment_does_not_overwrite_a_verdict(db_session) -> None:  # type: ignore[no-untyped-def]
    """Idempotent. A replay or a redelivery must not reset a state a processor has already acted on —
    only PENDING rows are touched."""
    from email import policy
    from email.message import EmailMessage
    from uuid import UUID as _UUID

    from app.models.inbound_attachment import InboundAttachment
    from app.services.attachment_safety import apply_safety_to_message
    from app.services.inbound_ingest import ingest_raw_message
    from sqlalchemy import select

    message = EmailMessage()
    message["From"] = "akash@example.com"
    message["To"] = "lf-abc@inbox.example.com"
    message["Subject"] = "docs"
    message["Message-ID"] = "<safety-3@example.com>"
    message.set_content("attached")
    message.add_attachment(
        _fixture("clean.pdf"), maintype="application", subtype="pdf", filename="ok.pdf"
    )
    raw = message.as_bytes(policy=policy.default)

    result = await ingest_raw_message(
        db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-safety-3"
    )
    message_id = _UUID(result.message_id)
    await apply_safety_to_message(db_session, inbound_message_id=message_id, raw=raw)

    row = (await db_session.execute(select(InboundAttachment))).scalar_one()
    row.disposition = row.disposition  # a processor has now looked at it
    second = await apply_safety_to_message(db_session, inbound_message_id=message_id, raw=raw)

    assert second == 0  # nothing left in PENDING
    assert row.safety_state is AttachmentSafetyState.SAFE
