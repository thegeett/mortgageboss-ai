"""LP-812 — the timeline, and the double-count it exists to remove.

THE FIRST TEST IS THE TICKET. `b7`'s warning going in was the right one: *"a merge that picks
per-source will show one arrival twice and look correct in every test built from one source."* So
the case that matters drives ONE real message through the REAL ingest chain — LP-803's ingest,
LP-804b's safety, LP-805's routing, all of which write their own row — and asserts the timeline
holds exactly one entry for it.

A fixture that hand-built a `Communication` would produce a timeline with one row whether or not the
reconciliation existed, because the activity entry it duplicates would never have been written.
"""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from app.models import Company, LoanProgram
from app.models.activity_log import ActivityType
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.services.activity_log import log_activity
from app.services.inbound_ingest import process_raw_message
from app.services.timeline import (
    MESSAGE_ACTIVITY_TYPES,
    TimelineFilter,
    TimelineKind,
    build_timeline,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

_PDF = (Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf").read_bytes()


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


def _raw(address: str, *, message_id: str, filename: str = "March_statement.pdf") -> bytes:
    message = EmailMessage()
    message["From"] = "jane@borrower.example"
    message["To"] = address
    message["Subject"] = "Statements attached"
    message["Message-ID"] = f"<{message_id}>"
    message.set_content("here you go")
    message.add_attachment(_PDF, maintype="application", subtype="pdf", filename=filename)
    return message.as_bytes(policy=policy.default)


# --------------------------------------------------------------------------------------------- #
# The double-count
# --------------------------------------------------------------------------------------------- #
async def test_one_real_arrival_is_one_timeline_row(db_session: AsyncSession) -> None:
    """THROUGH THE REAL CHAIN, so all three rows genuinely exist.

    LP-803 writes the `inbound_message`, LP-805 writes the `Communication` AND the
    `COMMUNICATION_RECEIVED` activity. A timeline that merged both sources naively shows this
    arrival twice — and would pass any test whose fixture wrote only one of them.
    """
    _company, loan_file = await _company_and_file(db_session, slug="once")
    await process_raw_message(
        db_session,
        raw=_raw(loan_file.get_inbox_address(), message_id="once@example.com"),
        raw_storage_path=None,
        store_raw=True,
    )

    # THE PRECONDITION, asserted rather than assumed: all three rows are really there.
    assert (
        (
            await db_session.execute(
                select(InboundMessage).where(InboundMessage.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert (
        (
            await db_session.execute(
                select(Communication).where(Communication.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    from app.models.activity_log import ActivityLog

    assert (
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.loan_file_id == loan_file.id,
                    ActivityLog.activity_type == ActivityType.COMMUNICATION_RECEIVED,
                )
            )
        )
        .scalars()
        .all()
    )

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    assert len(timeline) == 1
    assert timeline[0].kind is TimelineKind.MESSAGE
    assert timeline[0].direction == CommunicationDirection.INBOUND.value


async def test_the_one_row_carries_the_attachment_manifest(db_session: AsyncSession) -> None:
    """THE OTHER HALF OF THE RECONCILIATION. Choosing the `Communication` as the timeline's row left
    it needing a path to the attachments, which hang off `inbound_messages`. That path is the FK,
    not the sender-written `Message-ID`."""
    _company, loan_file = await _company_and_file(db_session, slug="manifest")
    await process_raw_message(
        db_session,
        raw=_raw(loan_file.get_inbox_address(), message_id="manifest@example.com"),
        raw_storage_path=None,
        store_raw=True,
    )

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    assert timeline[0].attachments == ("March_statement.pdf",)


async def test_a_non_message_activity_does_not_appear(db_session: AsyncSession) -> None:
    """LP-825 — THE REPORTED DEFECT, INVERTED FROM WHAT THIS TEST USED TO ASSERT.

    It read "a non-message activity STILL appears", and stood as the control against a timeline that
    dropped everything. That control was right about the risk and wrong about the requirement: the
    filter was written as "drop the three duplicates" and its effect was "keep the other
    twenty-nine", so a processor's Communication page carried document classifications, DTI
    overrides and field reviews. Measured on LF-JR4T: ten of eleven recent rows were not about
    communication.

    The control it provided has not been dropped — it moved to
    `test_a_message_still_appears_on_an_otherwise_busy_file`, which is the only kind of row left. A
    silent empty timeline is still the failure nobody reports; it just is not this assertion any
    more.
    """
    _company, loan_file = await _company_and_file(db_session, slug="activity")
    await log_activity(
        db_session,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary="A document was uploaded",
    )

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    assert timeline == []


async def test_a_message_still_appears_on_an_otherwise_busy_file(
    db_session: AsyncSession,
) -> None:
    """THE CONTROL, in its new home. A timeline that returned nothing at all would satisfy the test
    above and every filter test below, and the failure would be a Communication page that shows
    silence on a file with a live conversation — worse than the noise it replaced."""
    _company, loan_file = await _company_and_file(db_session, slug="busy")
    for activity_type in (
        ActivityType.DOCUMENT_UPLOADED,
        ActivityType.DTI_OVERRIDDEN,
        ActivityType.FIELD_REVIEWED,
    ):
        await log_activity(
            db_session,
            loan_file_id=loan_file.id,
            activity_type=activity_type,
            summary=f"{activity_type.value} happened",
        )
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            recipient="jane@borrower.example",
            subject="Documents we need",
        )
    )
    await db_session.flush()

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    assert [entry.kind for entry in timeline] == [TimelineKind.MESSAGE]
    assert timeline[0].subject == "Documents we need"


def test_every_communication_activity_type_is_excluded() -> None:
    """DERIVED FROM THE ENUM, not listed. A fourth `COMMUNICATION_*` type added later would appear
    beside the Communication it describes — the same double-count, arriving by a different route.

    The non-empty assertion is the control on the derivation itself: a set built by a predicate that
    matches nothing excludes nothing, and reads exactly like a working exclusion.
    """
    matching = {activity for activity in ActivityType if activity.name.startswith("COMMUNICATION_")}

    assert matching, "the prefix matched nothing — the exclusion would be silently empty"
    assert matching == MESSAGE_ACTIVITY_TYPES
    assert ActivityType.COMMUNICATION_FAILED in MESSAGE_ACTIVITY_TYPES


async def test_a_bounce_does_not_appear_twice(db_session: AsyncSession) -> None:
    """LP-819 writes a `COMMUNICATION_FAILED` activity AND sets the Communication to FAILED. The
    message row already says it failed; the activity beside it would read as a second event."""
    _company, loan_file = await _company_and_file(db_session, slug="bounce")
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.FAILED,
            recipient="jane@borrower.example",
        )
    )
    await log_activity(
        db_session,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.COMMUNICATION_FAILED,
        summary="A message bounced",
    )

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    assert len(timeline) == 1
    assert timeline[0].summary == "A message could not be delivered"


# --------------------------------------------------------------------------------------------- #
# Order
# --------------------------------------------------------------------------------------------- #
async def test_a_sent_message_sits_at_when_it_was_sent(db_session: AsyncSession) -> None:
    """A draft composed on Monday and sent on Thursday belongs at Thursday — that is when the
    borrower heard from us. Ordered by composition, the send would appear before a reminder that
    actually preceded it."""
    from datetime import timedelta

    from app.models.base import utcnow

    _company, loan_file = await _company_and_file(db_session, slug="order")
    sent = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        recipient="jane@borrower.example",
        sent_at=utcnow(),
    )
    db_session.add(sent)
    await db_session.flush()
    sent.created_at = utcnow() - timedelta(days=3)
    await log_activity(
        db_session,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary="Something happened yesterday",
    )
    await db_session.flush()
    from app.models.activity_log import ActivityLog

    activity_row = (
        await db_session.execute(
            select(ActivityLog).where(ActivityLog.loan_file_id == loan_file.id)
        )
    ).scalar_one_or_none()
    assert activity_row is not None
    activity_row.created_at = utcnow() - timedelta(days=1)
    await db_session.flush()

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    # LP-825 — the activity row this used to sit beside is no longer on the timeline, so the
    # ordering claim is now made against `created_at` directly: the message is placed at `sent_at`
    # (today), not at its composition three days ago, which is the whole point of `_message_at`.
    assert [entry.kind for entry in timeline] == [TimelineKind.MESSAGE]
    assert timeline[0].at == sent.sent_at
    assert timeline[0].at > sent.created_at


# --------------------------------------------------------------------------------------------- #
# The filter pills
# --------------------------------------------------------------------------------------------- #
async def _mixed(db: AsyncSession, loan_file) -> None:
    for direction, status in (
        (CommunicationDirection.OUTBOUND, CommunicationStatus.SENT),
        (CommunicationDirection.OUTBOUND, CommunicationStatus.DRAFT),
        (CommunicationDirection.OUTBOUND, CommunicationStatus.QUEUED),
        (CommunicationDirection.INBOUND, CommunicationStatus.RECEIVED),
    ):
        db.add(
            Communication(
                loan_file_id=loan_file.id,
                direction=direction,
                status=status,
                recipient="jane@borrower.example",
                template_key=f"k-{status.value}",
            )
        )
    await log_activity(
        db,
        loan_file_id=loan_file.id,
        activity_type=ActivityType.DOCUMENT_UPLOADED,
        summary="A document was uploaded",
    )
    await db.flush()


async def test_all_shows_everything(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="pill-all")
    await _mixed(db_session, loan_file)

    # FOUR — `_mixed`'s four messages. Its activity row is not on the timeline since LP-825, and
    # "all" means every row the timeline HAS, not every row the file has.
    assert len((await build_timeline(db_session, loan_file=loan_file))[0]) == 4


async def test_sent_excludes_drafts(db_session: AsyncSession) -> None:
    """A draft is outbound and has not gone. Showing it under "sent" tells a processor they have
    already asked for something they have not."""
    _company, loan_file = await _company_and_file(db_session, slug="pill-sent")
    await _mixed(db_session, loan_file)

    entries, _truncated = await build_timeline(
        db_session, loan_file=loan_file, wanted=TimelineFilter.SENT
    )

    assert [entry.status for entry in entries] == [CommunicationStatus.SENT.value]


async def test_drafts_includes_a_queued_auto_reply(db_session: AsyncSession) -> None:
    """QUEUED is a message not yet gone, which is what a processor means by drafts — and it is the
    one state no other pill would show, so excluding it here makes it invisible everywhere."""
    _company, loan_file = await _company_and_file(db_session, slug="pill-drafts")
    await _mixed(db_session, loan_file)

    entries, _truncated = await build_timeline(
        db_session, loan_file=loan_file, wanted=TimelineFilter.DRAFTS
    )

    assert {entry.status for entry in entries} == {
        CommunicationStatus.DRAFT.value,
        CommunicationStatus.QUEUED.value,
    }


async def test_received_is_inbound_only(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="pill-recv")
    await _mixed(db_session, loan_file)

    entries, _truncated = await build_timeline(
        db_session, loan_file=loan_file, wanted=TimelineFilter.RECEIVED
    )

    assert [entry.direction for entry in entries] == [CommunicationDirection.INBOUND.value]


def test_there_is_no_activity_pill(db_session: AsyncSession) -> None:
    """LP-825 — REMOVED, NOT LEFT EMPTY. The pill could only ever match an activity row and the
    timeline has none, so it would answer "Nothing in activity" on every file forever. A control
    that always says nothing is a broken control, not a filter with no results.

    Asserted against the enum rather than the screen, because the pill list is built from it: a
    reinstated member would put the pill back on the panel with nothing behind it."""
    assert not hasattr(TimelineFilter, "ACTIVITY")
    assert {f.value for f in TimelineFilter} == {"all", "sent", "received", "drafts"}


# --------------------------------------------------------------------------------------------- #
# Scoping
# --------------------------------------------------------------------------------------------- #
async def test_a_sibling_files_history_does_not_leak_in(db_session: AsyncSession) -> None:
    """SAME COMPANY, TWO FILES. The scoping axis here is the file, and a company-scoped query would
    pass every cross-tenant test while showing one borrower's mail on another borrower's file."""
    from app.services.loan_files import create_loan_file

    company, mine = await _company_and_file(db_session, slug="sibling")
    theirs = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _mixed(db_session, theirs)

    assert (await build_timeline(db_session, loan_file=mine))[0] == []
    # FOUR, not five: `_mixed` adds four messages and one activity, and LP-825 took the activity off
    # the timeline. The number is stated here rather than counted from the fixture so that a change
    # to what the timeline carries fails this test rather than silently agreeing with it.
    assert len((await build_timeline(db_session, loan_file=theirs))[0]) == 4


async def test_the_timeline_never_carries_a_body(db_session: AsyncSession) -> None:
    """A timeline is a list anybody scrolls past. The body lives on the message, is dropped from
    every readonly view, and would make this the fullest copy of a borrower's prose in the product.

    The fixture puts a distinctive string in the body so the absence is a choice, not an empty
    column.
    """
    _company, loan_file = await _company_and_file(db_session, slug="nobody")
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            recipient="jane@borrower.example",
            subject="Your documents",
            body="Dear Jane, your account ending 4821 needs a statement.",
        )
    )
    await db_session.flush()

    timeline, _truncated = await build_timeline(db_session, loan_file=loan_file)

    rendered = repr(timeline[0])
    assert "4821" not in rendered
    assert "Dear Jane" not in rendered
    # The SUBJECT does travel — it is what a processor recognises a message by.
    assert timeline[0].subject == "Your documents"


# --------------------------------------------------------------------------------------------- #
# The backfill, RUN rather than read (review finding)
# --------------------------------------------------------------------------------------------- #
def _backfill_sql() -> str:
    """The migration's one-shot UPDATE, imported so a test can execute it.

    A backfill is the least reviewable thing in a migration: it runs once, against data nobody has,
    and is unfalsifiable afterwards. `test_readonly_query.py` reaches into migrations for view DDL
    for the same reason.
    """
    from importlib.util import module_from_spec, spec_from_file_location

    root = Path(__file__).resolve().parents[1].parent / "alembic" / "versions"
    # A migration revision id, not a secret — detect-secrets sees the entropy, not the meaning.
    (path,) = [p for p in root.glob("*.py") if "c5f9a3b71d80" in p.name]  # pragma: allowlist secret
    spec = spec_from_file_location("_mig_c5f9a3b71d80", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module._BACKFILL)


async def _inbound_pair(
    db: AsyncSession, *, loan_file, message_id: str, deleted: bool = False
) -> InboundMessage:
    message = InboundMessage(
        company_id=loan_file.company_id,
        loan_file_id=loan_file.id,
        ingest_key=f"k-{uuid4().hex}",
        routing_state=InboundRoutingState.ROUTED,
        message_id=message_id,
        raw_storage_path="s3://bucket/key",
        auth_verdicts={},
        deleted_at=utcnow() if deleted else None,
    )
    db.add(message)
    await db.flush()
    return message


async def test_the_backfill_does_not_link_to_a_soft_deleted_message(
    db_session: AsyncSession,
) -> None:
    """Measured before the fix: it did.

    Neither side of the join excluded soft deletes, so a Communication was linked to an
    `inbound_message` somebody had deleted — and the timeline row then pointed at a manifest for a
    message that is gone.
    """
    _company, loan_file = await _company_and_file(db_session, slug=f"bf-{uuid4().hex[:6]}")
    gone = await _inbound_pair(
        db_session, loan_file=loan_file, message_id="<only@example.com>", deleted=True
    )
    comm = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        external_message_id="<only@example.com>",
    )
    db_session.add(comm)
    await db_session.flush()

    await db_session.execute(text(_backfill_sql()))
    await db_session.refresh(comm)

    assert gone.deleted_at is not None  # the fixture is armed
    assert comm.inbound_message_id is None


async def test_the_backfill_links_a_live_unambiguous_message(db_session: AsyncSession) -> None:
    """The control. Excluding deleted rows on both sides must not stop the backfill working —
    a query that links nothing satisfies the test above and leaves every timeline row without its
    manifest."""
    _company, loan_file = await _company_and_file(db_session, slug=f"bf-{uuid4().hex[:6]}")
    live = await _inbound_pair(db_session, loan_file=loan_file, message_id="<live@example.com>")
    comm = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        external_message_id="<live@example.com>",
    )
    db_session.add(comm)
    await db_session.flush()

    await db_session.execute(text(_backfill_sql()))
    await db_session.refresh(comm)

    assert comm.inbound_message_id == live.id


async def test_a_deleted_duplicate_no_longer_suppresses_a_good_link(
    db_session: AsyncSession,
) -> None:
    """The other half of the same omission, in the opposite direction.

    The ambiguity guard counted soft-deleted rows too, so a deleted duplicate made a genuinely
    unambiguous link look ambiguous and left it NULL. One half of the query was too permissive and
    the other too strict, from one missing predicate.
    """
    _company, loan_file = await _company_and_file(db_session, slug=f"bf-{uuid4().hex[:6]}")
    await _inbound_pair(
        db_session, loan_file=loan_file, message_id="<dup@example.com>", deleted=True
    )
    live = await _inbound_pair(db_session, loan_file=loan_file, message_id="<dup@example.com>")
    comm = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        external_message_id="<dup@example.com>",
    )
    db_session.add(comm)
    await db_session.flush()

    await db_session.execute(text(_backfill_sql()))
    await db_session.refresh(comm)

    assert comm.inbound_message_id == live.id


async def test_two_live_duplicates_are_still_left_unlinked(db_session: AsyncSession) -> None:
    """The guard the builder called unreachable, kept and proven to fire.

    It IS reachable: `message_id` is sender-written and not unique, and since LP-807 keyed dedup on
    the SES id, two deliveries of one thread can carry the same header and route to the same file.
    A timeline row with no manifest is a gap somebody can see; one attached to another message's
    documents is not.
    """
    _company, loan_file = await _company_and_file(db_session, slug=f"bf-{uuid4().hex[:6]}")
    await _inbound_pair(db_session, loan_file=loan_file, message_id="<two@example.com>")
    await _inbound_pair(db_session, loan_file=loan_file, message_id="<two@example.com>")
    comm = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.INBOUND,
        status=CommunicationStatus.RECEIVED,
        external_message_id="<two@example.com>",
    )
    db_session.add(comm)
    await db_session.flush()

    await db_session.execute(text(_backfill_sql()))
    await db_session.refresh(comm)

    assert comm.inbound_message_id is None


async def test_a_truncated_timeline_says_so(db_session: AsyncSession) -> None:
    """There is no pagination yet, so the cap drops the OLDEST entries.

    A page that looks whole and is not is the wrong failure: a processor hunting the message that
    started a thread finds a complete-looking timeline that does not contain it. Until this is
    paginated the response at least has to be able to say there is more.
    """
    _company, loan_file = await _company_and_file(db_session, slug=f"trunc-{uuid4().hex[:6]}")
    # MESSAGES, not activity rows. This fixture used the activity log because it was the cheapest
    # way to make four entries; since LP-825 that produces an EMPTY timeline, and the truncation
    # test would have passed on nothing being capped at all.
    for index in range(4):
        db_session.add(
            Communication(
                loan_file_id=loan_file.id,
                direction=CommunicationDirection.OUTBOUND,
                status=CommunicationStatus.DRAFT,
                recipient="jane@borrower.example",
                subject=f"entry {index}",
                template_key=f"trunc-{index}",
            )
        )
    await db_session.flush()

    full, truncated = await build_timeline(db_session, loan_file=loan_file)
    assert len(full) == 4
    assert truncated is False  # the control: an uncapped timeline must not claim truncation

    capped, truncated = await build_timeline(db_session, loan_file=loan_file, limit=2)
    assert len(capped) == 2
    assert truncated is True
