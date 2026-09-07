"""LP-820 — the seven parties who are not the borrower, and whether we can reach any of them.

THE FIRST TEST IS A MEASUREMENT, not an assertion about behaviour. `b7`'s question going in was the
right one: *which parties have a REACHABLE address today?* — because a per-party clock without a
per-party address is a reminder nobody can act on.

Counted before anything was built: of 166 document types, 113 go to the borrower, 24 to the
processor (who orders them and needs no request), 16 to the lender — and 13 to title, agent, CPA,
insurer and employer, of which only `title` and `agent` had even a ROLE on `loan_file_participants`
and neither had a writer. `test_the_catalog_still_sorts_to_parties_this_module_can_reach` is that
measurement pinned, so a document type re-sorted to a party with no mapping fails here rather than
silently becoming unaskable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.documents.catalog import ResponsibleParty, get_guidance
from app.models import Company, LoanProgram, User, UserRole
from app.models.communication import Communication, CommunicationStatus
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
from app.models.needs_item import NeedsItem, NeedsItemOrigin, NeedsItemStatus
from app.services.party_requests import (
    PARTY_ROLE,
    add_participant,
    build_party_draft,
    open_requests,
    party_for,
    remove_participant,
    template_key_for,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company_and_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


async def _actor(db: AsyncSession, company) -> User:
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
    return user


def _type_for(party: ResponsibleParty) -> str:
    """A real catalog slug that sorts to ``party``. Raises if none does, which is the point."""
    from app.documents.catalog import _RESPONSIBLE_PARTY

    for slug, assigned in _RESPONSIBLE_PARTY.items():
        if assigned is party:
            return slug
    raise AssertionError(f"no document type sorts to {party}")


async def _need(
    db: AsyncSession, loan_file, *, needs_type: str | None, title: str = "A document"
) -> NeedsItem:
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title=title,
        needs_type=needs_type,
        origin=NeedsItemOrigin.TEMPLATE,
        status=NeedsItemStatus.PENDING,
    )
    db.add(need)
    await db.flush()
    return need


# --------------------------------------------------------------------------------------------- #
# The measurement
# --------------------------------------------------------------------------------------------- #
def test_the_catalog_still_sorts_to_parties_this_module_can_reach() -> None:
    """EVERY PARTY THE CATALOG USES HAS A ROLE, or is the processor, who is asked nothing.

    Pinned rather than assumed: a document type re-sorted to a party with no mapping would become
    unaskable, and the failure would be silent — the need would simply never appear in any group.
    """
    from app.documents.catalog import _RESPONSIBLE_PARTY

    used = set(_RESPONSIBLE_PARTY.values())

    assert ResponsibleParty.PROCESSOR in used, (
        "the processor default is what makes the mapping's omission of it meaningful"
    )
    unmapped = used - set(PARTY_ROLE) - {ResponsibleParty.PROCESSOR}
    assert not unmapped, (
        f"these parties have no participant role: {sorted(p.value for p in unmapped)}"
    )


def test_the_processor_is_deliberately_unmapped() -> None:
    """A party that cannot be written to is different from one that MUST NOT be. Mapping the
    processor to any role would turn "we fetch this" into "we email somebody about it"."""
    assert ResponsibleParty.PROCESSOR not in PARTY_ROLE


def test_every_party_gets_its_own_template_key() -> None:
    """The one-open-draft index is `(loan_file_id, template_key)`. A shared key would make a title
    request and a CPA request collide, and the second would be refused by the database with an
    error about a draft the processor cannot see."""
    keys = {template_key_for(party) for party in PARTY_ROLE}

    assert len(keys) == len(PARTY_ROLE)


# --------------------------------------------------------------------------------------------- #
# Grouping, including the parties we cannot reach
# --------------------------------------------------------------------------------------------- #
async def test_an_unreachable_party_is_listed_rather_than_dropped(
    db_session: AsyncSession,
) -> None:
    """THE POINT OF THE TICKET. A screen showing only what it can send presents a file with five
    outstanding title documents as having nothing to do — which is the build plan's "sit at PENDING
    forever, invisible to LP-814", rendered."""
    _company, loan_file = await _company_and_file(db_session, slug="unreachable")
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))

    requests = await open_requests(db_session, loan_file=loan_file)

    title = next(r for r in requests if r.party is ResponsibleParty.TITLE)
    assert title.reachable is False
    assert title.address is None
    assert len(title.needs) == 1


async def test_adding_an_address_makes_a_party_reachable(db_session: AsyncSession) -> None:
    """THE CONTROL. Without it, "unreachable" passes against a module that can never reach anybody."""
    _company, loan_file = await _company_and_file(db_session, slug="reachable")
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))

    await add_participant(
        db_session,
        loan_file=loan_file,
        role=ParticipantRole.TITLE,
        email="Closings@Title.Example",
        name="Acme Title",
    )

    title = next(
        r
        for r in await open_requests(db_session, loan_file=loan_file)
        if r.party is ResponsibleParty.TITLE
    )
    assert title.reachable is True
    # Normalised, so it matches the address the participant lookup would recognise on the way back.
    assert title.address == "closings@title.example"
    assert title.name == "Acme Title"


async def test_processor_needs_are_not_listed_at_all(db_session: AsyncSession) -> None:
    """Nobody is emailed about them. Showing them with "no address" would read as a gap to fill."""
    _company, loan_file = await _company_and_file(db_session, slug="proc")
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.PROCESSOR))

    requests = await open_requests(db_session, loan_file=loan_file)

    assert ResponsibleParty.PROCESSOR not in {r.party for r in requests}


async def test_an_untyped_need_is_the_borrowers(db_session: AsyncSession) -> None:
    """Matching `_is_borrower_facing` exactly: the need was created by a processor clicking "request
    documents", so a person has already decided to ask the borrower. LP-800's processor default
    protects against a document nobody classified; it must not veto a request somebody made."""
    _company, loan_file = await _company_and_file(db_session, slug="untyped")
    need = await _need(db_session, loan_file, needs_type=None)

    assert party_for(need) is ResponsibleParty.BORROWER


async def test_a_satisfied_need_is_not_outstanding(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="satisfied")
    need = await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))
    need.status = NeedsItemStatus.RECEIVED
    await db_session.flush()

    assert await open_requests(db_session, loan_file=loan_file) == []


async def test_a_rejected_need_is_still_outstanding(db_session: AsyncSession) -> None:
    """REJECTED means a document arrived and failed — the need is still open, with a reason. Leaving
    it out would drop exactly the re-request a processor most needs to make."""
    _company, loan_file = await _company_and_file(db_session, slug="rejected")
    need = await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))
    need.status = NeedsItemStatus.REJECTED
    await db_session.flush()

    assert len(await open_requests(db_session, loan_file=loan_file)) == 1


async def test_reachable_parties_sort_first(db_session: AsyncSession) -> None:
    """A processor can act on the top of the list; the ones below are a different job — find an
    address — rather than a failed one."""
    _company, loan_file = await _company_and_file(db_session, slug="sorted")
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.CPA))
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.CPA, email="cpa@example.com"
    )

    requests = await open_requests(db_session, loan_file=loan_file)

    assert [r.reachable for r in requests] == [True, False]


# --------------------------------------------------------------------------------------------- #
# The address book
# --------------------------------------------------------------------------------------------- #
async def test_an_address_is_never_trusted(db_session: AsyncSession) -> None:
    """LP-805's rule, here too: an address a processor typed is somebody we can write TO, not
    somebody whose attachments should bypass review. §2.3's default is quarantine."""
    _company, loan_file = await _company_and_file(db_session, slug="untrusted")

    participant = await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="t@example.com"
    )

    assert participant.is_trusted_sender is False


async def test_correcting_a_typo_replaces_rather_than_accumulates(
    db_session: AsyncSession,
) -> None:
    """ "First wins per role" is what picks the address, so a stale row left beside a corrected one
    would be the one that gets written to."""
    _company, loan_file = await _company_and_file(db_session, slug="typo")
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))
    first = await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="wrong@example.com"
    )
    await remove_participant(db_session, loan_file=loan_file, participant_id=first.id)
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="right@example.com"
    )

    title = next(
        r
        for r in await open_requests(db_session, loan_file=loan_file)
        if r.party is ResponsibleParty.TITLE
    )
    assert title.address == "right@example.com"


async def test_adding_the_same_address_twice_keeps_one_row(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="idempotent")
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.CPA, email="a@example.com"
    )
    await add_participant(
        db_session,
        loan_file=loan_file,
        role=ParticipantRole.CPA,
        email="A@Example.com",
        name="Books LLP",
    )

    rows = (
        (
            await db_session.execute(
                select(LoanFileParticipant).where(
                    LoanFileParticipant.loan_file_id == loan_file.id,
                    LoanFileParticipant.role == ParticipantRole.CPA,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].name == "Books LLP"


async def test_another_files_address_cannot_be_removed(db_session: AsyncSession) -> None:
    """The route proves the caller owns the FILE; the participant id is a path parameter anybody can
    type. A REAL address on a real other file."""
    _theirs, their_file = await _company_and_file(db_session, slug="addr-theirs")
    _mine, my_file = await _company_and_file(db_session, slug="addr-mine")
    theirs = await add_participant(
        db_session, loan_file=their_file, role=ParticipantRole.TITLE, email="t@example.com"
    )

    assert (
        await remove_participant(db_session, loan_file=my_file, participant_id=theirs.id) is False
    )
    assert theirs.deleted_at is None


async def test_a_malformed_address_is_refused(db_session: AsyncSession) -> None:
    _company, loan_file = await _company_and_file(db_session, slug="malformed")

    with pytest.raises(ValueError):
        await add_participant(
            db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="not-an-address"
        )


# --------------------------------------------------------------------------------------------- #
# The draft, and the clock it exists to start
# --------------------------------------------------------------------------------------------- #
async def test_a_party_draft_is_a_real_draft_on_the_existing_send_path(
    db_session: AsyncSession,
) -> None:
    """IT CARRIES THE NEEDS JOIN, which is the whole reason it is a draft rather than a mailer:
    LP-811a's `send_draft` calls `request_needs_item` on everything in that join, and that call is
    what stamps `requested_at` and starts LP-814's clock. The build plan's complaint was that these
    needs never get the stamp."""
    from app.services.email_draft import _needs_in_draft

    company, loan_file = await _company_and_file(db_session, slug="draft")
    actor = await _actor(db_session, company)
    need = await _need(
        db_session,
        loan_file,
        needs_type=_type_for(ResponsibleParty.TITLE),
        title="Title commitment",
    )
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="t@title.example"
    )

    draft = await build_party_draft(
        db_session,
        loan_file=loan_file,
        party=ResponsibleParty.TITLE,
        actor_user_id=actor.id,
    )

    assert draft.status is CommunicationStatus.DRAFT
    assert draft.recipient == "t@title.example"
    assert draft.template_key == template_key_for(ResponsibleParty.TITLE)
    assert [item.id for item in await _needs_in_draft(db_session, draft=draft)] == [need.id]


async def test_two_parties_can_have_open_drafts_at_once(db_session: AsyncSession) -> None:
    """A CLAIM ABOUT THE INDEX, asserted by writing the rows. `(loan_file_id, template_key)` is
    unique among open drafts, so a shared key would make the second party's request an
    IntegrityError a processor cannot explain."""
    company, loan_file = await _company_and_file(db_session, slug="twoparties")
    actor = await _actor(db_session, company)
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.CPA))
    for role in (ParticipantRole.TITLE, ParticipantRole.CPA):
        await add_participant(
            db_session, loan_file=loan_file, role=role, email=f"{role.value}@example.com"
        )

    await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )
    await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.CPA, actor_user_id=actor.id
    )

    drafts = (
        (
            await db_session.execute(
                select(Communication).where(
                    Communication.loan_file_id == loan_file.id,
                    Communication.status == CommunicationStatus.DRAFT,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(drafts) == 2


async def test_building_twice_accumulates_rather_than_duplicating(
    db_session: AsyncSession,
) -> None:
    company, loan_file = await _company_and_file(db_session, slug="accumulate")
    actor = await _actor(db_session, company)
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE), title="One")
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="t@example.com"
    )
    first = await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE), title="Two")

    second = await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )

    from app.services.email_draft import _needs_in_draft

    assert second.id == first.id
    assert len(await _needs_in_draft(db_session, draft=second)) == 2


async def test_a_corrected_address_reaches_an_open_draft(db_session: AsyncSession) -> None:
    """A processor who fixed a typo between opening the draft and sending it must not send to the
    old one — and the draft is the thing they press send on."""
    company, loan_file = await _company_and_file(db_session, slug="refresh")
    actor = await _actor(db_session, company)
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))
    wrong = await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="wrong@example.com"
    )
    await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )
    await remove_participant(db_session, loan_file=loan_file, participant_id=wrong.id)
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="right@example.com"
    )

    draft = await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )

    assert draft.recipient == "right@example.com"


async def test_a_party_with_no_address_is_refused_rather_than_drafted(
    db_session: AsyncSession,
) -> None:
    """A draft addressed to nobody is a message that will never be sent and a clock that will never
    start — the exact state this ticket exists to end."""
    company, loan_file = await _company_and_file(db_session, slug="noaddress")
    actor = await _actor(db_session, company)
    await _need(db_session, loan_file, needs_type=_type_for(ResponsibleParty.TITLE))

    with pytest.raises(ValueError, match="no address"):
        await build_party_draft(
            db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
        )


async def test_the_processor_cannot_be_drafted_to(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="nodraft")
    actor = await _actor(db_session, company)

    with pytest.raises(ValueError, match="nobody to send"):
        await build_party_draft(
            db_session,
            loan_file=loan_file,
            party=ResponsibleParty.PROCESSOR,
            actor_user_id=actor.id,
        )


async def test_a_party_with_nothing_outstanding_is_refused(db_session: AsyncSession) -> None:
    company, loan_file = await _company_and_file(db_session, slug="nothing")
    actor = await _actor(db_session, company)
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="t@example.com"
    )

    with pytest.raises(ValueError, match="nothing outstanding"):
        await build_party_draft(
            db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
        )


async def test_a_sibling_files_needs_are_not_in_this_ones_groups(
    db_session: AsyncSession,
) -> None:
    """SAME COMPANY, TWO FILES. A company-scoped query would pass every cross-tenant test while
    asking one borrower's title company for another borrower's documents."""
    from app.services.loan_files import create_loan_file

    company, mine = await _company_and_file(db_session, slug="sibling")
    theirs = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    await _need(db_session, theirs, needs_type=_type_for(ResponsibleParty.TITLE))

    assert await open_requests(db_session, loan_file=mine) == []
    assert len(await open_requests(db_session, loan_file=theirs)) == 1


def test_no_non_borrower_type_has_catalog_guidance_today() -> None:
    """A MEASUREMENT, PINNED, because the ticket's body limitation depends on it.

    LP-800 wrote full entries for the borrower-facing types and party-only for the rest. Counted:
    28 of 113 borrower types have a `borrower_label`, and **none** of the 53 that go to any other
    party does. So a party request's body is the needs' TITLES with no retrieval instructions —
    which is the honest state, not a bug: "Title commitment" needs no explanation to a title company.

    Pinned so that the day somebody writes guidance for a title type, this fails and the ticket's
    claim gets re-read rather than quietly becoming false.
    """
    from app.documents.catalog import _RESPONSIBLE_PARTY

    with_guidance = {
        party
        for slug, party in _RESPONSIBLE_PARTY.items()
        if get_guidance(slug).borrower_label is not None
    }

    assert with_guidance == {ResponsibleParty.BORROWER}


async def test_the_draft_body_names_what_is_being_asked_for(
    db_session: AsyncSession,
) -> None:
    """The body is the same renderer the borrower request uses. For a non-borrower party the catalog
    has no guidance (see the test above), so `_document_line`'s documented fallback applies and the
    need's TITLE is what appears — which is what a title company needs to see."""
    company, loan_file = await _company_and_file(db_session, slug="body")
    actor = await _actor(db_session, company)
    await _need(
        db_session,
        loan_file,
        needs_type=_type_for(ResponsibleParty.TITLE),
        title="Title commitment",
    )
    await add_participant(
        db_session, loan_file=loan_file, role=ParticipantRole.TITLE, email="t@example.com"
    )

    draft = await build_party_draft(
        db_session, loan_file=loan_file, party=ResponsibleParty.TITLE, actor_user_id=actor.id
    )

    assert draft.body
    assert "Title commitment" in draft.body
