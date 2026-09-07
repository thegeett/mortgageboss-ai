"""LP-803 — ingest, and the two things the ticket's acceptance criterion turns on.

    "the same message delivered twice produces exactly one row, and a message with
     dmarcVerdict: GRAY is stored as GRAY rather than coerced to PASS"

Both fail SILENTLY if wrong. A second row looks like a second message, which is what a redelivery
IS from the outside. A GRAY coerced to PASS looks like a message that authenticated — and the whole
point of storing the verdict is that a later routing rule reads it.

The third thing tested here is not in the criterion and matters as much: a bounce that is not
recognised as a bounce files itself as a borrower document. It is an email, it is addressed to the
file's inbox, and it usually carries the original message as an attachment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.services.inbound_ingest import (
    compute_ingest_key,
    extract_receipt_verdicts,
    ingest_raw_message,
    is_auto_reply,
    is_delivery_status_notification,
    normalise_message_id,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "eml"


def _eml(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


# --------------------------------------------------------------------------------------------- #
# The dedup contract
# --------------------------------------------------------------------------------------------- #
async def test_the_same_message_twice_produces_one_row(db_session: AsyncSession) -> None:
    """The ticket's first acceptance criterion. SQS is at-least-once BY DESIGN, so this is the
    ordinary case rather than an edge one."""
    raw = _eml("plain_reply.eml")

    first = await ingest_raw_message(
        db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-1"
    )
    second = await ingest_raw_message(
        db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-1"
    )

    assert first.created is True
    assert second.created is False
    assert second.message_id == first.message_id
    count = await db_session.scalar(select(func.count()).select_from(InboundMessage))
    assert count == 1


async def test_a_duplicate_is_reported_as_success_not_as_an_error(
    db_session: AsyncSession,
) -> None:
    """`created=False` and no exception. A non-2xx on a duplicate drives a provider into its retry
    schedule forever — one message becomes sustained load, with nothing in any log that looks like
    the cause."""
    raw = _eml("plain_reply.eml")
    await ingest_raw_message(db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-1")

    result = await ingest_raw_message(
        db_session, raw=raw, raw_storage_path=None, ses_message_id="ses-1"
    )

    assert result.created is False
    assert result.message_id is not None


async def test_two_different_messages_both_land(db_session: AsyncSession) -> None:
    """The control. A dedup that collapsed everything would satisfy the test above and would lose
    every message after the first — and the symptom is silence, not an error."""
    await ingest_raw_message(
        db_session, raw=_eml("plain_reply.eml"), raw_storage_path=None, ses_message_id="ses-1"
    )
    await ingest_raw_message(
        db_session, raw=_eml("out_of_office.eml"), raw_storage_path=None, ses_message_id="ses-2"
    )

    count = await db_session.scalar(select(func.count()).select_from(InboundMessage))
    assert count == 2


async def test_dedup_works_with_no_ses_id_and_no_message_id(db_session: AsyncSession) -> None:
    """The `sha256(raw)` fallback, and the case NULLS NOT DISTINCT exists for. Both rows have
    company_id NULL — which is the state every message starts in — and in a default unique index two
    NULLs are never equal, so the duplicate would have been admitted."""
    raw = _eml("no_message_id.eml")

    await ingest_raw_message(db_session, raw=raw, raw_storage_path=None)
    second = await ingest_raw_message(db_session, raw=raw, raw_storage_path=None)

    assert second.created is False
    count = await db_session.scalar(select(func.count()).select_from(InboundMessage))
    assert count == 1


def test_the_ingest_key_prefers_the_source_a_sender_cannot_choose() -> None:
    """Ordered by how hard each is to forge. `Message-ID` is written by the sender; the SES id is
    assigned by SES. Preferring the header over the hash is still right, because a legitimately
    redelivered message keeps its header and may not keep its bytes — a relay can add headers."""
    raw = b"whatever"
    assert compute_ingest_key(ses_message_id="ses-1", message_id="<m@x>", raw=raw) == "ses-1"
    assert compute_ingest_key(ses_message_id=None, message_id="<m@x>", raw=raw) == "m@x"
    assert len(compute_ingest_key(ses_message_id=None, message_id=None, raw=raw)) == 64


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("<abc@example.com>", "abc@example.com"), ("  <abc@x>  ", "abc@x"), (None, None), ("", None)],
)
def test_message_ids_are_normalised(raw: str | None, expected: str | None) -> None:
    """The same id arrives spelled differently — with brackets, without, with folded whitespace — and
    a key that treats those as different ids does not deduplicate at all."""
    assert normalise_message_id(raw) == expected


# --------------------------------------------------------------------------------------------- #
# The verdicts
# --------------------------------------------------------------------------------------------- #
async def test_a_gray_dmarc_verdict_is_stored_as_gray(db_session: AsyncSession) -> None:
    """The ticket's second acceptance criterion. GRAY means SES could not decide; a routing rule
    that reads it as PASS treats "we do not know" as "authenticated"."""
    receipt = {
        "dmarcVerdict": {"status": "GRAY"},
        "spfVerdict": {"status": "PASS"},
        "dkimVerdict": {"status": "FAIL"},
    }

    await ingest_raw_message(
        db_session,
        raw=_eml("plain_reply.eml"),
        raw_storage_path=None,
        ses_message_id="ses-1",
        receipt=receipt,
    )

    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.auth_verdicts["dmarcVerdict"] == "GRAY"
    assert stored.auth_verdicts["dkimVerdict"] == "FAIL"
    assert stored.auth_verdicts["spfVerdict"] == "PASS"


def test_an_unrecognised_verdict_survives() -> None:
    """Copied verbatim rather than mapped onto a known set. A verdict this code has never seen must
    reach a person to be looked at, not be dropped for being unrecognised."""
    verdicts = extract_receipt_verdicts({"dmarcVerdict": {"status": "SOMETHING_NEW"}})
    assert verdicts["dmarcVerdict"] == "SOMETHING_NEW"


def test_verdicts_come_only_from_the_receipt() -> None:
    """The control that matters. `extract_receipt_verdicts` is given the RECEIPT, never the parsed
    message — an `Authentication-Results` header is written by whoever sent the mail and can assert
    its own DKIM pass. With no receipt there are no verdicts, not defaults."""
    assert extract_receipt_verdicts(None) == {}
    assert extract_receipt_verdicts({}) == {}


async def test_a_message_with_no_receipt_stores_no_verdicts(db_session: AsyncSession) -> None:
    """Empty, not absent-and-therefore-fine. A later rule asking "did this pass DMARC?" must find
    nothing rather than find a default that reads as a pass."""
    await ingest_raw_message(
        db_session, raw=_eml("plain_reply.eml"), raw_storage_path=None, ses_message_id="ses-1"
    )
    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.auth_verdicts == {}


# --------------------------------------------------------------------------------------------- #
# What kind of message this is
# --------------------------------------------------------------------------------------------- #
async def test_a_bounce_is_recognised(db_session: AsyncSession) -> None:
    """A bounce that is not flagged files itself as a borrower document: it is an email, addressed
    to the file's inbox, usually carrying the original message as an attachment."""
    await ingest_raw_message(
        db_session, raw=_eml("bounce_dsn.eml"), raw_storage_path=None, ses_message_id="ses-dsn"
    )
    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.is_dsn is True


async def test_an_out_of_office_is_recognised(db_session: AsyncSession) -> None:
    await ingest_raw_message(
        db_session, raw=_eml("out_of_office.eml"), raw_storage_path=None, ses_message_id="ses-ooo"
    )
    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.is_auto_reply is True
    assert stored.is_dsn is False


async def test_an_ordinary_reply_is_neither(db_session: AsyncSession) -> None:
    """The control for both flags. Detectors that fired on everything would satisfy the two tests
    above and would send every borrower reply to the wrong path."""
    await ingest_raw_message(
        db_session, raw=_eml("plain_reply.eml"), raw_storage_path=None, ses_message_id="ses-1"
    )
    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.is_dsn is False
    assert stored.is_auto_reply is False
    assert stored.routing_state is InboundRoutingState.PENDING


def test_an_empty_return_path_alone_marks_a_bounce() -> None:
    """RFC 5321 requires a notification to carry `Return-Path: <>` so it cannot itself bounce. Real
    bounces in the wild carry that, or the multipart/report shape, or both — so either is enough."""
    import email

    parsed = email.message_from_bytes(
        b"From: MAILER-DAEMON@x\r\nReturn-Path: <>\r\nSubject: failed\r\n\r\nnope\r\n"
    )
    assert is_delivery_status_notification(parsed) is True


def test_a_normal_return_path_does_not() -> None:
    """The control. `Return-Path` is present on almost every delivered message, and treating its
    presence rather than its EMPTINESS as the signal would flag all of them."""
    import email

    parsed = email.message_from_bytes(
        b"From: a@x\r\nReturn-Path: <a@x>\r\nSubject: hello\r\n\r\nhi\r\n"
    )
    assert is_delivery_status_notification(parsed) is False
    assert is_auto_reply(parsed) is False


# --------------------------------------------------------------------------------------------- #
# What is stored, and what is not
# --------------------------------------------------------------------------------------------- #
async def test_the_row_starts_owned_by_nobody(db_session: AsyncSession) -> None:
    """Ingest does not resolve. Which loan file — and therefore which company — is LP-805's, in the
    one place allowed to derive a company id from a resolved loan file."""
    await ingest_raw_message(
        db_session, raw=_eml("plain_reply.eml"), raw_storage_path=None, ses_message_id="ses-1"
    )
    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.company_id is None
    assert stored.loan_file_id is None
    assert stored.routing_signal is None


async def test_the_envelope_is_recorded(db_session: AsyncSession) -> None:
    await ingest_raw_message(
        db_session,
        raw=_eml("plain_reply.eml"),
        raw_storage_path="s3://bucket/inbound/abc",
        ses_message_id="ses-1",
    )
    stored = (await db_session.execute(select(InboundMessage))).scalar_one()
    assert stored.from_address == "akash@example.com"
    assert "lf-abc123@inbox.example.com" in stored.to_addresses
    assert stored.raw_storage_path == "s3://bucket/inbound/abc"
    assert stored.received_at is not None
