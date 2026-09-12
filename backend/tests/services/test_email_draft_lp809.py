"""LP-809 — one accumulating draft per file, regenerated from its contents.

The behaviour worth protecting is not "a draft exists". It is that a processor who requests
documents four times over two days produces ONE email, that removing a line actually removes it,
and that the borrower is never asked for something that is not theirs to send.

Three of these fail silently if wrong. A second draft is invisible until someone opens the tab and
finds two. An appended body reads perfectly while contradicting the needs list. A stale
`template_version` is a correct-looking audit row pointing at the wrong words.
"""

from __future__ import annotations

from string import Template
from uuid import uuid4

import pytest
from app.documents.catalog import ResponsibleParty
from app.models import Company, LoanProgram
from app.models.base import utcnow
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import (
    DRAFT_TEMPLATE,
    add_needs_to_draft,
    finalise_draft_body,
    get_open_draft,
    open_drafts,
    remove_need_from_draft,
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


# --------------------------------------------------------------------------------------------- #
# Accumulation
# --------------------------------------------------------------------------------------------- #
async def test_a_second_request_makes_a_second_draft_carrying_both(
    db_session: AsyncSession,
) -> None:
    """LP-832 — THE MODEL CHANGED, AND THIS TEST ASSERTED THE OLD ONE.

    It read "a second request JOINS the first draft" and pinned `one.draft.id == two.draft.id` with a
    row count of 1. That was LP-809's design — four requests over two days are one email — and the
    user asked for the other one directly, with the alternative shown beside it: a new draft each
    time, the older ones left in the list.

    What LP-809 was protecting has not been dropped. The borrower still reads ONE list containing
    both documents; it is simply the newest draft's list rather than the only draft's. That is the
    half worth keeping and it is asserted below, because a model where each request produced a draft
    containing ONLY its own document would satisfy the row count and mail the borrower twice.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
    )
    two = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
    )

    assert one.draft is not None and two.draft is not None
    assert one.draft.id != two.draft.id
    count = await db_session.scalar(
        select(func.count())
        .select_from(Communication)
        .where(Communication.loan_file_id == loan_file.id)
    )
    assert count == 2

    # THE NEWEST CARRIES EVERYTHING OUTSTANDING — the property LP-809 existed for, kept.
    assert "Bank statements" in two.draft.body
    assert "Pay stubs" in two.draft.body
    # AND THE FIRST IS UNCHANGED. It is a draft a processor may still send; silently rewriting it to
    # match the newest would mail a borrower a list they were never shown.
    await db_session.refresh(one.draft)
    assert "Pay stubs" not in (one.draft.body or "")


async def test_adding_the_same_need_twice_is_a_no_op(db_session: AsyncSession) -> None:
    """A second click must not ask the borrower for one thing twice in one email — the failure
    LP-801's review found on the needs list, reachable again here."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)
    second = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert second.added == ()
    assert second.already_present == (need.id,)
    assert second.draft.body.count("Bank statements") == 1


async def test_the_body_is_regenerated_not_appended(db_session: AsyncSession) -> None:
    """Appending cannot express a removal. If the body were appended to, the removed document would
    still be in the email while the needs list said otherwise — and the email would look right."""
    loan_file, actor = await _file_and_actor(db_session)
    keep = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    drop = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[keep, drop], actor_user_id=actor
    )

    draft = await remove_need_from_draft(db_session, loan_file=loan_file, needs_item_id=drop.id)

    assert draft is not None
    assert "Bank statements" not in draft.body
    assert "Pay stubs" in draft.body


async def test_removing_the_last_need_keeps_an_empty_draft(db_session: AsyncSession) -> None:
    """A processor removing the last line is editing, not abandoning. Deleting the row would discard
    whatever else they had changed, and an empty draft is visibly empty where a missing one is not."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)

    await remove_need_from_draft(db_session, loan_file=loan_file, needs_item_id=need.id)

    draft = await get_open_draft(db_session, loan_file_id=loan_file.id)
    assert draft is not None
    assert "Pay stubs" not in draft.body


async def test_order_follows_when_each_need_was_added(db_session: AsyncSession) -> None:
    """A processor who added one thing on Wednesday should find it at the bottom, not the whole list
    reshuffled under them."""
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Zebra document", needs_type=None)
    second = await _need(db_session, loan_file, title="Alpha document", needs_type=None)
    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
    )

    body = result.draft.body
    assert body.index("Zebra document") < body.index("Alpha document")


# --------------------------------------------------------------------------------------------- #
# What does not go in a borrower's email
# --------------------------------------------------------------------------------------------- #
async def test_a_need_the_borrower_does_not_hold_is_not_added(db_session: AsyncSession) -> None:
    """LP-800's party field, reaching a borrower's inbox. An appraisal is ordered by the lender."""
    loan_file, actor = await _file_and_actor(db_session)
    theirs = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    not_theirs = await _need(db_session, loan_file, title="Appraisal", needs_type="appraisal")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[theirs, not_theirs], actor_user_id=actor
    )

    # LP-841 — THE APPRAISAL IS NOT DISCARDED ANY MORE, IT IS ROUTED. This asserted
    # `skipped_not_borrower`, which is the field that ticket removed: a request for a document the
    # borrower does not hold now produces a draft to whoever does, rather than a needs item and no
    # message to anybody.
    #
    # What this test was protecting is unchanged and is asserted below: the appraisal must not be in
    # an email addressed to the BORROWER. That was always the point; "and nothing else happens" was
    # the limitation, not the requirement.
    borrower = result.borrower
    assert borrower is not None and borrower.draft is not None
    assert borrower.added == (theirs.id,)
    assert "Appraisal" not in borrower.draft.body

    lender = next(p for p in result.parties if p.party is ResponsibleParty.LENDER)
    assert lender.added == (not_theirs.id,)
    assert lender.draft is not None
    assert "Appraisal" in (lender.draft.body or "")


async def test_a_skipped_need_still_exists_on_the_file(db_session: AsyncSession) -> None:
    """ "Not in this email" is not "dropped". The needs list is the record; the draft is not, and a
    processor still has to chase the appraiser."""
    loan_file, actor = await _file_and_actor(db_session)
    not_theirs = await _need(db_session, loan_file, title="Appraisal", needs_type="appraisal")

    await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[not_theirs], actor_user_id=actor
    )

    still_there = await db_session.get(NeedsItem, not_theirs.id)
    assert still_there is not None and still_there.deleted_at is None


async def test_an_untyped_need_is_treated_as_the_borrowers(db_session: AsyncSession) -> None:
    """LP-624 makes an untyped need routine — a request generated from a finding's own sentence has
    no catalog type. Those were created BY a processor clicking "request documents", so the decision
    to ask the borrower has already been made by a person; LP-800's processor default exists to
    protect against a document nobody classified, not to veto a request somebody made."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(
        db_session, loan_file, title="One more source stating the date of birth", needs_type=None
    )

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert result.added == (need.id,)
    assert "One more source stating the date of birth" in result.draft.body


async def test_a_catalogued_need_gets_its_full_guidance(db_session: AsyncSession) -> None:
    """The positive control for the fallback above: where LP-800 has instructions, the borrower gets
    them, not just a title."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert "Where to get it:" in result.draft.body
    assert "page 1 of 5" in result.draft.body


# --------------------------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------------------------- #
async def test_the_draft_records_the_template_and_version_that_rendered_it(
    db_session: AsyncSession,
) -> None:
    """phase4.md §6 wants template + version beside the body, and ADR-401 makes a version name
    exactly one set of words — which is worth nothing if the version is not stored."""
    from app.communications.templates import TEMPLATES

    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert result.draft.template_key == DRAFT_TEMPLATE.value
    assert result.draft.template_version == TEMPLATES[DRAFT_TEMPLATE].version


async def test_the_draft_carries_the_files_own_inbox_address(db_session: AsyncSession) -> None:
    """M3's routing depends on the borrower having been given THIS file's address. One file's
    address in another file's email would route documents to the wrong loan."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert loan_file.get_inbox_address() in result.draft.body


async def test_two_files_get_two_drafts(db_session: AsyncSession) -> None:
    """The uniqueness is per FILE. Without this, "one open draft" could be satisfied by one draft
    for the whole database and every test above would still pass."""
    first_file, actor = await _file_and_actor(db_session)
    second_file, _ = await _file_and_actor(db_session)
    a = await _need(db_session, first_file, title="Pay stubs", needs_type="pay_stub")
    b = await _need(db_session, second_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(db_session, loan_file=first_file, needs=[a], actor_user_id=actor)
    two = await add_needs_to_draft(
        db_session, loan_file=second_file, needs=[b], actor_user_id=actor
    )

    assert one.draft.id != two.draft.id


async def test_a_second_open_draft_is_now_permitted(db_session: AsyncSession) -> None:
    """LP-832 — `uq_communications_open_draft` IS GONE, and this test asserted it.

    It read "refused by the database", and the index was what made "the open draft" a true phrase
    under concurrency. Dropping it is the ticket, so the assertion is inverted — but the reason the
    index existed has to survive somewhere, and it is not here.

    Its own comment gave the reason as two near-simultaneous requests each creating a draft "with no
    basis for choosing between them". Two drafts are now correct; two drafts each MISSING THE OTHER'S
    document is not, and that is what a concurrent pair would produce from the same pre-state.
    `add_needs_to_draft` takes a row lock on the loan file, which is a guarantee no test on one
    connection can exercise — so it is asserted structurally in
    `test_the_draft_creation_path_locks_the_file` below rather than left as a claim in a docstring.
    """
    from app.models.communication import CommunicationDirection

    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)

    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            template_key=DRAFT_TEMPLATE.value,
            initiated_by_user_id=actor,
        )
    )
    await db_session.flush()  # must not raise

    assert len(await open_drafts(db_session, loan_file_id=loan_file.id)) == 2
    # AND THE LOOKUP DOES NOT RAISE EITHER. `scalar_one_or_none()` did — the four callers written
    # against it would have started failing on exactly this state.
    assert await get_open_draft(db_session, loan_file_id=loan_file.id) is not None


async def test_membership_goes_when_the_draft_goes(db_session: AsyncSession) -> None:
    """CASCADE, not SET NULL. A draft has no history to preserve — it was never sent — and a
    membership row pointing at nothing is a need that is in an email that does not exist."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    await db_session.delete(result.draft)
    await db_session.flush()

    remaining = await db_session.scalar(select(func.count()).select_from(CommunicationNeedsItem))
    assert remaining == 0


# --------------------------------------------------------------------------------------------- #
# Resolving the stored body at send time (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_a_dollar_amount_in_a_need_title_does_not_break_the_send(
    db_session: AsyncSession,
) -> None:
    """The stored body mixes template placeholders with text a PROCESSOR wrote, and the second
    substitution pass has to survive the human half.

    "Proof of $10,000 gift deposit" is an ordinary mortgage ask. `$10` is not a valid placeholder,
    so a strict `Template.substitute` over the stored body raises `ValueError: Invalid placeholder
    in string` and the send dies. Measured before `finalise_draft_body` existed; this pins both
    that the strict form still fails and that the supported path does not.
    """
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(
        db_session, loan_file, title="Proof of $10,000 gift deposit", needs_type=None
    )

    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    body = update.draft.body
    assert body is not None
    assert "$10,000" in body

    # The strict pass — what a caller reaching for `string.Template` directly would write.
    with pytest.raises(ValueError, match="Invalid placeholder"):
        Template(body).substitute(borrower_first_name="Ann", processor_name="Pat")

    final = finalise_draft_body(body, borrower_first_name="Ann", processor_name="Pat")
    assert "Proof of $10,000 gift deposit" in final  # reaches the borrower exactly as typed
    assert "Hello Ann," in final
    assert "$borrower_first_name" not in final
    assert "$processor_name" not in final


async def test_finalising_resolves_both_deferred_placeholders(db_session: AsyncSession) -> None:
    """The positive control. A `safe_substitute` that resolved NOTHING would also satisfy the test
    above, since its assertions are about what survives."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type=None)

    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    body = update.draft.body
    assert body is not None
    assert "$borrower_first_name" in body and "$processor_name" in body  # deferred, as designed

    final = finalise_draft_body(body, borrower_first_name="Ann", processor_name="Pat")
    assert "Hello Ann," in final
    assert final.rstrip().endswith("Pat")


# --------------------------------------------------------------------------------------------- #
# LP-832 — a request makes a draft; the set resets at a send
# --------------------------------------------------------------------------------------------- #
async def test_a_request_after_a_send_starts_fresh(db_session: AsyncSession) -> None:
    """THE HALF THAT IS NOT "accumulate forever". A draft carries everything requested SINCE THE LAST
    SEND, so the document that has already gone must not reappear in the next email.

    The sent document is requested BEFORE the send deliberately: a draft that carried everything ever
    requested would pass every other test in this file and fail only here.
    """
    loan_file, actor = await _file_and_actor(db_session)
    sent_one = await _need(
        db_session, loan_file, title="Bank statements", needs_type="bank_statement"
    )
    later = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    first = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[sent_one], actor_user_id=actor
    )
    assert first.draft is not None
    first.draft.status = CommunicationStatus.SENT
    await db_session.flush()

    after = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[later], actor_user_id=actor
    )

    assert after.draft is not None
    assert "Pay stubs" in after.draft.body
    assert "Bank statements" not in (after.draft.body or ""), (
        "the sent document came back — the set did not reset at the send"
    )


async def test_a_deleted_draft_does_not_take_its_documents_with_it(
    db_session: AsyncSession,
) -> None:
    """WHY THE OUTSTANDING SET IS A UNION AND NOT A READ OF THE NEWEST.

    While each draft is a superset of the last the two answers are identical, so this is the only
    fixture that separates them — and deleting a superseded draft is an action this model invites,
    because it leaves them in the list on purpose.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    third = await _need(db_session, loan_file, title="W-2", needs_type="w2")

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    newest = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
    )
    assert newest.draft is not None
    newest.draft.deleted_at = utcnow()
    await db_session.flush()

    after = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[third], actor_user_id=actor
    )

    assert after.draft is not None
    # The one still carried by the FIRST draft survives.
    assert "Bank statements" in after.draft.body
    assert "W-2" in after.draft.body
    # AND THE DELETED DRAFT'S OWN DOCUMENT IS GONE WITH IT — nothing carries it any more, which is
    # what deleting a draft means. This assertion is the only thing in the file that reads
    # `deleted_at` on the outstanding-set query: without it, dropping that predicate passes every
    # test here, which is exactly what a mutation run found. The comment described the property and
    # the fixture happened to satisfy it either way.
    assert "Pay stubs" not in (after.draft.body or "")


async def test_a_second_click_adds_nothing_and_mints_nothing(db_session: AsyncSession) -> None:
    """A REQUEST THAT ADDS NO DOCUMENT MUST NOT PUT A SECOND IDENTICAL EMAIL IN THE LIST.

    This is the other way of asking for nothing, beside the non-borrower request LP-809's review
    guarded: a second click on a finding already carried. Both mean "this added no document", and
    under a model where every request mints a draft the duplicate is the obvious failure.
    """
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
    assert len(await open_drafts(db_session, loan_file_id=loan_file.id)) == 1


async def test_the_draft_creation_path_locks_the_file(db_session: AsyncSession) -> None:
    """THE GUARANTEE THAT REPLACED THE INDEX, asserted structurally because a lock cannot be
    exercised on one connection.

    `uq_communications_open_draft` is dropped by this ticket, and its stated purpose was that two
    near-simultaneous requests must not each create a draft "with no basis for choosing between
    them". Under this model two drafts are correct; two drafts each missing the OTHER's new document
    is not, and that is what a concurrent pair produces when both compute the outstanding set from
    the same pre-state.

    Asserted on the emitted SQL rather than on a second connection: the test database is a single
    rollback-scoped transaction, so a genuine concurrent writer cannot be started here without
    leaving that isolation. The claim being made is narrow — the statement is issued, before
    anything is read — and it is better pinned narrowly than described in a comment nothing checks.
    """
    from sqlalchemy import event

    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")

    seen: list[str] = []
    bind = db_session.get_bind()
    # The session is bound to a CONNECTION in this suite (rollback isolation), not an engine, so the
    # listener goes on the sync connection it wraps.
    target = getattr(bind, "sync_connection", None) or getattr(bind, "sync_engine", bind)

    def _record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        seen.append(statement)

    event.listen(target, "before_cursor_execute", _record)
    try:
        await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)
    finally:
        event.remove(target, "before_cursor_execute", _record)

    locks = [s for s in seen if "FOR UPDATE" in s.upper() and "loan_files" in s]
    assert locks, "no row lock was taken on the loan file"
    # THE CONTROL: it must come before the read of what is outstanding, or a concurrent request has
    # already computed its set by the time this one locks.
    first_lock = next(i for i, s in enumerate(seen) if "FOR UPDATE" in s.upper())
    first_membership_read = next(
        (i for i, s in enumerate(seen) if "communication_needs_items" in s), len(seen)
    )
    assert first_lock < first_membership_read


async def test_removing_a_line_edits_the_draft_it_was_asked_about(db_session: AsyncSession) -> None:
    """LP-832 REVIEW — "the open draft" stopped naming one row, and this function still said it.

    `remove_need_from_draft` resolved its target with `get_open_draft`, which was exactly one row
    while `uq_communications_open_draft` existed and is now merely the NEWEST of several. With two
    drafts on a file, removing a line from the OLDER one silently edited the newer.

    Nothing would have caught it: the function has no caller in `app/` today. LP-831 builds the
    drafts list, and this is the function it will reach for — which is why the id is a parameter now
    rather than after somebody reports a line vanishing from the wrong email.

    Both halves asserted. The older draft loses the line, and the newer keeps it — either alone
    passes on a function that edited nothing at all.
    """
    loan_file, actor = await _file_and_actor(db_session)
    first = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    second = NeedsItem(
        loan_file_id=loan_file.id,
        title="Pay stubs",
        needs_type="pay_stub",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add_all([first, second])
    await db_session.flush()

    older = (
        await add_needs_to_draft(
            db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
        )
    ).draft
    newer = (
        await add_needs_to_draft(
            db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
        )
    ).draft
    assert older is not None and newer is not None and older.id != newer.id
    assert "Bank statements" in (older.body or "")  # the control: it is there to begin with
    assert "Bank statements" in (newer.body or "")

    edited = await remove_need_from_draft(
        db_session,
        loan_file=loan_file,
        needs_item_id=first.id,
        communication_id=older.id,
    )

    assert edited is not None and edited.id == older.id
    await db_session.refresh(older)
    await db_session.refresh(newer)
    assert "Bank statements" not in (older.body or ""), "the draft asked about was not edited"
    assert "Bank statements" in (newer.body or ""), "a different draft was edited instead"


async def test_removing_from_another_files_draft_is_refused(db_session: AsyncSession) -> None:
    """The same answer a missing draft gets. A draft on another file must not be distinguishable
    from one that does not exist, and it must certainly not be editable."""
    loan_file, _actor = await _file_and_actor(db_session)
    other_file, other_actor = await _file_and_actor(db_session)
    need = NeedsItem(
        loan_file_id=other_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add(need)
    await db_session.flush()
    theirs = (
        await add_needs_to_draft(
            db_session, loan_file=other_file, needs=[need], actor_user_id=other_actor
        )
    ).draft
    assert theirs is not None

    assert (
        await remove_need_from_draft(
            db_session,
            loan_file=loan_file,
            needs_item_id=need.id,
            communication_id=theirs.id,
        )
        is None
    )
    await db_session.refresh(theirs)
    assert "Bank statements" in (theirs.body or ""), "another file's draft was edited"


# --------------------------------------------------------------------------------------------- #
# LP-839 — the processor's note, which reached nobody
# --------------------------------------------------------------------------------------------- #
async def test_the_note_reaches_the_borrower(db_session: AsyncSession) -> None:
    """THE TEXTAREA WROTE TO A COLUMN AND STOPPED. The request form asks for something to add,
    stores it in `NeedsItem.description`, and `_document_line` rendered the catalog's guidance or the
    title — so "the March one specifically, not February" reached nobody."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    need.description = "The March one specifically, not February."
    await db_session.flush()

    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert update.draft is not None
    assert "The March one specifically, not February." in update.draft.body


async def test_a_note_survives_the_next_request(db_session: AsyncSession) -> None:
    """WHY IT LIVES ON THE NEED AND NOT ON THE DRAFT. The body is rewritten from the needs on every
    add and remove, so a note anywhere else would be wiped by the next request — LP-834's problem,
    with a cheaper answer available because a note already has a row to live on."""
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    first.description = "The March one specifically."
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    await db_session.flush()

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[first], actor_user_id=actor)
    after = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
    )

    assert after.draft is not None
    assert "The March one specifically." in after.draft.body


async def test_a_draft_with_no_notes_reads_as_before(db_session: AsyncSession) -> None:
    """THE CONTROL. A renderer that appended something for every need would put a blank line under
    each document on every file that has never used the field."""
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")

    update = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert update.draft is not None
    assert "\n  \n" not in update.draft.body
    assert "Bank statement" in update.draft.body or "bank statement" in update.draft.body.lower()


def test_a_note_changes_the_composition_key() -> None:
    """AND THE MODEL MUST BE ASKED AGAIN. `cache_key` is a digest of the facts payload: without the
    notes in it, adding one leaves the key unchanged, `_cached_prose` hits, and no composition runs —
    the framing would stay written for a request that has since changed.

    Compared as keys rather than as prose, because the claim is about the cache and not about what
    the model would say.
    """
    from app.ai.email_draft import DraftFacts

    plain = DraftFacts(
        borrower_first_name="the borrower",
        loan_reference="LF-1",
        requested_labels=("Bank statement",),
    )
    annotated = DraftFacts(
        borrower_first_name="the borrower",
        loan_reference="LF-1",
        requested_labels=("Bank statement",),
        requested_notes=("The March one specifically.",),
    )

    assert plain.cache_key() != annotated.cache_key()


def test_a_number_in_a_note_does_not_license_the_model_to_state_one() -> None:
    """THE GUARD THE PREVIOUS CHANGE NEARLY OPENED. Putting notes in the facts put them in
    `to_json()`, which is what licenses a number — so "the one showing the $10,000 deposit" would
    have licensed "10,000" anywhere in the output. LP-597 and LP-613 each cost a shipped defect to
    find; a note is the same shape of thing as a label and joins the unlicensed set."""
    from app.ai.email_draft import DraftComposition, DraftFacts, rejection_reason

    facts = DraftFacts(
        borrower_first_name="the borrower",
        loan_reference="LF-1",
        requested_labels=("Bank statement",),
        requested_notes=("The one showing the $10,000 deposit.",),
    )
    composition = DraftComposition(
        opening="We are working through your file.",
        bridge="Here is what we still need:",
        # NO CURRENCY SYMBOL, deliberately. `$10,000` also trips `states_a_money_amount`, so an
        # `is not None` assertion passed whether or not the note was licensed — it was measuring a
        # different guard. A bare number reaches the licensing check and nothing else.
        closing="Please include the 10,000 deposit.",
    )

    # THE SPECIFIC REASON, not merely "rejected": that is what makes this about licensing.
    assert rejection_reason(facts, composition) == "unsupported_numbers:1"


async def test_a_processor_owned_document_gets_no_draft_at_all(db_session: AsyncSession) -> None:
    """LP-841 — THE ONE PARTY THAT IS NOT A RECIPIENT.

    Routing every requested document to its responsible party's draft is the whole ticket, and the
    catalog's 24 processor-owned types are the exception: a tax transcript is ordered by the
    processor from the IRS, so a draft addressed to the processor would be an email a person writes
    to themselves. It stays a needs item and nothing else.

    THE POSITIVE CONTROL IS IN THE SAME CALL. Without it this passes on a build that creates no
    drafts for anybody — which is the state this ticket exists to fix, and it would read as green.
    """
    loan_file, actor = await _file_and_actor(db_session)
    mine = await _need(db_session, loan_file, title="Tax transcripts", needs_type="tax_transcript")
    theirs = await _need(db_session, loan_file, title="Credit report", needs_type="credit_report")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[mine, theirs], actor_user_id=actor
    )

    by_party = {p.party.value: p for p in result.parties}
    # The processor's half is REPORTED — the caller has to be able to say where the request went —
    # and carries no draft. Asserting its absence from the list instead would pass on a build that
    # silently dropped it, which is the old discard behaviour wearing this ticket's name.
    assert by_party["processor"].draft is None, "an email the processor writes to themselves"
    # The control: the lender's half of the same call did produce one.
    assert by_party["lender"].draft is not None


def test_every_party_draft_names_a_template_that_exists() -> None:
    """LP-843 — ADR-401'S PIN, WHICH LP-841 HAD QUIETLY BROKEN.

    A stored `template_key` + `template_version` must resolve to the exact words that were sent;
    that is the entire purpose of the pin. LP-841 filed a lender draft under
    `document_request_lender` so the communication page could bucket it, and NO SUCH TEMPLATE HAS
    EVER EXISTED — so the pair named nothing, and a row that resolves to nothing cannot be told
    apart from one that resolves to something.

    The key means "what rendered this" again. The bucket moved to `Communication.party`, which is
    what it needed to be all along: five parties can share one professional template and still need
    five tabs.
    """
    from app.communications.templates import TEMPLATES
    from app.documents.catalog import ResponsibleParty
    from app.services.email_draft import draft_template_key

    registered = {key.value for key in TEMPLATES}
    for party in ResponsibleParty:
        assert draft_template_key(party) in registered, party

    # The borrower's historical key is the one thing that must NOT have moved: it is on every message
    # this product has ever sent, and renaming it orphans every audit row that names it.
    assert draft_template_key(ResponsibleParty.BORROWER) == "initial_documentation_request"


def test_the_old_per_party_keys_still_resolve_for_drafts_written_before_the_column() -> None:
    """A draft open across the deploy keeps LP-841's key and has no stored party until the backfill.

    `party_for_draft_template` exists for exactly those rows. It cannot answer for a modern one —
    five parties share `document_request_third_party` — and that is the honest answer rather than a
    gap: the caller reads the column.
    """
    from app.documents.catalog import ResponsibleParty
    from app.services.email_draft import party_for_draft_template

    assert party_for_draft_template("document_request_lender") is ResponsibleParty.LENDER
    assert party_for_draft_template("document_request_title") is ResponsibleParty.TITLE
    assert party_for_draft_template("initial_documentation_request") is ResponsibleParty.BORROWER
    # The shared key names no single party, and saying so is the point.
    assert party_for_draft_template("document_request_third_party") is None
    assert party_for_draft_template("password_reset") is None
    assert party_for_draft_template(None) is None


async def test_the_ask_says_what_the_document_must_establish(db_session: AsyncSession) -> None:
    """LP-842 — THE REASON THAT REACHED NOBODY.

    The catalog says where to get a homeowner's policy. Only the rule that fired knows this file
    needs one showing the dwelling settled on a replacement-cost basis. Reported from the other end:
    the borrower sends another declarations page, it does not state the loss-settlement basis
    (because the first one did not either — that IS the finding), and the file is a round trip older
    and no closer.
    """
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    need.outbound_ask = "Please include every page, including any that are intentionally blank."
    await db_session.flush()

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    body = result.borrower.draft.body or ""
    assert "including any that are intentionally blank" in body
    # The control: the document itself is still named. An ask that REPLACED the document line would
    # satisfy the line above and tell the borrower nothing about what to send.
    assert "statement" in body.lower()


async def test_a_dollar_sign_in_an_ask_survives_as_a_literal(db_session: AsyncSession) -> None:
    """LP-823's trap, reachable through a new door.

    The stored draft body keeps `$borrower_first_name` and friends UNRESOLVED — that is the whole
    point of the deferred-placeholder design — so something later runs `Template.substitute` over
    the stored text. Rule authors write about money, so an ask will eventually contain a `$`, and
    `substitute` is strict: an unknown `$word` raises, mid-send, on a draft a processor is watching.

    `$2,000` is the shape that is actually safe (a digit cannot start an identifier) and `$2,000 in
    deposits` is not the test. `$AMOUNT` is: it looks exactly like a placeholder.
    """
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    need.outbound_ask = "Show the source of any deposit over $AMOUNT, and any $2,000 transfer."
    await db_session.flush()

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    body = result.borrower.draft.body or ""
    assert "$AMOUNT" in body, "a literal dollar sign did not survive composition"
    assert "$2,000" in body

    # AND THROUGH THE SECOND PASS, which is where it would actually die. Composition stores the body
    # with `$borrower_first_name` still in it; `finalise_draft_body` resolves that at read and send.
    # Asserting only on the stored body would pass against a build that raises the moment anybody
    # opens the draft — the failure is downstream of where this need was written.
    from app.services.email_draft import finalise_draft_body

    final = finalise_draft_body(body, borrower_first_name="Felicia", processor_name="Geet")
    assert "$AMOUNT" in final
    assert "$2,000" in final
    # The control: the REAL placeholders did resolve, so this is not passing because nothing ran.
    assert "Felicia" in final
    assert "$borrower_first_name" not in final


async def test_a_lender_is_not_told_it_is_their_loan_file(db_session: AsyncSession) -> None:
    """LP-843 — THE REPORTED DEFECT, in the words that were reported.

    "Current email message says 'We are working through your loan file and there are a few documents
    we still need from you' to send an email to Employer. Also to send email to lender... These look
    like processor sending email to borrower. It is actually borrower's file."

    LP-841 filed a lender draft under `document_request_lender` and no such template existed, so
    `render_draft_body` rendered the borrower's file for everybody.
    """
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Credit report", needs_type="credit_report")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    lender = next(p for p in result.parties if p.party.value == "lender")
    body = (lender.draft.body or "").lower()
    assert "your loan file" not in body
    assert "we still need from you" not in body
    assert "$borrower_first_name" not in (lender.draft.body or "")
    # The control: it is still a document request that names the document.
    assert "credit report" in body


async def test_no_third_party_email_carries_the_file_inbox_address(
    db_session: AsyncSession,
) -> None:
    """LP-843 — THE SECURITY DECISION, asserted rather than described.

    The file inbox address is a bearer capability (ADR-397): anyone holding it can post documents
    into this loan file and nothing authenticates the sender. The borrower's template carries it by
    design. A third party's must not — handing an employer or a title company write access to a
    borrower's file is a capability we cannot withdraw once the mail has left, and the person who
    carries the consequence is not the person we gave it to.

    ASSERTED ON THE RENDERED BODY, not on the template's declared variables. A template that does not
    declare `inbox_address` could still be handed the address through any other slot — the
    identification block is built from file data and is exactly the kind of place it would arrive.
    """
    loan_file, actor = await _file_and_actor(db_session)
    inbox = loan_file.get_inbox_address()
    assert inbox, "the fixture has no inbox address; this test would pass on nothing"

    appraisal = await _need(db_session, loan_file, title="Appraisal", needs_type="appraisal")
    voe = await _need(db_session, loan_file, title="VOE", needs_type="voe")
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[appraisal, voe], actor_user_id=actor
    )

    seen = 0
    for party_draft in result.parties:
        if party_draft.draft is None or party_draft.party.value == "borrower":
            continue
        seen += 1
        assert inbox not in (party_draft.draft.body or ""), party_draft.party
        assert inbox not in (party_draft.draft.subject or ""), party_draft.party
    # THE CONTROL. Every assertion above is satisfied when no third-party draft was built at all,
    # which is the state before LP-841 and would read as green.
    assert seen >= 2, "no third-party drafts were produced; the loop asserted nothing"


async def test_a_third_party_can_find_the_loan_in_their_own_system(
    db_session: AsyncSession,
) -> None:
    """LP-843 — `display_id` IS OURS.

    A lender files by borrower name and property address; "LF-XMB2" names nothing they can search,
    and an email that offers only that is one they cannot act on. The reference stays, because it is
    what they quote back to us.
    """
    from app.models.borrower import Borrower
    from app.models.property import Property

    loan_file, actor = await _file_and_actor(db_session)
    db_session.add(Borrower(loan_file_id=loan_file.id, first_name="Felicia", last_name="Vance"))
    db_session.add(
        Property(
            loan_file_id=loan_file.id,
            address_line="41 Bellweather Lane",
            city="Fresno",
            state="CA",
            postal_code="93720",
        )
    )
    await db_session.flush()
    need = await _need(db_session, loan_file, title="Appraisal", needs_type="appraisal")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    body = next(p for p in result.parties if p.party.value == "lender").draft.body or ""
    assert loan_file.display_id in body, "the reference they quote back to us"
    # The two things a lender actually files by. Our display_id names nothing in their system.
    assert "Felicia Vance" in body
    assert "41 Bellweather Lane" in body


async def test_the_identification_block_omits_what_the_file_does_not_have(
    db_session: AsyncSession,
) -> None:
    """A purchase file often has no address for weeks — `Property.address_line` is nullable exactly
    for that — so this is the ordinary case, not the degraded one.

    "Property:" with nothing after it tells a reader the address is missing from our system, which is
    true and useless. The line does not appear at all.
    """
    loan_file, actor = await _file_and_actor(db_session)
    need = await _need(db_session, loan_file, title="Appraisal", needs_type="appraisal")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    body = next(p for p in result.parties if p.party.value == "lender").draft.body or ""
    assert "Property:" not in body
    assert "Borrower:" not in body
    # The control: the block still rendered, and still carries the one thing this file does have.
    assert loan_file.display_id in body


async def test_an_employer_is_asked_for_a_verification_not_for_their_loan_file(
    db_session: AsyncSession,
) -> None:
    """LP-843 — THE EMPLOYER GETS ITS OWN VOICE, and the reason it is not the third-party one.

    A VOE is a form to COMPLETE, not a document to retrieve. An employer who sends back a letter
    confirming employment and nothing else costs another round trip, so the email names the fields a
    complete verification carries. It also spells out "Verification of Employment": "VOE" is our
    jargon, and the person opening this email works in payroll.
    """
    from app.models.borrower import Borrower

    loan_file, actor = await _file_and_actor(db_session)
    db_session.add(Borrower(loan_file_id=loan_file.id, first_name="Felicia", last_name="Vance"))
    await db_session.flush()
    need = await _need(db_session, loan_file, title="VOE", needs_type="voe")

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    draft = next(p for p in result.parties if p.party.value == "employer").draft
    body = draft.body or ""
    assert "Verification of Employment" in body, "spelled out, not our acronym"
    assert "Felicia Vance" in body, "payroll needs to know which employee"
    assert "Year-to-date earnings" in body, "the fields that make one round trip enough"
    # NOT the borrower's words, and not the third party's either.
    assert "your loan file" not in body.lower()
    assert "the following from you" not in body.lower()


async def test_a_draft_left_by_the_old_code_is_found_rather_than_forked(
    db_session: AsyncSession,
) -> None:
    """LP-843 REVIEW — THE DEPLOY WINDOW, which the compatibility arm was not covering.

    `_open_drafts_stmt` matches `party == X OR (party IS NULL AND template_key IN <legacy keys>)`. The
    second arm existed for exactly one row: a draft created by the OLD code AFTER the migration ran,
    which has no `party` and an LP-841 key like `document_request_lender`.

    It compared against `draft_template_key(party)` — this ticket's value — so for a lender it looked
    for `document_request_third_party` among rows carrying `document_request_lender`. Measured across
    all eight parties: only `employer` matched, and only because its new key equals its old one. Six
    of eight covered nothing, so such a draft was invisible and the next request minted a second one —
    the fork the arm was written to prevent.

    Simulated by writing the row the old code would have written. The control is the second half: a
    row whose key belongs to a DIFFERENT party must not be adopted, or the arm would collapse every
    unlabelled draft into whichever party asked first.
    """
    loan_file, _actor = await _file_and_actor(db_session)
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.DRAFT,
            # What LP-841's code wrote: the per-party key, and no `party` column to set.
            template_key="document_request_lender",
            template_version="v1",
            party=None,
        )
    )
    await db_session.flush()

    found = await open_drafts(db_session, loan_file_id=loan_file.id, party=ResponsibleParty.LENDER)

    assert [d.template_key for d in found] == ["document_request_lender"], (
        "a draft the old code left behind is invisible — the next request would fork it"
    )
    # THE CONTROL: it is the LENDER's key, and title must not adopt it.
    assert (
        await open_drafts(db_session, loan_file_id=loan_file.id, party=ResponsibleParty.TITLE) == []
    ), "an unlabelled draft was adopted by the wrong party"


async def test_a_borrower_is_told_where_to_get_each_document(db_session: AsyncSession) -> None:
    """LP-846 — WHAT A BORROWER READS, asserted from the request rather than from a layer.

    Reported: "it does not have section where to get each document."

    Eleven communication tickets have each asserted at one layer — the catalog has guidance, the
    block renderer formats it, the template interpolates it, the HTML renderer displays it — and
    nearly every defect since has lived in the SEAM between two of them. This one did: the sections
    were generated correctly and the HTML renderer flattened them.

    So this test spans the whole backend half in the terms the report used: ask for a document, and
    the words a borrower receives name it AND say where to get it AND what we need to see. It has no
    business knowing which function produced which line.
    """
    loan_file, actor = await _file_and_actor(db_session)
    licence = await _need(
        db_session, loan_file, title="drivers license", needs_type="drivers_license"
    )
    insurance = await _need(
        db_session, loan_file, title="homeowners insurance", needs_type="homeowners_insurance"
    )

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[licence, insurance], actor_user_id=actor
    )

    body = result.borrower.draft.body or ""
    # Both documents, by the name a borrower would recognise rather than by slug.
    assert "Driver's licence" in body
    assert "Homeowner's insurance" in body
    # AND THE GUIDANCE, which is the reported gap. Two of them, so this cannot pass on one document
    # happening to carry a section while the other does not.
    assert body.count("Where to get it:") == 2, body
    assert body.count("What we need to see:") == 2
    # The slug must never reach a borrower's inbox.
    assert "drivers_license" not in body
    assert "homeowners_insurance" not in body
