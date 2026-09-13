"""LP-850 — outstanding means outstanding, and one draft per party.

Two defects with one root cause: **draft membership was being used as the source of truth for what
is outstanding**. The needs list already knows — it is literally the `needs_action` group — and
`_outstanding_needs` re-derived the same fact from a different table without ever looking at
`NeedsItem.status`.

The first test in this file is the one that fails on `phase4-with-ui`. It was written and run before
any of the code under it changed, and it failed for the stated reason: a bank statement marked
`verified` while its draft sat unsent was carried into the next draft and asked for again.

The second defect — N clicks leaving N live, sendable drafts with overlapping contents — is closed by
construction rather than by a warning: there is no longer a way to create a second open draft for a
party. A request against an open one either appends to it or marks it sent and starts a fresh one.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.documents.catalog import ResponsibleParty
from app.models import Company, LoanProgram
from app.models.communication import Communication, CommunicationStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.email_draft import (
    DraftDecisionRequired,
    OnConflict,
    add_needs_to_draft,
    open_drafts,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def _file_and_actor(db: AsyncSession):
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
    return loan_file, user.id


async def _need(db: AsyncSession, loan_file, *, title: str, needs_type: str | None) -> NeedsItem:
    item = NeedsItem(
        loan_file_id=loan_file.id,
        title=title,
        needs_type=needs_type,
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(item)
    await db.flush()
    return item


async def _count_drafts(db: AsyncSession, loan_file) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Communication)
            .where(
                Communication.loan_file_id == loan_file.id,
                Communication.status == CommunicationStatus.DRAFT,
                Communication.deleted_at.is_(None),
            )
        )
        or 0
    )


# --------------------------------------------------------------------------------------------- #
# Acceptance 1 — the test that failed before the fix
# --------------------------------------------------------------------------------------------- #
async def test_a_need_verified_while_its_draft_is_unsent_is_not_asked_for_again(
    db_session: AsyncSession,
) -> None:
    """THE DEFECT, ISOLATED FROM THE COINCIDENCE THAT HID IT.

    `_outstanding_needs` never filtered on `NeedsItem.status`, so a need that had been received or
    verified stayed outstanding for as long as some unsent draft carried it. It only LOOKED correct
    because marking a draft sent also clears the set — the needs drop out because of the send, not
    because the document arrived.

    So the document arrives here WITHOUT a send, which is the ordinary case rather than a contrived
    one: with no live inbound mail, documents come in by manual upload or the secure link, and a
    borrower who sends something after a phone call makes "arrived before its request went out"
    routine.

    The carry-forward is read BEFORE the old draft is marked sent, which is the order that makes
    this test mean something: read it after, and the new draft carries nothing forward from anything
    ever, and this passes for a reason that would also break
    `test_the_new_draft_still_carries_what_is_still_outstanding` below.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)

    # The statement arrives by upload and passes. Nothing was sent; the draft is still open.
    first.status = NeedsItemStatus.VERIFIED
    await db_session.flush()

    two = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )

    assert two.draft is not None
    assert "Pay stubs" in (two.draft.body or "")
    assert "Bank statements" not in (two.draft.body or ""), (
        "a need that is already VERIFIED was carried into the next draft"
    )


async def test_a_received_need_is_not_asked_for_again_either(db_session: AsyncSession) -> None:
    """`received` and `verified` are both "the document is in the file".

    Asserted separately rather than parametrised over the whole enum, because the two halves of the
    set have to be checked in opposite directions and a single loop would hide which one moved:
    `rejected` below must STAY outstanding.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    first.status = NeedsItemStatus.RECEIVED
    await db_session.flush()

    two = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )
    assert two.draft is not None
    assert "Bank statements" not in (two.draft.body or "")


@pytest.mark.parametrize(
    "status",
    [NeedsItemStatus.PENDING, NeedsItemStatus.REQUESTED, NeedsItemStatus.REJECTED],
)
async def test_the_new_draft_still_carries_what_is_still_outstanding(
    db_session: AsyncSession, status: NeedsItemStatus
) -> None:
    """THE OTHER DIRECTION, WHICH THE FILTER MUST NOT BREAK.

    A filter that dropped everything would pass the two tests above. `rejected` is the one that
    matters most: a document arrived and FAILED — expired, illegible, the wrong month — and the need
    is still open. Dropping it out of the next request is how a borrower never learns their statement
    was unreadable.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    first.status = status
    await db_session.flush()

    two = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )
    assert two.draft is not None
    assert "Bank statements" in (two.draft.body or "")
    assert "Pay stubs" in (two.draft.body or "")


async def test_a_waived_need_drops_out_too(db_session: AsyncSession) -> None:
    """`waived` is the processor deciding it does not apply. Asking for it anyway contradicts them."""
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    first.status = NeedsItemStatus.WAIVED
    await db_session.flush()

    two = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )
    assert two.draft is not None
    assert "Bank statements" not in (two.draft.body or "")


# --------------------------------------------------------------------------------------------- #
# Acceptance 2, 3 — one open draft per party, and a refusal that writes nothing
# --------------------------------------------------------------------------------------------- #
async def test_two_requests_in_a_row_for_one_party_produce_one_draft(
    db_session: AsyncSession,
) -> None:
    """ACCEPTANCE 2. LP-832 left N drafts for N clicks and nothing marked the earlier ones obsolete,
    because nothing knew they were. Appending is what makes "the open draft to the borrower" a
    phrase a screen can keep true."""
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
    )
    two = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.APPEND,
    )

    assert one.draft is not None and two.draft is not None
    assert one.draft.id == two.draft.id
    assert await _count_drafts(db_session, loan_file) == 1
    assert "Bank statements" in (two.draft.body or "")
    assert "Pay stubs" in (two.draft.body or "")


async def test_an_open_draft_refuses_and_names_its_contents(db_session: AsyncSession) -> None:
    """ACCEPTANCE 3. The refusal carries the draft's age and its documents, because "there is an
    open draft" is not something a processor can decide with."""
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
    )
    assert one.draft is not None

    with pytest.raises(DraftDecisionRequired) as raised:
        await add_needs_to_draft(
            db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
        )

    conflicts = raised.value.decisions_required
    assert len(conflicts) == 1
    assert conflicts[0].party is ResponsibleParty.BORROWER
    assert conflicts[0].draft_id == one.draft.id
    assert conflicts[0].created_at == one.draft.created_at
    assert [n.title for n in conflicts[0].carrying] == ["Bank statements"]
    assert [n.title for n in conflicts[0].adding] == ["Pay stubs"]
    assert raised.value.would_create == ()


async def test_a_refusal_writes_nothing(db_session: AsyncSession) -> None:
    """ACCEPTANCE 3, the half a toast cannot tell you: checked against the database.

    A refusal that had already created the draft, or already added the membership row, would look
    identical from the UI and would leave a document in an email the processor said not to touch.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
    )
    assert one.draft is not None
    body_before = one.draft.body

    with pytest.raises(DraftDecisionRequired):
        await add_needs_to_draft(
            db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
        )

    assert await _count_drafts(db_session, loan_file) == 1
    await db_session.refresh(one.draft)
    assert one.draft.body == body_before
    assert "Pay stubs" not in (one.draft.body or "")


async def test_a_second_click_on_the_same_document_is_not_a_conflict(
    db_session: AsyncSession,
) -> None:
    """NOTHING NEW IS NOT A DECISION. Asking a processor to choose between appending nothing and
    sending a draft they did not mean to send would be a dialog about a click that did not happen."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")

    first = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    again = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert first.draft is not None and again.draft is not None
    assert again.draft.id == first.draft.id
    assert again.added == ()
    assert again.already_present == (need.id,)
    assert await _count_drafts(db_session, loan_file) == 1


async def test_a_need_already_in_the_draft_is_not_added_twice_even_once_verified(
    db_session: AsyncSession,
) -> None:
    """ "ALREADY IN THIS DRAFT" IS NOT "STILL OUTSTANDING", and reading the second for the first is
    how one document ends up in one email twice.

    A verified need has left the outstanding set — that is this ticket. It has NOT left the draft,
    and requesting it again must still add nothing.
    """
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")

    first = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    assert first.draft is not None
    need.status = NeedsItemStatus.VERIFIED
    await db_session.flush()

    again = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    assert again.added == ()
    assert again.already_present == (need.id,)
    assert (again.draft.body or "").count("Bank statements") == 1


# --------------------------------------------------------------------------------------------- #
# Acceptance 4 — mark sent and start a new one
# --------------------------------------------------------------------------------------------- #
async def test_mark_sent_and_new_leaves_the_old_draft_sent_with_its_needs_intact(
    db_session: AsyncSession,
) -> None:
    """ACCEPTANCE 4. The superseded draft is never deleted — LP-821's evidence record is what
    actually went out, and `mark_sent` is the existing transition rather than a new one."""
    from app.models.communication_needs_item import CommunicationNeedsItem

    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
    )
    assert one.draft is not None
    old_id = one.draft.id

    two = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )
    assert two.draft is not None
    assert two.draft.id != old_id

    old = await db_session.get(Communication, old_id)
    assert old is not None
    assert old.status is CommunicationStatus.SENT
    assert old.sent_at is not None
    assert old.deleted_at is None
    membership = await db_session.scalar(
        select(func.count())
        .select_from(CommunicationNeedsItem)
        .where(CommunicationNeedsItem.communication_id == old_id)
    )
    assert membership == 1

    # THE CLOCK LP-814 READS. `requested_at` is stamped by the send, which is what makes this the
    # existing transition rather than a status assignment wearing its name.
    await db_session.refresh(first)
    assert first.requested_at is not None
    assert first.status is NeedsItemStatus.REQUESTED

    # And the new draft carries the one still outstanding plus the new one.
    assert "Bank statements" in (two.draft.body or "")
    assert "Pay stubs" in (two.draft.body or "")
    assert await _count_drafts(db_session, loan_file) == 1


async def test_marking_a_draft_sent_does_not_move_a_need_to_received(
    db_session: AsyncSession,
) -> None:
    """ACCEPTANCE 6. SENDING IS NOT RECEIVING.

    The claim is that a processor put the message into their own mail client. Nothing observed the
    borrower reading it, and nothing observed a document arriving.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )

    await db_session.refresh(first)
    assert first.status is not NeedsItemStatus.RECEIVED
    assert first.status is NeedsItemStatus.REQUESTED
    assert first.satisfied_at is None
    assert first.satisfied_by_document_id is None


async def test_marking_sent_does_not_un_arrive_a_document_that_has_landed(
    db_session: AsyncSession,
) -> None:
    """THE OTHER HALF OF ACCEPTANCE 6, and the one that would have re-armed the defect.

    `request_needs_item` set the status unconditionally, so a need that was already `verified` when
    its draft was marked sent was pushed BACK to `requested` — and `requested` is outstanding, so
    the document already sitting in the file re-entered the next email by a second route.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    first.status = NeedsItemStatus.VERIFIED
    await db_session.flush()

    await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )

    await db_session.refresh(first)
    assert first.status is NeedsItemStatus.VERIFIED


# --------------------------------------------------------------------------------------------- #
# Acceptance 5 — one request, two parties
# --------------------------------------------------------------------------------------------- #
async def test_a_request_spanning_two_parties_refuses_once_and_names_both(
    db_session: AsyncSession,
) -> None:
    """ACCEPTANCE 5. ONE REFUSAL, NOT TWO.

    The party with nothing open needs no decision and still appears, because a processor must leave
    the dialog knowing a second message exists. That is LP-852's rule showing up here.
    """
    loan_file, actor = await _file_and_actor(db_session)
    borrower_need = await _need(
        db_session, loan_file, title="Bank statements", needs_type="bank_statement"
    )
    await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[borrower_need], actor_user_id=actor
    )

    more_borrower = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    title_need = await _need(
        db_session, loan_file, title="Title commitment", needs_type="title_commitment"
    )

    with pytest.raises(DraftDecisionRequired) as raised:
        await add_needs_to_draft(
            db_session,
            loan_file=loan_file,
            needs=[more_borrower, title_need],
            actor_user_id=actor,
        )

    assert [c.party for c in raised.value.decisions_required] == [ResponsibleParty.BORROWER]
    assert [w.party for w in raised.value.would_create] == [ResponsibleParty.TITLE]
    assert [n.title for n in raised.value.would_create[0].adding] == ["Title commitment"]


async def test_two_parties_with_nothing_open_need_no_decision(db_session: AsyncSession) -> None:
    """A file with no drafts on it shows no dialog at all — acceptance 1 of LP-851, held here."""
    loan_file, actor = await _file_and_actor(db_session)
    borrower_need = await _need(
        db_session, loan_file, title="Bank statements", needs_type="bank_statement"
    )
    title_need = await _need(
        db_session, loan_file, title="Title commitment", needs_type="title_commitment"
    )

    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[borrower_need, title_need], actor_user_id=actor
    )
    parties = {p.party for p in update.parties if p.draft is not None}
    assert parties == {ResponsibleParty.BORROWER, ResponsibleParty.TITLE}
    assert await _count_drafts(db_session, loan_file) == 2


async def test_one_partys_open_draft_does_not_block_another_partys_new_one(
    db_session: AsyncSession,
) -> None:
    """THE CONSTRAINT IS PER PARTY, which is why LP-832's file-keyed index could not express it.

    A title company's draft and a borrower's draft are both legitimately open at once.
    """
    loan_file, actor = await _file_and_actor(db_session)
    borrower_need = await _need(
        db_session, loan_file, title="Bank statements", needs_type="bank_statement"
    )
    await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[borrower_need], actor_user_id=actor
    )

    title_need = await _need(
        db_session, loan_file, title="Title commitment", needs_type="title_commitment"
    )
    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[title_need], actor_user_id=actor
    )

    title = next(p for p in update.parties if p.party is ResponsibleParty.TITLE)
    assert title.draft is not None
    assert len(await open_drafts(db_session, loan_file_id=loan_file.id)) == 1
    assert (
        len(await open_drafts(db_session, loan_file_id=loan_file.id, party=ResponsibleParty.TITLE))
        == 1
    )


async def test_one_partys_outstanding_documents_stay_out_of_anothers_draft(
    db_session: AsyncSession,
) -> None:
    """FIVE PARTIES SHARE ONE TEMPLATE KEY since LP-843, and `_outstanding_needs` matched on it.

    So "the title company's outstanding documents" also returned the lender's, the agent's, the
    CPA's and the insurer's — and a new title draft asked the closer for the lender's appraisal.
    Both queries read `Communication.party` now.
    """
    loan_file, actor = await _file_and_actor(db_session)
    lender_need = await _need(
        db_session, loan_file, title="Closing disclosure", needs_type="closing_disclosure"
    )
    await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[lender_need], actor_user_id=actor
    )

    title_need = await _need(
        db_session, loan_file, title="Title commitment", needs_type="title_commitment"
    )
    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[title_need], actor_user_id=actor
    )
    title = next(p for p in update.parties if p.party is ResponsibleParty.TITLE)
    assert title.draft is not None
    assert "Title commitment" in (title.draft.body or "")
    assert "Closing disclosure" not in (title.draft.body or "")


async def test_one_answer_applies_to_every_conflicted_party(db_session: AsyncSession) -> None:
    """ONE `on_conflict` PER REQUEST, AND IT ANSWERS FOR ALL OF THEM (LP-851 review).

    `add_needs_to_draft` takes a single `on_conflict` and applies it to every party it planned. That
    is the contract LP-850's endpoint sketch describes — one value, not a value per party — and it
    is the reason LP-851's multi-party dialog answers once at the bottom rather than per row.

    IT WENT UNTESTED AND THE UI BELIEVED OTHERWISE. Screen 4 gives each party block its own "Mark
    sent, start new", and the first implementation wired every one of them to the same global
    answer — so pressing it inside the BORROWER's block marked the LENDER's draft sent too:
    `requested_at` stamped, an evidence row written, its needs moved to `REQUESTED`, for a draft the
    processor never opened. Nothing here contradicted that belief, because nothing here asserted
    what a multi-party answer does.

    So this pins the behaviour rather than the screen. If per-party answers are ever wanted, THIS is
    the test that has to change first, and the endpoint with it.
    """
    loan_file, actor = await _file_and_actor(db_session)

    borrower_need = await _need(
        db_session, loan_file, title="Bank statements", needs_type="bank_statement"
    )
    title_need = await _need(
        db_session, loan_file, title="Title commitment", needs_type="title_commitment"
    )
    opened = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[borrower_need, title_need],
        actor_user_id=actor,
    )
    open_ids = {p.party: p.draft.id for p in opened.parties if p.draft is not None}
    assert set(open_ids) == {ResponsibleParty.BORROWER, ResponsibleParty.TITLE}

    more_borrower = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    # A SECOND TITLE-COMPANY DOCUMENT. `payoff_statement` was the first choice and routes to the
    # PROCESSOR — `NO_RECIPIENT`, so it never becomes a draft at all and the test asserted about a
    # party that was never in the request. The catalog decides this, not the name.
    more_title = await _need(db_session, loan_file, title="Survey", needs_type="survey")
    await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[more_borrower, more_title],
        actor_user_id=actor,
        on_conflict=OnConflict.MARK_SENT_AND_NEW,
    )

    # BOTH of the drafts that were open are now sent — not just the one whose row was pressed.
    for party, draft_id in open_ids.items():
        row = await db_session.get(Communication, draft_id)
        assert row is not None
        assert row.status is CommunicationStatus.SENT, f"{party.value}'s draft was not marked sent"


async def test_append_also_answers_for_every_conflicted_party(
    db_session: AsyncSession,
) -> None:
    """THE CONTROL, in the other direction. A single answer that only ever reached ONE party would
    satisfy the test above by leaving the second draft open — and would silently drop the second
    party's new document, which is this epic's own worst failure."""
    loan_file, actor = await _file_and_actor(db_session)

    borrower_need = await _need(
        db_session, loan_file, title="Bank statements", needs_type="bank_statement"
    )
    title_need = await _need(
        db_session, loan_file, title="Title commitment", needs_type="title_commitment"
    )
    opened = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[borrower_need, title_need], actor_user_id=actor
    )
    open_ids = {p.party: p.draft.id for p in opened.parties if p.draft is not None}

    more_borrower = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    # A SECOND TITLE-COMPANY DOCUMENT. `payoff_statement` was the first choice and routes to the
    # PROCESSOR — `NO_RECIPIENT`, so it never becomes a draft at all and the test asserted about a
    # party that was never in the request. The catalog decides this, not the name.
    more_title = await _need(db_session, loan_file, title="Survey", needs_type="survey")
    await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[more_borrower, more_title],
        actor_user_id=actor,
        on_conflict=OnConflict.APPEND,
    )

    borrower_draft = await db_session.get(Communication, open_ids[ResponsibleParty.BORROWER])
    title_draft = await db_session.get(Communication, open_ids[ResponsibleParty.TITLE])
    assert borrower_draft is not None and title_draft is not None
    assert "Pay stubs" in (borrower_draft.body or "")
    assert "Survey" in (title_draft.body or "")
    assert borrower_draft.status is CommunicationStatus.DRAFT
    assert title_draft.status is CommunicationStatus.DRAFT
