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
from app.models import Company, LoanProgram
from app.models.communication import Communication, CommunicationStatus
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import (
    DRAFT_TEMPLATE,
    add_needs_to_draft,
    finalise_draft_body,
    get_open_draft,
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
async def test_a_second_request_joins_the_first_draft(db_session: AsyncSession) -> None:
    """The whole ticket. Four requests over two days must be one email, not four."""
    loan_file, actor = await _file_and_actor(db_session)
    first = await _need(db_session, loan_file, title="Bank statements", needs_type="bank_statement")
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")

    one = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[first], actor_user_id=actor
    )
    two = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[second], actor_user_id=actor
    )

    assert one.draft.id == two.draft.id
    count = await db_session.scalar(
        select(func.count())
        .select_from(Communication)
        .where(Communication.loan_file_id == loan_file.id)
    )
    assert count == 1
    assert "Bank statements" in two.draft.body
    assert "Pay stubs" in two.draft.body


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

    assert result.added == (theirs.id,)
    assert result.skipped_not_borrower == (not_theirs.id,)
    assert "Appraisal" not in result.draft.body


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


async def test_a_second_open_draft_is_refused_by_the_database(db_session: AsyncSession) -> None:
    """The service looks before it creates, but a look-then-create races. The partial unique index is
    what makes "the open draft" true under concurrency rather than merely usual."""
    from app.models.communication import CommunicationDirection
    from sqlalchemy.exc import IntegrityError

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
    with pytest.raises(IntegrityError):
        await db_session.flush()


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
