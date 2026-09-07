"""LP-819 — a message that did not arrive, and everything that must stop because of it.

THREE FAILURES THE PLAN NAMES, all of which are silent:

* a typo'd borrower address bounces and nobody sees it;
* **LP-814 keeps counting "no reply > 5 days" against a dead mailbox and escalates forever**;
* `Communication.error_detail` — a column that has existed since LP-20 — never gets a writer.

The middle one is the reason the suppression has to reach the reminder clock rather than only the
send path. A hard bounce means the borrower NEVER RECEIVED THE REQUEST, so `requested_at` is
unwound: a request that bounced was never made.

The classification is RFC 3463's, quoted rather than recalled — 4.x.x is a "persistent transient
failure" where "sending in the future may be successful", 5.x.x is "not likely to be resolved by
resending". Getting that backwards either abandons a borrower over a full mailbox or hammers a dead
one forever.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.activity_log import ActivityLog, ActivityType
from app.models.communication import CommunicationStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.models.suppressed_address import SuppressedAddress, SuppressionReason
from app.services.bounce_handling import (
    BounceClass,
    classify_status,
    is_suppressed,
    parse_ses_bounce,
    record_delivery_failure,
    suppress_address,
)
from app.services.email_draft import add_needs_to_draft
from app.services.email_send import CannotSendError, send_draft
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _file_with_sent_request(db: AsyncSession, *, recipient: str = "gone@example.com"):
    from app.models import User, UserRole
    from app.services.loan_files import create_loan_file

    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"p-{uuid4().hex[:8]}@example.com",
        hashed_password="x",  # pragma: allowlist secret
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
    )
    db.add(user)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=user.id)
    sent = await send_draft(
        db,
        loan_file=loan_file,
        draft_id=result.draft.id,
        recipient=recipient,
        body="Please send these.",
        approver_user_id=user.id,
    )
    sent.external_message_id = "ses-msg-1"
    await db.flush()
    return company, loan_file, user.id, need, sent


# --------------------------------------------------------------------------------------------- #
# RFC 3463
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("5.1.1", BounceClass.PERMANENT),
        ("5.4.1", BounceClass.PERMANENT),
        ("4.2.2", BounceClass.TRANSIENT),
        ("4.4.7", BounceClass.TRANSIENT),
        ("2.0.0", BounceClass.UNKNOWN),
        (None, BounceClass.UNKNOWN),
        ("nonsense", BounceClass.UNKNOWN),
    ],
)
def test_the_class_subfield_decides(status: str | None, expected: BounceClass) -> None:
    """RFC 3463: 4.x.x is a PERSISTENT TRANSIENT failure — "sending in the future may be
    successful" — and 5.x.x is PERMANENT, "not likely to be resolved by resending". The class is the
    only part of the code that changes what we do."""
    assert classify_status(status) is expected


def test_the_status_can_come_from_the_diagnostic_text() -> None:
    """Some providers put the code only in the human-readable diagnostic."""
    assert classify_status(None, diagnostic="smtp; 550 5.1.1 user unknown") is BounceClass.PERMANENT


def test_an_unparseable_report_is_not_treated_as_permanent() -> None:
    """UNKNOWN IS NOT PERMANENT, and the direction matters. Suppressing on a report we cannot parse
    would abandon a borrower because a provider phrased something unexpectedly — on a decision that
    stops somebody being contacted about their mortgage, the conservative direction is to leave it
    for a person."""
    assert classify_status("delivery failed, sorry") is BounceClass.UNKNOWN


def test_digits_in_an_address_are_not_mistaken_for_a_status() -> None:
    """A diagnostic quotes the recipient back, and an address can contain digits and dots. The
    pattern is anchored on word boundaries and a leading 2, 4 or 5 for that reason."""
    assert classify_status(None, diagnostic="smtp; recipient a1.2.3b@example.com rejected") is (
        BounceClass.UNKNOWN
    )


def test_every_failed_recipient_is_parsed_not_just_the_first() -> None:
    """One SES event can carry several recipients with their own statuses. Taking only the first
    leaves the others un-suppressed — and they are exactly the ones a second send bounces off."""
    failures = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-1"},
            "bounce": {
                "bouncedRecipients": [
                    {"emailAddress": "One@Example.com", "status": "5.1.1"},
                    {"emailAddress": "two@example.com", "status": "4.2.2"},
                ]
            },
        }
    )

    assert len(failures) == 2
    assert failures[0].recipient == "one@example.com"  # normalised
    assert failures[0].bounce_class is BounceClass.PERMANENT
    assert failures[1].bounce_class is BounceClass.TRANSIENT


# --------------------------------------------------------------------------------------------- #
# The clock, which is the failure the plan names
# --------------------------------------------------------------------------------------------- #
async def test_a_hard_bounce_unwinds_the_request(db_session: AsyncSession) -> None:
    """THE ONE THAT MATTERS. LP-814 counts "no reply > 5 days" against `requested_at`. A hard bounce
    means the borrower never received the request, so leaving the stamp set escalates forever
    against a mailbox that does not exist — and every nudge bounces too."""
    _company, _loan_file, _actor, need, _sent = await _file_with_sent_request(db_session)
    assert need.requested_at is not None

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [{"emailAddress": "gone@example.com", "status": "5.1.1"}]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    assert need.requested_at is None
    assert need.status is NeedsItemStatus.PENDING


async def test_a_soft_bounce_does_not_unwind(db_session: AsyncSession) -> None:
    """The control, and the reason the class matters. A full mailbox will accept mail later; clearing
    the clock would make the system ask again immediately and forget it had ever asked."""
    _company, _loan_file, _actor, need, _sent = await _file_with_sent_request(db_session)

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [{"emailAddress": "gone@example.com", "status": "4.2.2"}]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    assert need.requested_at is not None
    assert need.status is NeedsItemStatus.REQUESTED


async def test_a_need_satisfied_another_way_is_not_dragged_backwards(
    db_session: AsyncSession,
) -> None:
    """Only needs still in REQUESTED are unwound. One satisfied by a document that arrived another
    way must not be reopened by a bounce on the email that asked for it."""
    _company, _loan_file, _actor, need, _sent = await _file_with_sent_request(db_session)
    need.status = NeedsItemStatus.RECEIVED
    await db_session.flush()

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [{"emailAddress": "gone@example.com", "status": "5.1.1"}]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    assert need.status is NeedsItemStatus.RECEIVED


# --------------------------------------------------------------------------------------------- #
# The column that has never had a writer
# --------------------------------------------------------------------------------------------- #
async def test_the_communication_records_the_failure(db_session: AsyncSession) -> None:
    """`error_detail` has existed since LP-20 with nothing writing it. This is the writer."""
    _company, _loan_file, _actor, _need, sent = await _file_with_sent_request(db_session)

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [
                    {
                        "emailAddress": "gone@example.com",
                        "status": "5.1.1",
                        "diagnosticCode": "smtp; 550 5.1.1 user unknown",
                    }
                ]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    assert sent.status is CommunicationStatus.FAILED
    assert sent.error_detail is not None
    assert "5.1.1" in sent.error_detail


async def test_an_unmatched_event_is_not_an_error(db_session: AsyncSession) -> None:
    """SES publishes events for everything sent through the configuration set. One we cannot match
    is not an error, and raising would fail a whole batch over a message that is not ours."""
    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "never-seen"},
            "bounce": {"bouncedRecipients": [{"emailAddress": "x@example.com", "status": "5.1.1"}]},
        }
    )[0]

    assert await record_delivery_failure(db_session, failure=failure) is None


async def test_the_failure_is_logged_without_the_address(db_session: AsyncSession) -> None:
    """The standing check. The activity detail carries the class and the code; the provider's
    diagnostic quotes the borrower's address back and never reaches it."""
    _company, loan_file, _actor, _need, _sent = await _file_with_sent_request(db_session)

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [
                    {
                        "emailAddress": "gone@example.com",
                        "status": "5.1.1",
                        "diagnosticCode": "smtp; 550 gone@example.com unknown",
                    }
                ]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    row = (
        await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == loan_file.id,
                ActivityLog.activity_type == ActivityType.COMMUNICATION_FAILED,
            )
        )
    ).scalar_one()
    blob = f"{row.summary} {row.detail}"
    assert "gone@example.com" not in blob
    assert row.detail["bounce_class"] == "permanent"


# --------------------------------------------------------------------------------------------- #
# Suppression, and its tenancy
# --------------------------------------------------------------------------------------------- #
async def test_a_hard_bounce_suppresses_the_address(db_session: AsyncSession) -> None:
    company, _loan_file, _actor, _need, _sent = await _file_with_sent_request(db_session)

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [{"emailAddress": "gone@example.com", "status": "5.1.1"}]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    assert await is_suppressed(db_session, company_id=company.id, address="gone@example.com")
    row = (await db_session.execute(select(SuppressedAddress))).scalar_one()
    assert row.reason is SuppressionReason.HARD_BOUNCE


async def test_a_soft_bounce_does_not_suppress(db_session: AsyncSession) -> None:
    """The control. Suppressing on a full mailbox abandons a borrower over a temporary condition."""
    company, _loan_file, _actor, _need, _sent = await _file_with_sent_request(db_session)

    failure = parse_ses_bounce(
        {
            "mail": {"messageId": "ses-msg-1"},
            "bounce": {
                "bouncedRecipients": [{"emailAddress": "gone@example.com", "status": "4.2.2"}]
            },
        }
    )[0]
    await record_delivery_failure(db_session, failure=failure)

    assert not await is_suppressed(db_session, company_id=company.id, address="gone@example.com")


async def test_suppression_is_scoped_to_one_company(db_session: AsyncSession) -> None:
    """The tenancy shape, and the same one LP-811a's rate limit was corrected for. One company's
    bounce must not block another's send — a borrower shopping two brokers is ordinary — and a
    shared table would tell company B that somebody else has been emailing their borrower."""
    theirs, _lf, _actor, _need, _sent = await _file_with_sent_request(db_session)
    mine = Company(name="Mine", slug=f"mine-{uuid4().hex[:8]}")
    db_session.add(mine)
    await db_session.flush()

    await suppress_address(
        db_session,
        company_id=theirs.id,
        address="gone@example.com",
        reason=SuppressionReason.HARD_BOUNCE,
    )

    assert await is_suppressed(db_session, company_id=theirs.id, address="gone@example.com")
    assert not await is_suppressed(db_session, company_id=mine.id, address="gone@example.com")


async def test_suppression_is_case_insensitive(db_session: AsyncSession) -> None:
    """The local part is case-sensitive per RFC 5321 and case-insensitive at every provider anyone
    uses. Matching case-sensitively lets one capitalisation typo walk past a suppression."""
    company, _lf, _actor, _need, _sent = await _file_with_sent_request(db_session)
    await suppress_address(
        db_session,
        company_id=company.id,
        address="Gone@Example.COM",
        reason=SuppressionReason.HARD_BOUNCE,
    )

    assert await is_suppressed(db_session, company_id=company.id, address="gone@example.com")


async def test_suppressing_twice_is_one_row(db_session: AsyncSession) -> None:
    company, _lf, _actor, _need, _sent = await _file_with_sent_request(db_session)
    for _ in range(2):
        await suppress_address(
            db_session,
            company_id=company.id,
            address="gone@example.com",
            reason=SuppressionReason.HARD_BOUNCE,
        )

    count = await db_session.scalar(select(func.count()).select_from(SuppressedAddress))
    assert count == 1


# --------------------------------------------------------------------------------------------- #
# The send path
# --------------------------------------------------------------------------------------------- #
async def test_sending_to_a_suppressed_address_is_refused(db_session: AsyncSession) -> None:
    """And the refusal says WHY. "Wait five minutes" would be actively misleading for an address that
    will never work."""
    company, loan_file, actor, _need, _sent = await _file_with_sent_request(db_session)
    await suppress_address(
        db_session,
        company_id=company.id,
        address="gone@example.com",
        reason=SuppressionReason.HARD_BOUNCE,
    )

    second_need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add(second_need)
    await db_session.flush()
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second_need], actor_user_id=actor
    )

    with pytest.raises(CannotSendError, match="suppressed"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=result.draft.id,
            recipient="gone@example.com",
            body="Please send these.",
            approver_user_id=actor,
        )


async def test_an_unsuppressed_address_still_sends(db_session: AsyncSession) -> None:
    """The control. A suppression check that refused everything would satisfy the test above and
    would stop the product working."""
    _company, loan_file, actor, _need, _sent = await _file_with_sent_request(db_session)
    second_need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add(second_need)
    await db_session.flush()
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second_need], actor_user_id=actor
    )

    sent = await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=result.draft.id,
        recipient="fine@example.com",
        body="Please send these.",
        approver_user_id=actor,
    )
    assert sent.status is CommunicationStatus.SENT
