"""LP-811a — the send that finally starts the clock.

`request_needs_item` has existed since LP-19 with ZERO callers, so `requested_at` is NULL on every
needs item that has ever existed. LP-814's reminders are a Celery beat over that column: until
something writes it, every reminder rule is a query over an empty set — green, silent, and unable to
fire. The first test here is the one that matters.

The rest are about what must be true at the moment of sending: the routing tag is an identifier and
not a capability, the rate limit counts across files rather than within one, and a truncated
`mailto:` never gets offered.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.activity_log import ActivityLog, ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.email_draft import add_needs_to_draft
from app.services.email_send import (
    MAILTO_MAX_CHARS,
    CannotSendError,
    build_outbound,
    footer_tag,
    loan_reference_in,
    send_draft,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _setup(db: AsyncSession, *, titles: tuple[str, ...] = ("Bank statements",)):
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
    needs = []
    for title in titles:
        need = NeedsItem(
            loan_file_id=loan_file.id,
            title=title,
            needs_type="bank_statement",
            origin=NeedsItemOrigin.FINDING,
        )
        db.add(need)
        needs.append(need)
    await db.flush()
    result = await add_needs_to_draft(db, loan_file=loan_file, needs=needs, actor_user_id=user.id)
    return loan_file, user.id, needs, result.draft


# --------------------------------------------------------------------------------------------- #
# The clock
# --------------------------------------------------------------------------------------------- #
async def test_sending_stamps_requested_at_on_every_need(db_session: AsyncSession) -> None:
    """THE reason this ticket exists. Before it, `requested_at` was NULL on every row ever written,
    so LP-814's reminder rules were queries over an empty set — they could not fail and could not
    fire, which look identical from outside."""
    loan_file, actor, needs, draft = await _setup(
        db_session, titles=("Bank statements", "Pay stubs")
    )
    assert all(need.requested_at is None for need in needs)

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="Please send these when you can.",
        approver_user_id=actor,
    )

    for need in needs:
        assert need.requested_at is not None
        assert need.status is NeedsItemStatus.REQUESTED


async def test_a_need_not_in_the_draft_keeps_its_clock_unstarted(db_session: AsyncSession) -> None:
    """The control. Stamping every need on the file would also pass the test above, and would start
    reminder clocks for documents nobody has asked the borrower for."""
    loan_file, actor, _needs, draft = await _setup(db_session)
    other = NeedsItem(
        loan_file_id=loan_file.id,
        title="Appraisal",
        needs_type="appraisal",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add(other)
    await db_session.flush()

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="Please send these.",
        approver_user_id=actor,
    )

    assert other.requested_at is None
    assert other.status is NeedsItemStatus.PENDING


# --------------------------------------------------------------------------------------------- #
# The routing tag
# --------------------------------------------------------------------------------------------- #
def test_the_footer_tag_is_the_display_id_and_never_the_token() -> None:
    """ADR-048 draws the line this depends on: the display id is an IDENTIFIER whose predictability
    is low-risk; the inbox token is a CAPABILITY whose possession lets anyone post documents into the
    file. A footer is quoted into every reply and forwarded onward, so putting the token there would
    hand it to everyone the borrower ever forwards the message to."""

    class _File:
        display_id = "LF-6T3N"
        inbox_token = "s3cr3t-token-value"  # pragma: allowlist secret

        def get_inbox_address(self) -> str:
            return f"lf-{self.inbox_token}@inbox.example.com"

    loan_file = _File()
    tag = footer_tag(loan_file)  # type: ignore[arg-type]
    assert tag == "[LF-6T3N]"
    assert loan_file.inbox_token not in tag


def test_the_footer_tag_round_trips(db_session: AsyncSession) -> None:
    """LP-805's fallback match. `Reply-To` routes a well-behaved reply; this is what still works when
    a client strips or rewrites the header, which several do."""

    class _File:
        display_id = "LF-6T3N"

        def get_inbox_address(self) -> str:
            return "lf-abc@inbox.example.com"

    message = build_outbound(_File(), subject="Documents", body="Please send these.")  # type: ignore[arg-type]
    assert loan_reference_in(message.body) == "LF-6T3N"


def test_a_message_with_no_tag_resolves_to_nothing() -> None:
    """The control — a matcher that returned a file for any text would route stranger's mail into
    somebody's loan."""
    assert loan_reference_in("An ordinary reply with no tag in it.") is None


async def test_the_reply_to_is_the_files_inbox_address(db_session: AsyncSession) -> None:
    loan_file, _actor, _needs, _draft = await _setup(db_session)
    message = build_outbound(loan_file, subject="Documents", body="Please send these.")
    assert message.reply_to == loan_file.get_inbox_address()
    assert message.suggested_bcc == loan_file.get_inbox_address()


# --------------------------------------------------------------------------------------------- #
# The mailto threshold
# --------------------------------------------------------------------------------------------- #
async def test_a_long_message_does_not_offer_a_mail_client_link(db_session: AsyncSession) -> None:
    """`mailto:` does not FAIL when it is too long — it opens a compose window containing half an
    email, which a processor may not notice before sending. So the link is withheld rather than
    offered and hoped for."""
    loan_file, _actor, _needs, _draft = await _setup(db_session)
    long_body = "x" * (MAILTO_MAX_CHARS + 1)
    assert build_outbound(loan_file, subject="D", body=long_body).mailto_available is False


async def test_a_short_message_does_offer_one(db_session: AsyncSession) -> None:
    """The control: a threshold that refused everything would satisfy the test above and would leave
    the feature permanently unavailable, which looks exactly like it not being built."""
    loan_file, _actor, _needs, _draft = await _setup(db_session)
    assert build_outbound(loan_file, subject="D", body="Short.").mailto_available is True


# --------------------------------------------------------------------------------------------- #
# The rate limit
# --------------------------------------------------------------------------------------------- #
async def test_the_same_address_cannot_be_mailed_twice_in_five_minutes(
    db_session: AsyncSession,
) -> None:
    """Across two files of ONE company — which is what "across files, not within one" means.

    This test used to call `_setup` twice, and `_setup` builds a fresh COMPANY each time. So it was
    asserting that one tenant's send blocks another's, as though that were the feature. It passed
    for a reason unrelated to what it claimed: the limit was unscoped, and the test had accidentally
    pinned the cross-tenant leak in place. Two files, one company, is the case the limit is for.
    """
    loan_file, actor, _needs, draft = await _setup(db_session)
    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="First.",
        approver_user_id=actor,
    )
    second_file, second_need = await _second_file_in(db_session, loan_file.company_id)
    second = await add_needs_to_draft(
        db_session, loan_file=second_file, needs=[second_need], actor_user_id=actor
    )

    with pytest.raises(CannotSendError, match="minutes ago"):
        await send_draft(
            db_session,
            loan_file=second_file,
            draft_id=second.draft.id,
            recipient="borrower@example.com",
            body="Second.",
            approver_user_id=actor,
        )


async def test_the_limit_counts_across_files_not_within_one(db_session: AsyncSession) -> None:
    """The direction that matters, and the reason the test above uses a SECOND file. A borrower with
    two loan files in progress is one mailbox; a per-file limit would let them be mailed twice in a
    minute while every individual limit read as respected."""
    loan_file, actor, _needs, draft = await _setup(db_session)
    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="First.",
        approver_user_id=actor,
    )
    other_file, other_actor, _n, other_draft = await _setup(db_session)

    # A different address on a different file is unaffected — the limit is per ADDRESS.
    sent = await send_draft(
        db_session,
        loan_file=other_file,
        draft_id=other_draft.id,
        recipient="someone-else@example.com",
        body="Fine.",
        approver_user_id=other_actor,
    )
    assert sent.status is CommunicationStatus.SENT


async def test_the_daily_cap_refuses_a_fourth(db_session: AsyncSession) -> None:
    """Three per day. Seeded past the five-minute window so it is the DAILY rule being tested and not
    the one above wearing its clothes."""
    loan_file, actor, _needs, draft = await _setup(db_session)
    for hours in (6, 4, 2):
        db_session.add(
            Communication(
                loan_file_id=loan_file.id,
                direction=CommunicationDirection.OUTBOUND,
                status=CommunicationStatus.SENT,
                recipient="borrower@example.com",
                sent_at=utcnow() - timedelta(hours=hours),
            )
        )
    await db_session.flush()

    with pytest.raises(CannotSendError, match="3 times today"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=draft.id,
            recipient="borrower@example.com",
            body="Fourth.",
            approver_user_id=actor,
        )


# --------------------------------------------------------------------------------------------- #
# What sending records, and what it refuses
# --------------------------------------------------------------------------------------------- #
async def test_the_sent_body_is_what_the_processor_typed_plus_the_tag(
    db_session: AsyncSession,
) -> None:
    """The record of an outbound message must be what went out, not what was composed. LP-821 builds
    the three-way evidence record; here the stored body is the sent one."""
    loan_file, actor, _needs, draft = await _setup(db_session)

    sent = await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="I rewrote this entirely.",
        approver_user_id=actor,
    )

    assert "I rewrote this entirely." in sent.body
    assert footer_tag(loan_file) in sent.body
    assert sent.sent_at is not None
    assert sent.status is CommunicationStatus.SENT


async def test_the_send_is_logged_without_the_content(db_session: AsyncSession) -> None:
    """The standing reviewer check, asserted rather than asserted-about. The detail carries ids and
    the template's identity; never the subject, the body, or the recipient's address."""
    from sqlalchemy import select

    loan_file, actor, _needs, draft = await _setup(db_session)
    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="A distinctive sentence nobody should log.",
        approver_user_id=actor,
    )

    rows = (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    blob = f"{rows[0].summary} {rows[0].detail}"
    assert "distinctive sentence" not in blob
    assert "borrower@example.com" not in blob
    assert rows[0].actor_user_id == actor


async def test_a_draft_cannot_be_sent_twice(db_session: AsyncSession) -> None:
    """Idempotence at the only place it matters — a second click must not re-ask the borrower, and
    must not restart the clock on needs already requested."""
    loan_file, actor, _needs, draft = await _setup(db_session)
    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="borrower@example.com",
        body="Once.",
        approver_user_id=actor,
    )

    with pytest.raises(CannotSendError, match="already sent"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=draft.id,
            recipient="borrower@example.com",
            body="Twice.",
            approver_user_id=actor,
        )


async def test_a_draft_from_another_file_is_refused(db_session: AsyncSession) -> None:
    """The tenant-shaped mistake this endpoint could make. The draft id is a path parameter, so
    nothing but this check stops one file's draft being sent under another file's address."""
    _first, actor, _needs, draft = await _setup(db_session)
    other_file, _a, _n, _d = await _setup(db_session)

    with pytest.raises(CannotSendError, match="no such draft"):
        await send_draft(
            db_session,
            loan_file=other_file,
            draft_id=draft.id,
            recipient="borrower@example.com",
            body="Wrong file.",
            approver_user_id=actor,
        )


async def test_an_empty_body_is_refused(db_session: AsyncSession) -> None:
    loan_file, actor, _needs, draft = await _setup(db_session)
    with pytest.raises(CannotSendError, match="empty"):
        await send_draft(
            db_session,
            loan_file=loan_file,
            draft_id=draft.id,
            recipient="borrower@example.com",
            body="   ",
            approver_user_id=actor,
        )


# --------------------------------------------------------------------------------------------- #
# The rate limit is scoped to a company (review finding)
# --------------------------------------------------------------------------------------------- #
async def _second_file_in(db: AsyncSession, company_id, *, title: str = "Pay stubs"):
    """Another file for the SAME company, with its own draft."""
    from app.services.loan_files import create_loan_file

    loan_file = await create_loan_file(
        db, company_id=company_id, loan_program=LoanProgram.CONVENTIONAL
    )
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title=title,
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    return loan_file, need


async def test_one_companys_send_does_not_block_another_company(db_session: AsyncSession) -> None:
    """Two processing companies can hold a file for the same person — a borrower shopping two
    brokers is the ordinary case, not a contrivance.

    Counted system-wide, company A's send refused company B's with "was emailed less than 5 minutes
    ago", which both stalls B's mail and tells B that somebody else has been in touch with their
    borrower. Measured that way before the query was scoped.
    """
    borrower = "shared.borrower@example.com"
    file_a, actor_a, _, draft_a = await _setup(db_session)
    file_b, actor_b, _, draft_b = await _setup(db_session)
    assert file_a.company_id != file_b.company_id  # the property under test

    await send_draft(
        db_session,
        loan_file=file_a,
        draft_id=draft_a.id,
        recipient=borrower,
        body="Hello, please send documents.",
        approver_user_id=actor_a,
    )
    sent_b = await send_draft(
        db_session,
        loan_file=file_b,
        draft_id=draft_b.id,
        recipient=borrower,
        body="Hello, please send documents.",
        approver_user_id=actor_b,
    )

    assert sent_b.status is CommunicationStatus.SENT


async def test_the_window_still_applies_across_one_companys_files(
    db_session: AsyncSession,
) -> None:
    """The positive control, and the one that matters: scoping the query must not disable the limit.

    A fix that simply stopped counting would satisfy the test above while leaving a borrower
    mailable every second, which is the failure the limit exists to prevent. The two files here
    belong to ONE company, which is the case the limit is for.
    """
    borrower = "same.borrower@example.com"
    file_one, actor, _, draft_one = await _setup(db_session)
    file_two, need_two = await _second_file_in(db_session, file_one.company_id)
    result = await add_needs_to_draft(
        db_session, loan_file=file_two, needs=[need_two], actor_user_id=actor
    )

    await send_draft(
        db_session,
        loan_file=file_one,
        draft_id=draft_one.id,
        recipient=borrower,
        body="Hello, please send documents.",
        approver_user_id=actor,
    )
    with pytest.raises(CannotSendError, match="less than"):
        await send_draft(
            db_session,
            loan_file=file_two,
            draft_id=result.draft.id,
            recipient=borrower,
            body="Hello, please send documents.",
            approver_user_id=actor,
        )
