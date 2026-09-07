"""Pull a raw inbound message out of storage, record what SES said, and stop (LP-803).

DELIBERATELY INCURIOUS. This does not parse MIME (LP-804), does not decide which loan file the
message belongs to (LP-805), and does not create documents. It pulls bytes, computes an ingest key,
writes one row, and returns. Everything it stores is either a fact SES asserted or a fact about the
bytes themselves.

THE DEDUP CONTRACT IS THE TICKET. A provider redelivers: SQS is at-least-once by design, and SES
retries. The same message arriving twice must produce exactly ONE row and a SUCCESS — a non-2xx on a
duplicate drives a provider into its retry schedule forever, which is how a single message becomes a
sustained load with no error anywhere that looks like the cause.

VERDICTS COME FROM THE SES RECEIPT AND NOWHERE ELSE. An `Authentication-Results` header inside the
message is written by whoever sent it. The receipt is SES's own finding about the delivery it
accepted. Reading the header would let a sender assert their own DKIM pass.
"""

from __future__ import annotations

import email
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.inbound_attachment import InboundAttachment
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.services.inbound_mime import parse_message
from app.storage import get_storage_backend

logger = get_logger(__name__)

#: Verdict keys SES reports on the `receipt` object. Copied across verbatim, including values this
#: code has never seen — an unknown verdict must survive to be looked at, not be dropped for being
#: unrecognised.
_RECEIPT_VERDICT_KEYS = (
    "spfVerdict",
    "dkimVerdict",
    "dmarcVerdict",
    "dmarcPolicy",
    "spamVerdict",
    "virusVerdict",
)

#: RFC 3834's marker for automatically generated mail, plus the two conventions that predate it and
#: are still what most autoresponders actually send.
_AUTO_REPLY_HEADERS = ("auto-submitted", "x-autoreply", "x-autorespond")

_ANGLE = re.compile(r"<([^>]+)>")


@dataclass(frozen=True)
class IngestResult:
    """What happened. ``created`` is False when the message was already stored."""

    message_id: str
    created: bool
    ingest_key: str


def normalise_message_id(raw: str | None) -> str | None:
    """`Message-ID` with the angle brackets and whitespace removed, or None.

    Normalised because the same id arrives spelled differently — with and without brackets, with
    folded whitespace — and a dedup key that treats those as different ids does not dedup.
    """
    if not raw:
        return None
    stripped = raw.strip()
    if found := _ANGLE.search(stripped):
        stripped = found.group(1)
    collapsed = " ".join(stripped.split())
    return collapsed or None


def compute_ingest_key(*, ses_message_id: str | None, message_id: str | None, raw: bytes) -> str:
    """``ses_message_id | normalised Message-ID | sha256(raw)`` — the first that exists.

    ORDERED BY HOW HARD IT IS TO FORGE, not by convenience. The SES id is assigned by SES. The
    `Message-ID` header is written by the sender. The hash is a fact about the bytes. Preferring the
    header over the hash is still right — a message legitimately redelivered has the same header and
    may not have byte-identical bytes, because a relay can add headers on the way.
    """
    if ses_message_id:
        return ses_message_id
    if normalised := normalise_message_id(message_id):
        return normalised
    return hashlib.sha256(raw).hexdigest()


def extract_receipt_verdicts(receipt: dict[str, Any] | None) -> dict[str, Any]:
    """The verdicts SES recorded, verbatim.

    Every value is copied AS GIVEN. `dmarcVerdict: GRAY` stays GRAY; it is not coerced to PASS, not
    normalised to a boolean, and not dropped for being neither PASS nor FAIL. GRAY means SES could
    not decide, and a routing rule that treats "could not decide" as "passed" is the whole reason
    this is stated rather than assumed.
    """
    if not isinstance(receipt, dict):
        return {}
    verdicts: dict[str, Any] = {}
    for key in _RECEIPT_VERDICT_KEYS:
        value = receipt.get(key)
        if isinstance(value, dict) and "status" in value:
            verdicts[key] = value["status"]
        elif value is not None:
            verdicts[key] = value
    return verdicts


def _addresses(parsed: Message, header: str) -> list[str]:
    values = parsed.get_all(header, [])
    return [addr for _name, addr in getaddresses(values) if addr]


def _received_at(parsed: Message) -> datetime | None:
    raw = parsed.get("Date")
    if not raw:
        return None
    try:
        parsed_date = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed_date.tzinfo is None:
        return parsed_date.replace(tzinfo=UTC)
    return parsed_date


def is_delivery_status_notification(parsed: Message) -> bool:
    """Whether this is a bounce.

    TWO SIGNALS, EITHER SUFFICIENT. `multipart/report; report-type=delivery-status` is the standard
    shape; an empty `Return-Path: <>` is the older convention and is what RFC 5321 requires of a
    notification so it cannot itself bounce. Real bounces in the wild carry one, the other, or both.

    Getting this wrong files a bounce as a borrower document: it is an email, addressed to the file's
    inbox, and it usually carries the original message as an attachment.
    """
    content_type = (parsed.get_content_type() or "").lower()
    # `get_param` returns a 3-tuple for an RFC 2231 encoded parameter and a str otherwise. A bounce
    # would never encode `report-type`, but an attacker-shaped message can, and indexing a str would
    # have silently compared a single character.
    raw_report_type = parsed.get_param("report-type")
    report_type = (raw_report_type if isinstance(raw_report_type, str) else "").lower()
    if content_type == "multipart/report" and report_type == "delivery-status":
        return True

    # AN EMPTY `Return-Path`, CHECKED EXPLICITLY. The first version reused `normalise_message_id`
    # here, which was wrong in a way that read as correct: that function strips angle brackets around
    # CONTENT, and `<>` has none, so it returned the literal "<>" and every bounce was missed. Two
    # headers are not the same shape just because both are usually bracketed.
    return_path = parsed.get("Return-Path")
    return return_path is not None and return_path.strip() in {"<>", ""}


def is_auto_reply(parsed: Message) -> bool:
    """Whether this is an out-of-office or similar.

    `Auto-Submitted` with any value other than `no` is RFC 3834's marker. The two `X-` headers
    predate it and are still what a great deal of software actually sends.
    """
    submitted = (parsed.get("Auto-Submitted") or "").strip().lower()
    if submitted and submitted != "no":
        return True
    return any(parsed.get(name) is not None for name in _AUTO_REPLY_HEADERS[1:])


async def ingest_raw_message(
    db: AsyncSession,
    *,
    raw: bytes,
    raw_storage_path: str | None,
    ses_message_id: str | None = None,
    receipt: dict[str, Any] | None = None,
) -> IngestResult:
    """Store one inbound message. Idempotent on ``ingest_key``. ``flush`` only.

    Returns ``created=False`` when the row already existed. The caller must treat that as SUCCESS —
    see the module docstring on why a non-2xx on a duplicate is worse than the duplicate.
    """
    parsed = email.message_from_bytes(raw)
    normalised_id = normalise_message_id(parsed.get("Message-ID"))
    ingest_key = compute_ingest_key(
        ses_message_id=ses_message_id, message_id=normalised_id, raw=raw
    )

    values: dict[str, Any] = {
        "ingest_key": ingest_key,
        "ses_message_id": ses_message_id,
        "message_id": normalised_id,
        "in_reply_to": normalise_message_id(parsed.get("In-Reply-To")),
        "references": [ref for ref in (parsed.get("References") or "").split() if ref.strip()],
        "from_address": next(iter(_addresses(parsed, "From")), None),
        "to_addresses": _addresses(parsed, "To") + _addresses(parsed, "Delivered-To"),
        "subject": parsed.get("Subject"),
        "received_at": _received_at(parsed),
        "raw_storage_path": raw_storage_path,
        "auth_verdicts": extract_receipt_verdicts(receipt),
        "routing_state": InboundRoutingState.PENDING,
        "is_dsn": is_delivery_status_notification(parsed),
        "is_auto_reply": is_auto_reply(parsed),
    }

    # ON CONFLICT DO NOTHING against the ingest-key index, so a redelivery is a no-op rather than an
    # IntegrityError the caller has to catch and interpret.
    #
    # ON `ingest_key` ALONE (LP-807). The conflict target used to include `company_id`, which is NULL
    # here and is written later by routing — so a redelivery of an already-routed message conflicted
    # with nothing, inserted a second row, and then collided on the way to the same company.
    statement = (
        pg_insert(InboundMessage)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["ingest_key"])
        .returning(InboundMessage.id)
    )
    inserted = (await db.execute(statement)).scalar_one_or_none()
    await db.flush()

    if inserted is not None:
        await _record_attachments(db, inbound_message_id=inserted, raw=raw)
        # METADATA ONLY. No subject, no body, no sender address — the standing rule, and this is the
        # first code in Phase 4 that handles a real borrower's message.
        logger.info("inbound_message_ingested", ingest_key_prefix=ingest_key[:12], bytes=len(raw))
        return IngestResult(message_id=str(inserted), created=True, ingest_key=ingest_key)

    # NOT SCOPED TO `company_id IS NULL`. It was, and that made the lookup answer None for exactly
    # the row it was looking for as soon as routing had claimed it — returning `message_id="None"`
    # to a caller that would treat the redelivery as handled.
    existing = (
        await db.execute(select(InboundMessage.id).where(InboundMessage.ingest_key == ingest_key))
    ).scalar_one_or_none()
    logger.info("inbound_message_duplicate", ingest_key_prefix=ingest_key[:12])
    return IngestResult(message_id=str(existing), created=False, ingest_key=ingest_key)


#: Where a raw inbound message lives when it did not come from SES's own bucket — the dev injector
#: (§H1) and the seed. One flat prefix keyed on the row's uuid: raw mail has no company and no loan
#: file at the moment it is stored, so it cannot use the tenant-prefixed document path.
INBOUND_RAW_PREFIX = "inbound-raw"


def raw_storage_path_for(message_id: str) -> str:
    """The key a locally-stored raw message is written to. Server-controlled, never sender-derived."""
    return f"{INBOUND_RAW_PREFIX}/{message_id}.eml"


async def process_raw_message(
    db: AsyncSession,
    *,
    raw: bytes,
    raw_storage_path: str | None,
    ses_message_id: str | None = None,
    receipt: dict[str, Any] | None = None,
    store_raw: bool = False,
) -> IngestResult:
    """The whole ingest chain: store, assess, route. ``flush`` only; the caller commits.

    THE CHAIN HAD NO CALLER. `apply_safety_to_message` (LP-804b) and `apply_routing` (LP-805) were
    built as services and nothing outside their own tests ever invoked them: `ingest_raw_message`
    wrote the row and returned. Every message in the system would therefore have sat at
    `routing_state=PENDING` with every attachment at `safety_state=PENDING` forever — never routed to
    a file, never assessable, never acceptable, because `accept_attachment` requires `SAFE`. The
    tests for both services passed throughout, because each called its own function directly.

    That is the shape the repo has learned to distrust: a green suite over a step that never runs.
    LP-807 is the ticket that noticed, because it is the first one that has to SHOW a processor what
    arrived.

    SAFETY BEFORE ROUTING, per §2's diagram. `decide_disposition` decides whether a message may skip
    a human, and one of its conditions is that the attachments passed every safety gate; running it
    against attachments still in `PENDING` would ask that question before anything had looked.

    ``store_raw`` writes the bytes through the storage backend and records the path. It is False for
    SES, whose bucket already holds the object and whose path is passed in; it is True for the dev
    injector and the seed, where nothing else has stored anything. Without it `raw_storage_path` is
    NULL, and both accept-into-file and the attachment preview refuse — they re-derive the bytes from
    the stored message rather than keeping a second copy, so no stored message means no bytes.

    ONLY ON A FIRST INSERT. A redelivery returns ``created=False`` and is left exactly as it was: a
    message a processor has already accepted from must not have its verdicts recomputed underneath
    them.
    """
    result = await ingest_raw_message(
        db,
        raw=raw,
        raw_storage_path=raw_storage_path,
        ses_message_id=ses_message_id,
        receipt=receipt,
    )
    if not result.created:
        return result

    message = await db.get(InboundMessage, UUID(result.message_id))
    if message is None:  # pragma: no cover - the row was just inserted in this transaction
        return result

    if store_raw:
        path = raw_storage_path_for(result.message_id)
        await get_storage_backend().save_at(storage_path=path, content=raw)
        message.raw_storage_path = path

    from app.services.attachment_safety import apply_safety_to_message
    from app.services.inbound_routing import apply_routing

    await apply_safety_to_message(db, inbound_message_id=message.id, raw=raw)
    await apply_routing(db, message=message)
    await db.flush()
    return result


async def _record_attachments(db: AsyncSession, *, inbound_message_id: Any, raw: bytes) -> int:
    """Inventory every file-like part (LP-804a). Returns how many rows were written.

    ONLY ON A FIRST INSERT. A redelivery reaches the duplicate branch and never gets here, so the
    attachment rows are written exactly once — which is what makes the per-message
    ``(inbound_message_id, sha256)`` uniqueness a belt rather than the only mechanism.

    NOTHING IS DECIDED HERE. Every row lands `PENDING`: not sniffed, not scanned, not safe. LP-804b
    is what looks at the bytes, and until it has, nothing downstream may read one of these as a
    document.
    """
    parsed = parse_message(raw)
    if parsed.depth_limit_reached:
        # Surfaced, not swallowed. A message whose parts were not fully enumerated must not look
        # like one that simply had nothing deeper — that is how a payload hides behind the cap.
        logger.warning("inbound_attachments_depth_limited", count=len(parsed.attachments))
    for attachment in parsed.attachments:
        db.add(
            InboundAttachment(
                inbound_message_id=inbound_message_id,
                filename_original=attachment.filename_original,
                filename_normalized=attachment.filename_normalized,
                declared_content_type=attachment.declared_content_type,
                size_bytes=attachment.size_bytes,
                sha256=attachment.sha256,
                nesting_depth=attachment.nesting_depth,
            )
        )
    await db.flush()
    # A COUNT AND A DEPTH, and nothing else. Not the filename — it is text a stranger wrote — and
    # not the content type, which would leak what a borrower sent.
    logger.info(
        "inbound_attachments_recorded",
        count=len(parsed.attachments),
        max_depth=max((a.nesting_depth for a in parsed.attachments), default=0),
    )
    return len(parsed.attachments)


__all__ = [
    "INBOUND_RAW_PREFIX",
    "IngestResult",
    "compute_ingest_key",
    "extract_receipt_verdicts",
    "ingest_raw_message",
    "is_auto_reply",
    "is_delivery_status_notification",
    "normalise_message_id",
    "process_raw_message",
    "raw_storage_path_for",
]
