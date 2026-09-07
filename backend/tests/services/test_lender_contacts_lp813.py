"""LP-813 — the named underwriter, and the one place two ownership chains meet.

A loan file is owned by a company. A contact is owned by a lender, which is owned by a company.
`loan_files.underwriter_contact_id` is the only column in the schema where a file points at a row
reached through a different ownership chain — so it is the only place those two companies can
disagree, and nothing but `assign_underwriter` proves they do not.

So the cross-tenant tests here build TWO companies, TWO lenders and a REAL contact at the other
one. The same rule the last six tickets have been teaching: a fixture that cannot reach the
dangerous case looks exactly like a system that refuses it.

AND THERE IS A SECOND AXIS, inside one company: the contact must be at the file's OWN lender.
Same-company is not enough — "submitted to Sun-West, underwriter at UWM" is a file that reads as
complete and is wrong in the one field a processor acts on.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from app.models.lender import Lender
from app.models.lender_contact import LenderContact, LenderContactRole
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
from app.schemas.loan_file import LoanFileUpdate
from app.services.lender_contacts import (
    CannotAssignError,
    assign_underwriter,
    find_contact_by_email,
    get_scoped_contact,
    list_contacts,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    return company


async def _lender(db: AsyncSession, company: Company, slug: str) -> Lender:
    lender = Lender(company_id=company.id, name=slug.upper(), slug=slug, supported_programs=[])
    db.add(lender)
    await db.flush()
    return lender


async def _contact(
    db: AsyncSession, lender: Lender, *, name: str = "Dana Reed", email: str | None = None
) -> LenderContact:
    contact = LenderContact(
        lender_id=lender.id,
        name=name,
        email=email or f"{uuid4().hex[:8]}@lender.example.com",
        role=LenderContactRole.UNDERWRITER,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _file(db: AsyncSession, company: Company, lender: Lender | None = None):
    from app.services.loan_files import create_loan_file

    return await create_loan_file(
        db,
        company_id=company.id,
        lender_id=lender.id if lender else None,
        loan_program=LoanProgram.CONVENTIONAL,
    )


# --------------------------------------------------------------------------------------------- #
# The dangerous case, made reachable
# --------------------------------------------------------------------------------------------- #
async def test_another_companys_contact_cannot_be_assigned(db_session: AsyncSession) -> None:
    """TWO REAL COMPANIES, TWO REAL LENDERS, A REAL CONTACT AT THE OTHER ONE.

    The contact id is a body parameter and the route only proves the caller owns the FILE. If this
    check went, a loan file would point at another tenant's row and every later read of "who is the
    underwriter" would answer with their data.
    """
    theirs = await _company(db_session, "theirs")
    mine = await _company(db_session, "mine")
    their_lender = await _lender(db_session, theirs, "uwm")
    my_lender = await _lender(db_session, mine, "uwm")
    their_contact = await _contact(db_session, their_lender, name="Their Underwriter")
    my_file = await _file(db_session, mine, my_lender)

    with pytest.raises(CannotAssignError, match="No such contact"):
        await assign_underwriter(
            db_session, loan_file=my_file, contact_id=their_contact.id, company_id=mine.id
        )

    assert my_file.underwriter_contact_id is None


async def test_the_refusal_is_the_same_for_a_contact_that_never_existed(
    db_session: AsyncSession,
) -> None:
    """Telling them apart would confirm the id exists — an oracle over another tenant's rows."""
    theirs = await _company(db_session, "oracle-theirs")
    mine = await _company(db_session, "oracle-mine")
    their_contact = await _contact(db_session, await _lender(db_session, theirs, "uwm"))
    my_file = await _file(db_session, mine, await _lender(db_session, mine, "uwm"))

    messages = []
    for contact_id in (their_contact.id, uuid4()):
        with pytest.raises(CannotAssignError) as caught:
            await assign_underwriter(
                db_session, loan_file=my_file, contact_id=contact_id, company_id=mine.id
            )
        messages.append(str(caught.value))

    assert messages[0] == messages[1]


async def test_a_contact_at_a_different_lender_in_the_same_company_is_refused(
    db_session: AsyncSession,
) -> None:
    """THE SECOND AXIS. One company, two lenders — the tenant check passes and this must not.

    A file reading "submitted to Sun-West, underwriter at UWM" looks complete and is wrong in the
    one field a processor would act on: they would email a stranger about somebody else's loan.
    """
    company = await _company(db_session, "one-company")
    uwm = await _lender(db_session, company, "uwm")
    sunwest = await _lender(db_session, company, "sun-west")
    uwm_contact = await _contact(db_session, uwm)
    file_at_sunwest = await _file(db_session, company, sunwest)

    with pytest.raises(CannotAssignError, match="different lender"):
        await assign_underwriter(
            db_session,
            loan_file=file_at_sunwest,
            contact_id=uwm_contact.id,
            company_id=company.id,
        )


async def test_a_file_with_no_lender_cannot_have_an_underwriter(
    db_session: AsyncSession,
) -> None:
    """ "The underwriter for this file" means nothing before anyone has decided where it is going."""
    company = await _company(db_session, "no-lender")
    contact = await _contact(db_session, await _lender(db_session, company, "uwm"))
    orphan = await _file(db_session, company, None)

    with pytest.raises(CannotAssignError, match="Assign a lender"):
        await assign_underwriter(
            db_session, loan_file=orphan, contact_id=contact.id, company_id=company.id
        )


async def test_the_right_contact_is_assigned(db_session: AsyncSession) -> None:
    company = await _company(db_session, "happy")
    lender = await _lender(db_session, company, "uwm")
    contact = await _contact(db_session, lender)
    loan_file = await _file(db_session, company, lender)

    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )

    assert loan_file.underwriter_contact_id == contact.id


async def test_clearing_needs_none_of_the_checks(db_session: AsyncSession) -> None:
    """Removing something is not an assertion about what it was — including for a file whose
    lender has since been cleared, which every check above would refuse."""
    company = await _company(db_session, "clearing")
    lender = await _lender(db_session, company, "uwm")
    contact = await _contact(db_session, lender)
    loan_file = await _file(db_session, company, lender)
    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )
    loan_file.lender_id = None
    await db_session.flush()

    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=None, company_id=company.id
    )

    assert loan_file.underwriter_contact_id is None


# --------------------------------------------------------------------------------------------- #
# The invariant that is not self-enforcing
# --------------------------------------------------------------------------------------------- #
async def test_changing_the_lender_clears_the_underwriter(db_session: AsyncSession) -> None:
    """AN ORDINARY PATCH BREAKS THE ASSIGNMENT, and nothing on the screen would say so.

    `assign_underwriter` proves the contact is at the file's lender at the moment of assignment.
    `update_loan_file` then setattrs whatever it is given — including `lender_id`. Without the
    clear, the file names an underwriter at a lender it is no longer going to.
    """
    from app.services.loan_files import update_loan_file

    company = await _company(db_session, "moved")
    uwm = await _lender(db_session, company, "uwm")
    sunwest = await _lender(db_session, company, "sun-west")
    contact = await _contact(db_session, uwm)
    loan_file = await _file(db_session, company, uwm)
    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )
    assert loan_file.underwriter_contact_id == contact.id

    await update_loan_file(
        db_session, loan_file=loan_file, data=LoanFileUpdate(lender_id=sunwest.id)
    )

    assert loan_file.underwriter_contact_id is None


async def test_an_unrelated_patch_leaves_the_underwriter_alone(db_session: AsyncSession) -> None:
    """THE CONTROL. Without it the test above passes for a clear that fires on every edit.

    A processor changing the loan amount must not silently lose the underwriter — and a guard that
    clears unconditionally is green against the test above and wrong in the ordinary case.
    """
    from decimal import Decimal

    from app.services.loan_files import update_loan_file

    company = await _company(db_session, "unrelated")
    lender = await _lender(db_session, company, "uwm")
    contact = await _contact(db_session, lender)
    loan_file = await _file(db_session, company, lender)
    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )

    await update_loan_file(
        db_session, loan_file=loan_file, data=LoanFileUpdate(loan_amount=Decimal("450000"))
    )

    assert loan_file.underwriter_contact_id == contact.id


async def test_setting_the_same_lender_again_is_not_a_change(db_session: AsyncSession) -> None:
    """A PATCH that resends the lender it already has must not count as moving it."""
    from app.services.loan_files import update_loan_file

    company = await _company(db_session, "same-lender")
    lender = await _lender(db_session, company, "uwm")
    contact = await _contact(db_session, lender)
    loan_file = await _file(db_session, company, lender)
    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )

    await update_loan_file(
        db_session, loan_file=loan_file, data=LoanFileUpdate(lender_id=lender.id)
    )

    assert loan_file.underwriter_contact_id == contact.id


# --------------------------------------------------------------------------------------------- #
# The reason this ticket moved before LP-815: the underwriter has to be a participant
# --------------------------------------------------------------------------------------------- #
async def test_the_assigned_underwriter_is_seeded_as_a_participant(
    db_session: AsyncSession,
) -> None:
    """WITHOUT THIS THE ASSIGNMENT IS DECORATION. LP-805's ladder and its trust decision both ask
    whether a sender is on the file; an underwriter who is not is a stranger, so their reply lands
    in triage rather than on the file it is about."""
    from app.services.inbound_participants import seed_participants

    company = await _company(db_session, "participant")
    lender = await _lender(db_session, company, "uwm")
    contact = await _contact(db_session, lender, email="Dana.Reed@UWM.example.com")
    loan_file = await _file(db_session, company, lender)
    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )

    await seed_participants(db_session, loan_file=loan_file)

    rows = (
        (
            await db_session.execute(
                select(LoanFileParticipant).where(LoanFileParticipant.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    underwriters = [row for row in rows if row.role is ParticipantRole.UNDERWRITER]
    assert len(underwriters) == 1
    # Lowercased, like every other participant — a case-sensitive match fails to recognise an
    # underwriter whose client capitalised their address, every single time.
    assert underwriters[0].email == "dana.reed@uwm.example.com"
    assert underwriters[0].is_trusted_sender is False, (
        "membership is not trust — §2.3 makes quarantine the default"
    )


async def test_an_unassigned_file_seeds_no_underwriter(db_session: AsyncSession) -> None:
    """THE CONTROL for the test above, which would otherwise pass against a seeder that invented
    an underwriter row for every file."""
    from app.services.inbound_participants import seed_participants

    company = await _company(db_session, "no-underwriter")
    lender = await _lender(db_session, company, "uwm")
    await _contact(db_session, lender)
    loan_file = await _file(db_session, company, lender)

    await seed_participants(db_session, loan_file=loan_file)

    rows = (
        (
            await db_session.execute(
                select(LoanFileParticipant).where(LoanFileParticipant.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row for row in rows if row.role is ParticipantRole.UNDERWRITER] == []


async def test_a_deleted_underwriter_is_not_seeded(db_session: AsyncSession) -> None:
    """A contact who has left the lender must not be re-added to the allowlist by a later re-seed.

    `underwriter_contact_id` is deliberately left pointing at them — it is the record of who the
    underwriter WAS — so the soft-delete check has to happen here rather than being implied by the
    column being null.
    """
    from app.models.base import utcnow
    from app.services.inbound_participants import seed_participants

    company = await _company(db_session, "departed")
    lender = await _lender(db_session, company, "uwm")
    contact = await _contact(db_session, lender)
    loan_file = await _file(db_session, company, lender)
    await assign_underwriter(
        db_session, loan_file=loan_file, contact_id=contact.id, company_id=company.id
    )
    contact.deleted_at = utcnow()
    await db_session.flush()

    await seed_participants(db_session, loan_file=loan_file)

    rows = (
        (
            await db_session.execute(
                select(LoanFileParticipant).where(LoanFileParticipant.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row for row in rows if row.role is ParticipantRole.UNDERWRITER] == []


# --------------------------------------------------------------------------------------------- #
# Scoped reads and the duplicate rule
# --------------------------------------------------------------------------------------------- #
async def test_contacts_are_listed_only_for_the_owning_company(db_session: AsyncSession) -> None:
    theirs = await _company(db_session, "list-theirs")
    mine = await _company(db_session, "list-mine")
    their_lender = await _lender(db_session, theirs, "uwm")
    await _contact(db_session, their_lender)

    assert await list_contacts(db_session, lender_id=their_lender.id, company_id=mine.id) == []
    assert (
        len(await list_contacts(db_session, lender_id=their_lender.id, company_id=theirs.id)) == 1
    )


async def test_a_scoped_contact_read_refuses_another_company(db_session: AsyncSession) -> None:
    theirs = await _company(db_session, "scoped-theirs")
    mine = await _company(db_session, "scoped-mine")
    contact = await _contact(db_session, await _lender(db_session, theirs, "uwm"))

    assert await get_scoped_contact(db_session, contact_id=contact.id, company_id=mine.id) is None
    assert (
        await get_scoped_contact(db_session, contact_id=contact.id, company_id=theirs.id)
    ) is not None


async def test_the_same_address_is_found_whatever_the_case(db_session: AsyncSession) -> None:
    """Two rows for one underwriter means a file assigned to one and mail arriving from the other."""
    company = await _company(db_session, "dupe")
    lender = await _lender(db_session, company, "uwm")
    await _contact(db_session, lender, email="Dana.Reed@UWM.example.com")

    found = await find_contact_by_email(
        db_session, lender_id=lender.id, email="dana.reed@uwm.example.com"
    )

    assert found is not None


async def test_the_database_refuses_the_duplicate_too(db_session: AsyncSession) -> None:
    """The service check is a better message; the index is what makes it true under a race."""
    from sqlalchemy.exc import IntegrityError

    company = await _company(db_session, "dupe-db")
    lender = await _lender(db_session, company, "uwm")
    await _contact(db_session, lender, email="dana@uwm.example.com")

    db_session.add(
        LenderContact(
            lender_id=lender.id,
            name="Dana Again",
            email="DANA@uwm.example.com",
            role=LenderContactRole.UNDERWRITER,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_two_contacts_with_no_email_do_not_collide(db_session: AsyncSession) -> None:
    """The index is partial for this: a phone-only contact is a legitimate row, and several of them
    must not collide on NULL — which a plain unique index over `(lender_id, lower(email))` would
    not do anyway, but the partial clause says so rather than relying on it."""
    company = await _company(db_session, "no-email")
    lender = await _lender(db_session, company, "uwm")

    for name in ("A Person", "Another Person"):
        db_session.add(
            LenderContact(lender_id=lender.id, name=name, email=None, role=LenderContactRole.OTHER)
        )
    await db_session.flush()

    assert len(await list_contacts(db_session, lender_id=lender.id, company_id=company.id)) == 2
