"""Deciding whether an inbound attachment may be treated as a document (LP-804b).

THE DEFENCE IS RASTERISATION, NOT SANITISATION. Everything downstream reads a rendered image of each
page, never the original file. A PDF's `/JS`, `/OpenAction` and friends cannot run against something
that never opens them — and the raster was MEASURED to carry none of those keys. Sanitising the
original is defence in depth for the one case rasterising does not cover: a processor downloading
what the borrower actually sent.

WHY `pikepdf` AND NOT `pymupdf.scrub()`. `pymupdf` is already a dependency and its `scrub()` looked
like it would do the job. It does not. Measured on a PDF built by pymupdf itself and armed through
its own low-level API: after `scrub()`, `/OpenAction`, `/AA`, `/Names/JavaScript` and `/XFA` were all
still present and the catalog keys were still set. `pikepdf` removes all of them. That is why one
dependency was added and not the other — `pypdfium2` was NOT added, because `pymupdf` already
rasterises and a second renderer is a second thing to keep patched on a path whose entire job is
reading hostile input.

NO `puremagic` EITHER. The allowlist is six types. An explicit signature table over a closed set is
smaller and more auditable than a library that recognises three hundred formats — on this path, more
recognition is more surface, not less.

THE SNIFF IS THE VERDICT, THE DECLARATION IS A CLAIM. `Content-Type` is written by the sender. A
`.pdf` that sniffs as a ZIP is quarantined, which is the ticket's own acceptance criterion, and the
same rule catches the reverse: nothing is trusted because of what it says it is.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import fitz
import pikepdf

from app.core.logging import get_logger
from app.models.inbound_attachment import AttachmentSafetyState, InboundAttachment

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

#: What a borrower may send. TIFF and HEIC are HERE AND NOT IN `services/documents.py`, which is the
#: asymmetry the plan names: `storage/base.py` already permits the extensions while the upload path
#: rejects the content types, and borrowers email HEIC from iPhones constantly. Resolving that for
#: the UPLOAD path is a different ticket; this is the inbound one.
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/heic",
    }
)

#: Archives are refused OUTRIGHT in V1, per the plan. Not scanned, not opened, not descended into: a
#: zip is a container for an unbounded number of things this code would then have to decide about,
#: and "reject and ask the borrower to send the file itself" is a complete answer.
_ARCHIVE_TYPES = frozenset(
    {"application/zip", "application/x-7z-compressed", "application/x-rar", "application/gzip"}
)

#: Microsoft's TNEF envelope. Detected so it can be REFUSED WITH A REASON rather than silently
#: dropped — see `winmail.dat` in the ticket doc. Not parsed: that needs another dependency for a
#: case Outlook produces only in RTF mode.
_TNEF_TYPE = "application/vnd.ms-tnef"

#: Magic-byte signatures, as (offset, bytes, content_type). Explicit because the allowlist is closed
#: and a table anyone can read beats a dependency nobody audits.
_SIGNATURES: tuple[tuple[int, bytes, str], ...] = (
    (0, b"%PDF-", "application/pdf"),
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"II*\x00", "image/tiff"),  # little-endian
    (0, b"MM\x00*", "image/tiff"),  # big-endian
    (0, b"PK\x03\x04", "application/zip"),
    (0, b"PK\x05\x06", "application/zip"),  # empty archive
    (0, b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (0, b"Rar!\x1a\x07", "application/x-rar"),
    (0, b"\x1f\x8b", "application/gzip"),
    (0, b"\x78\x9f\x3e\x22", _TNEF_TYPE),
)

#: HEIC and its relatives live in an ISO base media container: the brand sits at offset 4, after the
#: box length. Handled separately because it is the one type in the allowlist whose signature is not
#: at offset zero — and getting that wrong means every iPhone photo is refused.
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"})

#: PDF catalog keys that can execute something or carry a payload. Removed wholesale rather than
#: inspected: there is no legitimate reason for a borrower's bank statement to carry any of them.
_DANGEROUS_CATALOG_KEYS = ("/OpenAction", "/AA", "/Names", "/AcroForm")

#: Rendering resolution for the derivative. 150 is legible for a scanned payslip without making a
#: forty-page statement enormous.
RASTER_DPI = 150

#: A page count past which rasterising is refused rather than attempted. A PDF can declare tens of
#: thousands of pages in a few kilobytes, and rendering them is the cheapest denial of service there
#: is against a service that renders whatever arrives.
MAX_PAGES = 200


@dataclass(frozen=True)
class SafetyOutcome:
    """What was decided about one attachment, and why."""

    state: AttachmentSafetyState
    sniffed_content_type: str | None
    #: Why it was refused, in words a processor can act on. None when the state is SAFE.
    reason: str | None = None
    #: The sanitised original, when there was something to sanitise.
    sanitised: bytes | None = None
    #: One PNG per page. What everything downstream is allowed to read.
    rasterised_pages: tuple[bytes, ...] = ()


def sniff_content_type(data: bytes) -> str | None:
    """What the BYTES say this is, or None.

    Never consults the declared type. That is the whole point: a `.pdf` that sniffs as a ZIP is
    quarantined, and it is quarantined because of what it contains rather than what it claims.
    """
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "image/heic"
    for offset, signature, content_type in _SIGNATURES:
        if data[offset : offset + len(signature)] == signature:
            return content_type
    return None


def is_encrypted_pdf(data: bytes) -> bool:
    """Whether this PDF is password-protected.

    DETECTED, NEVER CRACKED. An encrypted document cannot be rasterised, so it cannot be read
    safely; the answer is to tell the processor so they can ask the borrower for an unlocked copy.
    Attempting to guess a password would be both useless and the wrong posture for a system holding
    other people's financial documents.
    """
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return bool(doc.is_encrypted)
    except Exception:
        return False


def _strip_dangerous_annotations(page: pikepdf.Page) -> None:
    """Drop page annotations that carry a payload or an action, leaving ordinary ones alone.

    THE CATALOG IS NOT THE ONLY PLACE THESE LIVE, which is the half `_DANGEROUS_CATALOG_KEYS` does
    not reach. An `/EmbeddedFile` can hang off a `/FileAttachment` annotation instead of the
    catalog's `/Names` tree, and a `/Launch` action can sit in an annotation's `/A` rather than in
    `/OpenAction`. Measured before this existed: an embedded executable and a `/Launch` action, both
    attached to a page, passed through `sanitise_pdf` completely untouched — while the test asserting
    "no dangerous key survives" passed, because the armed fixture carried neither.

    Both are named in the build plan's list of what pikepdf must strip.

    Annotations are removed SELECTIVELY here rather than wholesale: a `/Link` to a URL is ordinary in
    a lender's PDF, and dropping every annotation would take legitimate ones with it. What goes is
    the subtype that exists to carry a file, and any action that launches or scripts.
    """
    if "/Annots" not in page:
        return
    kept = []
    for annot in page.Annots:
        subtype = str(annot.get("/Subtype", ""))
        action = annot.get("/A")
        action_kind = str(action.get("/S", "")) if isinstance(action, pikepdf.Dictionary) else ""
        if subtype == "/FileAttachment" or action_kind in ("/Launch", "/JavaScript"):
            continue
        # An ordinary annotation can still carry an embedded file on a filespec.
        if "/FS" in annot:
            del annot["/FS"]
        kept.append(annot)
    if kept:
        page.Annots = kept
    else:
        del page["/Annots"]


def sanitise_pdf(data: bytes) -> bytes:
    """Strip every catalog key that can execute something or carry a payload.

    `pikepdf`, because `pymupdf.scrub()` was measured NOT to remove them — see the module docstring.
    Removing the containers wholesale rather than walking them: `/Names` also holds harmless
    destinations, and losing those costs a named-anchor jump in a document nobody navigates by
    anchor, which is a trade worth making without thinking about it.
    """
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for key in _DANGEROUS_CATALOG_KEYS:
            if key in pdf.Root:
                del pdf.Root[key]
        for page in pdf.pages:
            _strip_dangerous_annotations(page)
        buffer = io.BytesIO()
        pdf.save(buffer)
        return buffer.getvalue()


def rasterise_pdf(data: bytes, *, dpi: int = RASTER_DPI) -> tuple[bytes, ...]:
    """One PNG per page. What the extraction path reads.

    Raises :class:`ValueError` past :data:`MAX_PAGES` — a PDF can declare tens of thousands of pages
    in a few kilobytes, and rendering them all is the cheapest denial of service available against
    anything that renders what arrives.
    """
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.page_count > MAX_PAGES:
            raise ValueError(f"{doc.page_count} pages exceeds the {MAX_PAGES}-page limit")
        return tuple(page.get_pixmap(dpi=dpi).tobytes("png") for page in doc)


def assess(data: bytes, *, declared_content_type: str | None = None) -> SafetyOutcome:
    """Decide whether ``data`` may become a document.

    Returns an outcome; never raises. Every failure path produces a state and a REASON, because the
    processor's next action differs — an encrypted PDF means "ask for an unlocked copy", a
    mismatched sniff means "this is not what it said it was", and an unreadable file means "ask them
    to send it again".
    """
    sniffed = sniff_content_type(data)

    if sniffed is None:
        return SafetyOutcome(
            AttachmentSafetyState.UNSUPPORTED,
            None,
            reason="The file type could not be identified.",
        )

    if sniffed in _ARCHIVE_TYPES:
        # QUARANTINED, not UNSUPPORTED. An archive is refused because of what it could contain, not
        # because it is a kind of document we happen not to handle — and the distinction is what a
        # processor reads when deciding whether to ask for it again.
        return SafetyOutcome(
            AttachmentSafetyState.QUARANTINED,
            sniffed,
            reason="Archives are not accepted. Ask for the file itself rather than a zip.",
        )

    if sniffed == _TNEF_TYPE:
        return SafetyOutcome(
            AttachmentSafetyState.UNSUPPORTED,
            sniffed,
            reason=(
                "This arrived as a winmail.dat envelope, which hides the real attachment. "
                "Ask the sender to resend with formatting set to plain text or HTML."
            ),
        )

    if sniffed not in ALLOWED_CONTENT_TYPES:
        return SafetyOutcome(
            AttachmentSafetyState.UNSUPPORTED,
            sniffed,
            reason=f"{sniffed} is not a document type this system accepts.",
        )

    declared = (declared_content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared in ALLOWED_CONTENT_TYPES and declared != sniffed:
        # THE ACCEPTANCE CRITERION, and the reason the sniff exists. A `.pdf` that is really a ZIP is
        # caught above by the archive rule; this catches the subtler case where both types are
        # allowed and the file is still not what it said it was.
        logger.warning("attachment_type_mismatch", declared=declared, sniffed=sniffed)
        return SafetyOutcome(
            AttachmentSafetyState.QUARANTINED,
            sniffed,
            reason=f"The file says it is {declared} but its contents are {sniffed}.",
        )

    if sniffed != "application/pdf":
        # An image has no executable structure to strip and no pages to render — it IS the raster.
        return SafetyOutcome(AttachmentSafetyState.SAFE, sniffed, rasterised_pages=(data,))

    if is_encrypted_pdf(data):
        return SafetyOutcome(
            AttachmentSafetyState.QUARANTINED,
            sniffed,
            reason=(
                "This PDF is password-protected, so its contents cannot be read. "
                "Ask for a copy without a password."
            ),
        )

    try:
        sanitised = sanitise_pdf(data)
        pages = rasterise_pdf(sanitised)
    except ValueError as exc:
        return SafetyOutcome(AttachmentSafetyState.QUARANTINED, sniffed, reason=str(exc))
    except Exception:
        logger.warning("attachment_pdf_unreadable")
        return SafetyOutcome(
            AttachmentSafetyState.QUARANTINED,
            sniffed,
            reason="This PDF could not be read. Ask for it to be sent again.",
        )

    if not pages:
        return SafetyOutcome(
            AttachmentSafetyState.QUARANTINED, sniffed, reason="This PDF has no pages."
        )

    return SafetyOutcome(
        AttachmentSafetyState.SAFE, sniffed, sanitised=sanitised, rasterised_pages=pages
    )


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "MAX_PAGES",
    "RASTER_DPI",
    "SafetyOutcome",
    "apply_safety_to_message",
    "assess",
    "is_encrypted_pdf",
    "rasterise_pdf",
    "sanitise_pdf",
    "sniff_content_type",
]


async def apply_safety_to_message(db: AsyncSession, *, inbound_message_id: UUID, raw: bytes) -> int:
    """Assess every attachment on one message and record the verdict. Returns how many were assessed.

    RE-PARSES THE RAW MESSAGE rather than storing the bytes twice. The `.eml` is the record of what
    arrived; a second copy of a borrower's document is a second thing to secure, retain and destroy.
    Matched back to the stored rows by sha256, which is what that column is for.

    IDEMPOTENT. Only rows still in ``PENDING`` are touched, so a re-run after a redelivery or a
    replay cannot overwrite a verdict a processor has already acted on.

    `derived_storage_path` IS NOT SET HERE. The rasterised pages are produced and thrown away: where
    they are stored is a bucket-and-path decision that belongs with LP-806, which is what turns an
    accepted attachment into a `Document`. Producing them now proves they CAN be produced — which is
    the half of the safety decision that would otherwise be assumed.
    """
    from sqlalchemy import select

    from app.services.inbound_mime import parse_message

    parsed = parse_message(raw)
    by_hash = {attachment.sha256: attachment for attachment in parsed.attachments}

    # LP-819 — A BOUNCE IS NOT A DOCUMENT, and it is the shape that most looks like one: a DSN is an
    # email, addressed to the file's inbox, and it CARRIES THE ORIGINAL MESSAGE AS AN ATTACHMENT.
    # Assessed normally that attachment is a well-formed message or PDF and comes back SAFE — so the
    # borrower's own request would be filed back onto their file as though they had sent it.
    from app.models.inbound_message import InboundMessage

    message = await db.get(InboundMessage, inbound_message_id)
    is_notification = bool(message and (message.is_dsn or message.is_auto_reply))

    rows = (
        (
            await db.execute(
                select(InboundAttachment).where(
                    InboundAttachment.inbound_message_id == inbound_message_id,
                    InboundAttachment.safety_state == AttachmentSafetyState.PENDING,
                )
            )
        )
        .scalars()
        .all()
    )

    assessed = 0
    for row in rows:
        attachment = by_hash.get(row.sha256)
        if attachment is None:
            # The row exists and the part does not. That is not a bug to raise over — it means the
            # raw message no longer contains what it did — but it must not silently stay PENDING and
            # read as "not looked at yet" forever.
            row.safety_state = AttachmentSafetyState.UNSUPPORTED
            row.safety_reason = "This attachment could not be found in the stored message."
            assessed += 1
            continue
        if is_notification:
            row.safety_state = AttachmentSafetyState.UNSUPPORTED
            row.sniffed_content_type = sniff_content_type(attachment.content)
            row.safety_reason = (
                "This arrived on a bounce or an automatic reply, not from the borrower. "
                "It is the original message coming back, not a document they sent."
            )
            assessed += 1
            continue
        outcome = assess(attachment.content, declared_content_type=row.declared_content_type)
        row.safety_state = outcome.state
        row.sniffed_content_type = outcome.sniffed_content_type
        row.safety_reason = outcome.reason
        assessed += 1

    await db.flush()
    # METADATA ONLY — a count and the states reached. Never the filename or the type, which say what
    # a borrower sent.
    logger.info(
        "inbound_attachments_assessed",
        count=assessed,
        quarantined=sum(1 for row in rows if row.safety_state is AttachmentSafetyState.QUARANTINED),
    )
    return assessed
