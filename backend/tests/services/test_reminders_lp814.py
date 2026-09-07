"""LP-814 — the three reminder rules, and the clock each one reads.

THE FIRST TWO TESTS ARE THE TICKET. §1.4: *"A reminder keyed on `created_at` would nag about
documents nobody has asked for yet."* And LP-819 unwinds `requested_at` on a hard bounce, so a
bounced request goes back to `PENDING` with no stamp — deliberately, because the borrower never
received it.

Those two facts make one trap with two mouths. A rule reading `created_at` nags about a need nobody
asked for; a rule *falling back* to `created_at` when `requested_at` is NULL — which looks like
tolerance — nags hardest about exactly the requests that bounced, against a mailbox that does not
exist, and every nudge bounces too.

So both are asserted, and each has the positive control beside it, because a rule that never fires
is green against a "does not nag" test and useless.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.models import Company, LoanProgram
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.loan_file import LoanFileStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.models.reminder_snooze import ReminderKind
from app.services.activity_log import log_activity
from app.services.reminders import build_suggestions, snooze, unsnooze
from sqlalchemy.ext.asyncio import AsyncSession

LONG_AGO = timedelta(days=30)


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    # KEEPS RULE 3 OUT OF THE WAY. A file created just now is not untouched, but these tests age
    # things by hand and a bare file would start firing rule 3 as soon as anything moved back a
    # week. One activity now is the honest "somebody just did something here".
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.FILE_CREATED,
        summary="created",
    )
    return company, loan_file


async def _need(
    db: AsyncSession,
    loan_file,
    *,
    status: NeedsItemStatus,
    requested_days_ago: int | None,
    title: str = "Bank statements",
) -> NeedsItem:
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title=title,
        needs_type="bank_statement",
        origin=NeedsItemOrigin.TEMPLATE,
        status=status,
        requested_at=(
            None if requested_days_ago is None else utcnow() - timedelta(days=requested_days_ago)
        ),
    )
    db.add(need)
    await db.flush()
    # AGED AFTER INSERT, so `created_at` is genuinely old too — which is what makes the
    # "does not fall back to created_at" tests mean something.
    need.created_at = utcnow() - LONG_AGO
    await db.flush()
    return need


def _kinds(suggestions) -> set[ReminderKind]:
    return {s.kind for s in suggestions}


# --------------------------------------------------------------------------------------------- #
# Rule 1, and the clock it must read
# --------------------------------------------------------------------------------------------- #
async def test_a_need_requested_four_days_ago_is_suggested(db_session: AsyncSession) -> None:
    """THE POSITIVE CONTROL, first. Every "does not nag" test below is worthless against an engine
    that never fires."""
    company, loan_file = await _company_and_file(db_session, slug="pending")
    await _need(db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=4)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING in _kinds(suggestions)


async def test_a_need_nobody_has_asked_for_is_not_suggested(db_session: AsyncSession) -> None:
    """§1.4's own sentence: a reminder keyed on `created_at` nags about documents nobody has asked
    for. The need here was created a month ago and never requested."""
    company, loan_file = await _company_and_file(db_session, slug="unasked")
    await _need(db_session, loan_file, status=NeedsItemStatus.PENDING, requested_days_ago=None)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(suggestions)


async def test_a_bounced_request_produces_no_clock(db_session: AsyncSession) -> None:
    """THE TRAP'S OTHER MOUTH. LP-819 unwinds `requested_at` and puts the need back to PENDING,
    because the borrower never received the request.

    A rule that fell back to `created_at` when the stamp was NULL — which looks like tolerance —
    would nag hardest about exactly these, against a mailbox that does not exist, and every nudge
    would bounce too. The need is aged a month so the fallback would definitely fire.
    """
    company, loan_file = await _company_and_file(db_session, slug="bounced")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )
    # Exactly what `_unwind_requests` does.
    need.status = NeedsItemStatus.PENDING
    need.requested_at = None
    await db_session.flush()

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(suggestions)


async def test_a_need_requested_yesterday_is_not_yet_suggested(
    db_session: AsyncSession,
) -> None:
    """THE THRESHOLD IS REAL. Without this, a rule with no time comparison passes the first test."""
    company, loan_file = await _company_and_file(db_session, slug="fresh")
    await _need(db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=1)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(suggestions)


async def test_the_stamp_decides_and_not_the_creation_date(db_session: AsyncSession) -> None:
    """THE TEST THAT ACTUALLY PINS THE CLOCK, and it was missing.

    The two tests above pass on the STATUS filter alone: an unasked need and a bounced one are both
    back at `PENDING`, so a rule reading `created_at` would exclude them anyway and both tests stay
    green. Measured — swapping `requested_at` for `created_at` in the query failed only one case,
    and neither of the two named after the trap.

    This is the case only the clock can decide: `REQUESTED`, created a month ago, requested
    yesterday. A rule reading creation nags; a rule reading the stamp waits.
    """
    company, loan_file = await _company_and_file(db_session, slug="stamp")
    await _need(db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=1)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(suggestions)


async def test_a_requested_need_with_no_stamp_is_not_suggested(
    db_session: AsyncSession,
) -> None:
    """DEFENSIVE, and honest about what does the work. `request_needs_item` sets the status and the
    stamp together and `_unwind_requests` clears them together, so this combination should not
    occur — nothing enforces it.

    It passes with or without the explicit `IS NOT NULL` clause, because SQL's three-valued logic
    already makes `NULL < timestamp` unknown. Measured, so this is not claimed as a test of that
    clause: what it pins is the OUTCOME for a row that drifted into the state, which is the thing a
    future change to the query could break.
    """
    company, loan_file = await _company_and_file(db_session, slug="nostamp")
    await _need(db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=None)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(suggestions)


async def test_a_need_satisfied_another_way_is_not_suggested(db_session: AsyncSession) -> None:
    """It keeps its `requested_at` and is not waiting for anything. A rule reading only the stamp
    would nag about a document already on the file."""
    company, loan_file = await _company_and_file(db_session, slug="satisfied")
    await _need(db_session, loan_file, status=NeedsItemStatus.RECEIVED, requested_days_ago=10)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(suggestions)


# --------------------------------------------------------------------------------------------- #
# Rule 2
# --------------------------------------------------------------------------------------------- #
async def _sent(db: AsyncSession, loan_file, *, days_ago: int) -> Communication:
    row = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        recipient="jane@borrower.example",
        sent_at=utcnow() - timedelta(days=days_ago),
    )
    db.add(row)
    await db.flush()
    return row


async def _received(db: AsyncSession, loan_file, *, days_ago: int) -> Communication:
    row = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
    )
    db.add(row)
    await db.flush()
    row.created_at = utcnow() - timedelta(days=days_ago)
    await db.flush()
    return row


async def test_a_message_unanswered_for_six_days_is_suggested(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="noreply")
    await _sent(db_session, loan_file, days_ago=6)

    assert ReminderKind.NO_REPLY in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_a_reply_after_the_send_clears_it(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="answered")
    await _sent(db_session, loan_file, days_ago=6)
    await _received(db_session, loan_file, days_ago=2)

    assert ReminderKind.NO_REPLY not in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_a_reply_BEFORE_the_send_does_not_clear_it(db_session: AsyncSession) -> None:
    """ "NOTHING SINCE" MEANS NOTHING AFTER THE SEND, not "no inbound at all". A borrower who replied
    last month and has gone quiet since Tuesday's request is exactly what this rule is for, and a
    query asking whether the file ever received anything would miss it."""
    company, loan_file = await _company_and_file(db_session, slug="stale-reply")
    await _received(db_session, loan_file, days_ago=20)
    await _sent(db_session, loan_file, days_ago=6)

    assert ReminderKind.NO_REPLY in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_three_unanswered_sends_are_one_suggestion(db_session: AsyncSession) -> None:
    """A processor who sent three requests and heard nothing has ONE problem. Three cards for it is a
    list they stop reading."""
    company, loan_file = await _company_and_file(db_session, slug="three")
    for days in (6, 10, 14):
        await _sent(db_session, loan_file, days_ago=days)

    suggestions = await build_suggestions(db_session, company_id=company.id)

    assert len([s for s in suggestions if s.kind is ReminderKind.NO_REPLY]) == 1


async def test_a_draft_is_not_a_send(db_session: AsyncSession) -> None:
    """Nobody has heard from us. Counting a draft would nag about silence we caused."""
    company, loan_file = await _company_and_file(db_session, slug="draft")
    draft = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.flush()
    draft.created_at = utcnow() - LONG_AGO
    await db_session.flush()

    assert ReminderKind.NO_REPLY not in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


# --------------------------------------------------------------------------------------------- #
# Rule 3
# --------------------------------------------------------------------------------------------- #
async def test_a_file_quiet_for_eight_days_is_suggested(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="quiet")
    from app.models.activity_log import ActivityLog
    from sqlalchemy import select

    entry = (
        await db_session.execute(
            select(ActivityLog).where(ActivityLog.loan_file_id == loan_file.id)
        )
    ).scalar_one()
    entry.created_at = utcnow() - timedelta(days=8)
    await db_session.flush()

    assert ReminderKind.FILE_UNTOUCHED in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_a_busy_file_is_not_suggested(db_session: AsyncSession) -> None:
    """THE CONTROL. A rule with no comparison fires on every file, and a list that always says
    everything is a list nobody reads."""
    company, _loan_file = await _company_and_file(db_session, slug="busy")

    assert ReminderKind.FILE_UNTOUCHED not in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_a_submitted_file_is_never_nagged_about(db_session: AsyncSession) -> None:
    """A submitted file is not one somebody forgot — it is finished, and nudging about it teaches a
    processor to ignore the list."""
    company, loan_file = await _company_and_file(db_session, slug="submitted")
    await _need(db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10)
    loan_file.status = LoanFileStatus.SUBMITTED
    await db_session.flush()

    assert await build_suggestions(db_session, company_id=company.id) == []


# --------------------------------------------------------------------------------------------- #
# Scoping
# --------------------------------------------------------------------------------------------- #
async def test_another_companys_files_are_never_suggested(db_session: AsyncSession) -> None:
    theirs, their_file = await _company_and_file(db_session, slug="rem-theirs")
    mine, _my_file = await _company_and_file(db_session, slug="rem-mine")
    await _need(db_session, their_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10)

    assert await build_suggestions(db_session, company_id=mine.id) == []
    assert await build_suggestions(db_session, company_id=theirs.id) != []


async def test_a_named_file_from_another_company_yields_nothing(
    db_session: AsyncSession,
) -> None:
    """The caller passes a file a scoped route resolved. Re-checking costs one comparison against
    the alternative of a suggestion list built from a file somebody else owns."""
    _theirs, their_file = await _company_and_file(db_session, slug="named-theirs")
    mine, _my_file = await _company_and_file(db_session, slug="named-mine")
    await _need(db_session, their_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10)

    assert (await build_suggestions(db_session, company_id=mine.id, loan_file=their_file)) == []


# --------------------------------------------------------------------------------------------- #
# Snooze and dismiss
# --------------------------------------------------------------------------------------------- #
async def test_a_snooze_hides_it_until_the_date(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="snooze")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )

    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=utcnow() + timedelta(days=2),
    )

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )
    # AND COMES BACK. A snooze that never expired would be a dismissal wearing the wrong name.
    later = utcnow() + timedelta(days=3)
    assert ReminderKind.NEEDS_ITEM_PENDING in _kinds(
        await build_suggestions(db_session, company_id=company.id, now=later)
    )


async def test_a_dismissal_never_comes_back(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="dismiss")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )

    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=None,
    )

    far_future = utcnow() + timedelta(days=400)
    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(
        await build_suggestions(db_session, company_id=company.id, now=far_future)
    )


async def test_snoozing_one_kind_does_not_hide_another(db_session: AsyncSession) -> None:
    """THE KIND IS PART OF THE IDENTITY. A processor who snoozed "nobody has replied" has not
    snoozed "this file has gone quiet" — different observations, different actions."""
    company, loan_file = await _company_and_file(db_session, slug="kinds")
    await _sent(db_session, loan_file, days_ago=10)
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )

    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=None,
    )

    assert ReminderKind.NO_REPLY in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_a_file_level_snooze_works_at_all(db_session: AsyncSession) -> None:
    """`subject_id` IS NULL FOR A FILE RULE, and the unique index carries NULLS NOT DISTINCT for it.
    Without that, every "file untouched" snooze is a fresh row and none of them suppresses
    anything — Postgres's default, biting in the direction that makes a feature silently do
    nothing."""
    from app.models.activity_log import ActivityLog
    from sqlalchemy import select

    company, loan_file = await _company_and_file(db_session, slug="filelevel")
    entry = (
        await db_session.execute(
            select(ActivityLog).where(ActivityLog.loan_file_id == loan_file.id)
        )
    ).scalar_one()
    entry.created_at = utcnow() - timedelta(days=10)
    await db_session.flush()
    assert ReminderKind.FILE_UNTOUCHED in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )

    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.FILE_UNTOUCHED,
        subject_id=None,
        until=None,
    )
    # TWICE, because the index is what makes the second one an update rather than a duplicate row.
    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.FILE_UNTOUCHED,
        subject_id=None,
        until=None,
    )

    assert ReminderKind.FILE_UNTOUCHED not in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_unsnoozing_brings_it_back(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="unsnooze")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )
    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=None,
    )

    assert (
        await unsnooze(
            db_session,
            loan_file=loan_file,
            kind=ReminderKind.NEEDS_ITEM_PENDING,
            subject_id=need.id,
        )
        is True
    )

    assert ReminderKind.NEEDS_ITEM_PENDING in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


async def test_re_snoozing_after_an_unsnooze_takes_effect(db_session: AsyncSession) -> None:
    """The row was soft-deleted, and `suppresses` returns False while `deleted_at` is set — so a
    re-snooze that only moved the date would do nothing at all, silently."""
    company, loan_file = await _company_and_file(db_session, slug="resnooze")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )
    for _ in range(1):
        await snooze(
            db_session,
            loan_file=loan_file,
            kind=ReminderKind.NEEDS_ITEM_PENDING,
            subject_id=need.id,
            until=None,
        )
        await unsnooze(
            db_session,
            loan_file=loan_file,
            kind=ReminderKind.NEEDS_ITEM_PENDING,
            subject_id=need.id,
        )

    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=None,
    )

    assert ReminderKind.NEEDS_ITEM_PENDING not in _kinds(
        await build_suggestions(db_session, company_id=company.id)
    )


# --------------------------------------------------------------------------------------------- #
# What a suggestion says
# --------------------------------------------------------------------------------------------- #
async def test_a_suggestion_carries_our_own_words(db_session: AsyncSession) -> None:
    """The need's TITLE, which comes from a template or a processor — never from a borrower's
    message. A summary built from inbound prose would put a stranger's words on a dashboard."""
    company, loan_file = await _company_and_file(db_session, slug="words")
    await _need(
        db_session,
        loan_file,
        status=NeedsItemStatus.REQUESTED,
        requested_days_ago=9,
        title="2024 W-2",
    )

    suggestion = next(
        s
        for s in await build_suggestions(db_session, company_id=company.id)
        if s.kind is ReminderKind.NEEDS_ITEM_PENDING
    )

    assert "2024 W-2" in suggestion.summary
    assert suggestion.days == 9
    assert suggestion.display_id == loan_file.display_id


async def test_the_oldest_problem_comes_first(db_session: AsyncSession) -> None:
    """A list ordered by anything else buries the thing that has been waiting longest, which is the
    one the rule exists to surface."""
    company, loan_file = await _company_and_file(db_session, slug="order")
    await _need(
        db_session,
        loan_file,
        status=NeedsItemStatus.REQUESTED,
        requested_days_ago=4,
        title="Recent",
    )
    await _need(
        db_session,
        loan_file,
        status=NeedsItemStatus.REQUESTED,
        requested_days_ago=20,
        title="Ancient",
    )

    suggestions = [
        s
        for s in await build_suggestions(db_session, company_id=company.id)
        if s.kind is ReminderKind.NEEDS_ITEM_PENDING
    ]

    assert suggestions[0].summary.startswith("Ancient")


# --------------------------------------------------------------------------------------------- #
# A decision covers the event it was about, not the subject forever (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_a_dismissal_does_not_silence_a_later_request(db_session: AsyncSession) -> None:
    """`until=None` is a documented dismissal and never expires.

    Keyed on (file, kind, subject) alone it also silenced a request made LATER about the same need.
    Measured before the fix: dismiss, let LP-819 unwind the request on a bounce, send a fresh one,
    leave it four days unanswered — and the engine produced nothing. The processor's decision was
    about a request that no longer exists.
    """
    company, loan_file = await _company_and_file(db_session, slug=f"stale{uuid4().hex[:6]}")
    need = await _need(
        db_session,
        loan_file,
        status=NeedsItemStatus.REQUESTED,
        requested_days_ago=10,
    )

    assert len(await build_suggestions(db_session, company_id=company.id)) == 1

    dismissal = await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=None,
    )
    # BACKDATED so the fixture is chronological. The dismissal has to happen BEFORE the new request,
    # or the scenario is one that cannot occur — and the first version of this test, which left it
    # at `now`, failed against correct code for exactly that reason.
    dismissal.created_at = utcnow() - timedelta(days=9)
    await db_session.flush()
    assert await build_suggestions(db_session, company_id=company.id) == []

    # LP-819 unwinds the bounced request, then a new one is sent and goes unanswered.
    need.status = NeedsItemStatus.PENDING
    need.requested_at = None
    await db_session.flush()
    need.status = NeedsItemStatus.REQUESTED
    need.requested_at = utcnow() - timedelta(days=4)
    await db_session.flush()

    again = await build_suggestions(db_session, company_id=company.id)
    assert len(again) == 1
    assert again[0].subject_id == need.id


async def test_a_dismissal_still_silences_the_request_it_was_about(
    db_session: AsyncSession,
) -> None:
    """The control, and the one that matters.

    A fix that simply stopped suppressing would satisfy the test above while making dismissal do
    nothing — every card a processor refused would come straight back, which is the failure the
    feature exists to avoid.
    """
    company, loan_file = await _company_and_file(db_session, slug=f"held{uuid4().hex[:6]}")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )

    await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=None,
    )
    await db_session.flush()

    # Time passes; the SAME request is still outstanding.
    assert await build_suggestions(db_session, company_id=company.id) == []


async def test_a_timed_snooze_still_expires_on_its_own_terms(db_session: AsyncSession) -> None:
    """The second control: the new comparison must not replace the date check.

    A snooze with a past date has to stop suppressing even though its subject's event has not moved.
    """
    company, loan_file = await _company_and_file(db_session, slug=f"exp{uuid4().hex[:6]}")
    need = await _need(
        db_session, loan_file, status=NeedsItemStatus.REQUESTED, requested_days_ago=10
    )

    row = await snooze(
        db_session,
        loan_file=loan_file,
        kind=ReminderKind.NEEDS_ITEM_PENDING,
        subject_id=need.id,
        until=utcnow() + timedelta(days=1),
    )
    await db_session.flush()
    assert await build_suggestions(db_session, company_id=company.id) == []

    row.snoozed_until = utcnow() - timedelta(minutes=1)
    await db_session.flush()

    assert len(await build_suggestions(db_session, company_id=company.id)) == 1
