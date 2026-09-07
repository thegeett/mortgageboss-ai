"""LP-805 — the token resolver, which is the one place in the codebase that inverts the tenancy rule.

Everywhere else, `company_id` comes from an authenticated user. Here it comes from an EMAIL ADDRESS
a stranger typed. That inversion is deliberate and it is written once; the protocol says a second one
is a blocking finding.

SO THE CROSS-TENANT TEST IS WRITTEN FIRST, AND IT IS WRITTEN TO FAIL AGAINST A RESOLVER WITH NO
SCOPING — not to pass because the fixture only ever had one company. That is the `_setup` trap from
LP-811a arriving in the worst possible place: a test asserting isolation, green because there was
nothing to isolate from. Every test below builds TWO companies with two real files and proves the
wrong one gets nothing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import Company, LoanProgram
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession


async def _company_with_file(db: AsyncSession, *, slug: str):
    from app.services.loan_files import create_loan_file

    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    loan_file = await create_loan_file(
        db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    return company, loan_file


# --------------------------------------------------------------------------------------------- #
# The cross-tenant property, written first
# --------------------------------------------------------------------------------------------- #
async def test_a_token_resolves_only_its_own_file(db_session: AsyncSession) -> None:
    """TWO COMPANIES, TWO REAL FILES, TWO REAL TOKENS. Each address must resolve to its own file and
    to nothing else.

    Written this way deliberately: a fixture with ONE company would pass against a resolver that
    ignored scoping entirely, because there would be nothing to confuse it with. The assertion that
    matters is the negative one, and a negative assertion is only worth what the fixture makes
    reachable."""
    from app.services.inbound_routing import resolve_loan_file_by_address

    _theirs, their_file = await _company_with_file(db_session, slug="theirs")
    _mine, my_file = await _company_with_file(db_session, slug="mine")
    assert their_file.inbox_token != my_file.inbox_token

    resolved_theirs = await resolve_loan_file_by_address(
        db_session, address=their_file.get_inbox_address()
    )
    resolved_mine = await resolve_loan_file_by_address(
        db_session, address=my_file.get_inbox_address()
    )

    assert resolved_theirs is not None and resolved_theirs.id == their_file.id
    assert resolved_mine is not None and resolved_mine.id == my_file.id
    # The negative, which is the whole point: neither address reaches the other's file.
    assert resolved_theirs.id != my_file.id
    assert resolved_mine.id != their_file.id


async def test_the_company_comes_from_the_resolved_file_and_nowhere_else(
    db_session: AsyncSession,
) -> None:
    """The invariant stated as a test. The resolver returns a FILE; the company is read off it. There
    is no path here that takes a company from the message, the sender, or a header."""
    from app.services.inbound_routing import resolve_loan_file_by_address

    theirs, their_file = await _company_with_file(db_session, slug="theirs")
    mine, _my_file = await _company_with_file(db_session, slug="mine")

    resolved = await resolve_loan_file_by_address(
        db_session, address=their_file.get_inbox_address()
    )

    assert resolved is not None
    assert resolved.company_id == theirs.id
    assert resolved.company_id != mine.id


@pytest.mark.parametrize(
    "address",
    [
        "lf-doesnotexist@inbox.example.com",
        "lf-@inbox.example.com",
        "notatoken@inbox.example.com",
        "@inbox.example.com",
        "",
    ],
)
async def test_an_unknown_token_resolves_to_nothing(db_session: AsyncSession, address: str) -> None:
    """UNKNOWN AND EXPIRED BEHAVE IDENTICALLY, and both behave like an address that was never valid.
    A resolver that distinguished them would be an oracle: send to a guessed token, and a different
    response tells you whether that file exists."""
    from app.services.inbound_routing import resolve_loan_file_by_address

    await _company_with_file(db_session, slug="theirs")
    assert await resolve_loan_file_by_address(db_session, address=address) is None


async def test_a_soft_deleted_file_does_not_resolve(db_session: AsyncSession) -> None:
    """A closed file must not keep accepting documents. Same response as an unknown token — no
    signal that the file ever existed."""
    from app.models.base import utcnow
    from app.services.inbound_routing import resolve_loan_file_by_address

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    address = loan_file.get_inbox_address()
    assert await resolve_loan_file_by_address(db_session, address=address) is not None

    loan_file.deleted_at = utcnow()
    await db_session.flush()

    assert await resolve_loan_file_by_address(db_session, address=address) is None


async def test_the_lookup_is_case_insensitive(db_session: AsyncSession) -> None:
    """Mail clients and relays rewrite case in the local part freely. A case-sensitive lookup sends
    a borrower's documents to triage because their phone capitalised the first letter."""
    from app.services.inbound_routing import resolve_loan_file_by_address

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    shouted = loan_file.get_inbox_address().upper()

    resolved = await resolve_loan_file_by_address(db_session, address=shouted)
    assert resolved is not None and resolved.id == loan_file.id


async def test_a_token_from_another_domain_does_not_resolve(db_session: AsyncSession) -> None:
    """The local part alone is not the credential — the DOMAIN is part of it. Otherwise a token
    lifted from one environment's address resolves against another's, and staging tokens open
    production files."""
    from app.services.inbound_routing import resolve_loan_file_by_address

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    local = loan_file.get_inbox_address().split("@", 1)[0]

    assert (
        await resolve_loan_file_by_address(db_session, address=f"{local}@elsewhere.example.com")
        is None
    )


# --------------------------------------------------------------------------------------------- #
# The ladder
# --------------------------------------------------------------------------------------------- #
async def _message(db: AsyncSession, **fields):  # type: ignore[no-untyped-def]
    from app.models.inbound_message import InboundMessage

    defaults = {
        "ingest_key": f"key-{uuid4().hex[:12]}",
        "from_address": "akash@example.com",
        "to_addresses": [],
        "references": [],
        "auth_verdicts": {},
    }
    defaults.update(fields)
    message = InboundMessage(**defaults)
    db.add(message)
    await db.flush()
    return message


async def test_rung_one_routes_on_the_inbox_token(db_session: AsyncSession) -> None:
    from app.services.inbound_routing import RoutingSignal, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    message = await _message(db_session, to_addresses=[loan_file.get_inbox_address()])

    outcome = await route_message(db_session, message=message)

    assert outcome.routed
    assert outcome.loan_file is not None and outcome.loan_file.id == loan_file.id
    assert outcome.signal is RoutingSignal.INBOX_TOKEN
    assert outcome.confidence == 1.0


async def test_rung_two_matches_the_whole_references_array(db_session: AsyncSession) -> None:
    """THE PLAN CALLS THIS OUT and the reason is concrete: clients truncate the middle of a long
    `References` chain differently, so the entry that survives in one borrower's reply is not the one
    that survives in another's. Matching only the tail makes a long thread route for some clients and
    not others, which reads as intermittent rather than as a bug.

    Here the id we generated is in the MIDDLE of the array, and neither first nor last."""
    from app.models.communication import (
        Communication,
        CommunicationDirection,
        CommunicationStatus,
    )
    from app.services.inbound_routing import RoutingSignal, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        Communication(
            loan_file_id=loan_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            external_message_id="ours-in-the-middle@mail.example.com",
        )
    )
    await db_session.flush()

    message = await _message(
        db_session,
        references=[
            "someone-elses-root@example.com",
            "ours-in-the-middle@mail.example.com",
            "a-later-reply@example.com",
        ],
    )

    outcome = await route_message(db_session, message=message)

    assert outcome.routed
    assert outcome.loan_file is not None and outcome.loan_file.id == loan_file.id
    assert outcome.signal is RoutingSignal.THREAD_REFERENCE


async def test_rung_two_does_not_match_a_message_id_we_never_sent(
    db_session: AsyncSession,
) -> None:
    """The control, and the one that matters for tenancy: `References` is written by the SENDER. If
    any id in it could route, anyone could put a made-up id in their own reply and have it delivered
    into whichever file happened to have a communication on it.

    THE FIXTURE MUST CONTAIN A COMMUNICATION THAT DOES NOT MATCH. An earlier version created no
    communications at all, so a mutant that dropped the id filter entirely — matching ANY
    communication — still returned nothing and the test passed. A negative assertion is worth only
    what the fixture makes reachable, and the reachable danger here is another company's message."""
    from app.models.communication import (
        Communication,
        CommunicationDirection,
        CommunicationStatus,
    )
    from app.services.inbound_routing import route_message

    _theirs, their_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        Communication(
            loan_file_id=their_file.id,
            direction=CommunicationDirection.OUTBOUND,
            status=CommunicationStatus.SENT,
            external_message_id="genuinely-ours@mail.example.com",
        )
    )
    await db_session.flush()

    message = await _message(db_session, references=["not-ours@example.com"])

    outcome = await route_message(db_session, message=message)
    assert not outcome.routed, (
        "a reference we never generated must not route, even when other communications exist"
    )


async def test_an_unmatched_message_is_unrouted_not_an_error(db_session: AsyncSession) -> None:
    """No match is not a failure. Confidence gates auto-acceptance, never visibility — an unrouted
    message goes to its company's triage queue and is seen there."""
    from app.services.inbound_routing import route_message

    await _company_with_file(db_session, slug="theirs")
    message = await _message(db_session, to_addresses=["someone@example.com"])

    outcome = await route_message(db_session, message=message)
    assert not outcome.routed
    assert outcome.signal is None
    assert outcome.confidence is None


# --------------------------------------------------------------------------------------------- #
# The trust decision
# --------------------------------------------------------------------------------------------- #
async def test_quarantine_is_the_default(db_session: AsyncSession) -> None:
    """§2.3: quarantine is the default, not the exception. A certain match from an authenticated
    sender who is NOT trusted still goes to triage."""
    from app.services.inbound_routing import Disposition, decide_disposition, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    message = await _message(
        db_session,
        to_addresses=[loan_file.get_inbox_address()],
        auth_verdicts={"dmarcVerdict": "PASS", "virusVerdict": "PASS"},
    )
    outcome = await route_message(db_session, message=message)

    disposition, _reason = await decide_disposition(db_session, message=message, outcome=outcome)
    assert disposition is Disposition.TRIAGE


async def test_a_trusted_sender_on_a_certain_match_may_auto_accept(
    db_session: AsyncSession,
) -> None:
    """The positive control. Without it, a decision that returned TRIAGE for everything would satisfy
    every other test here — and the rule LP-806 turns on would never have been exercised."""
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
    from app.services.inbound_routing import Disposition, decide_disposition, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.BORROWER,
            email="akash@example.com",
            is_trusted_sender=True,
        )
    )
    await db_session.flush()

    message = await _message(
        db_session,
        to_addresses=[loan_file.get_inbox_address()],
        auth_verdicts={"dmarcVerdict": "PASS", "virusVerdict": "PASS"},
    )
    outcome = await route_message(db_session, message=message)

    disposition, _reason = await decide_disposition(db_session, message=message, outcome=outcome)
    assert disposition is Disposition.AUTO_ACCEPT


async def test_gray_is_not_pass(db_session: AsyncSession) -> None:
    """§2.3's named subtlety. SES's `dkimVerdict: GRAY` most often means *signed by a domain that
    does not match From:* — precisely the spoofing case. Compared for equality with PASS rather than
    tested for "not FAIL", so an unrecognised verdict fails closed."""
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
    from app.services.inbound_routing import Disposition, decide_disposition, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.BORROWER,
            email="akash@example.com",
            is_trusted_sender=True,
        )
    )
    await db_session.flush()

    message = await _message(
        db_session,
        to_addresses=[loan_file.get_inbox_address()],
        auth_verdicts={"dmarcVerdict": "GRAY", "virusVerdict": "PASS"},
    )
    outcome = await route_message(db_session, message=message)

    disposition, _reason = await decide_disposition(db_session, message=message, outcome=outcome)
    assert disposition is Disposition.TRIAGE


async def test_a_virus_is_rejected_outright(db_session: AsyncSession) -> None:
    from app.services.inbound_routing import Disposition, decide_disposition, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    message = await _message(
        db_session,
        to_addresses=[loan_file.get_inbox_address()],
        auth_verdicts={"virusVerdict": "FAIL"},
    )
    outcome = await route_message(db_session, message=message)

    disposition, _reason = await decide_disposition(db_session, message=message, outcome=outcome)
    assert disposition is Disposition.REJECT


async def test_dmarc_fail_under_a_reject_policy_is_rejected(db_session: AsyncSession) -> None:
    """Both halves are required. A DMARC failure alone is triaged — plenty of legitimate mail fails
    DMARC after a forward — but a failure the sender's own domain asked us to reject is not ours to
    second-guess."""
    from app.services.inbound_routing import Disposition, decide_disposition, route_message

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    rejected = await _message(
        db_session,
        to_addresses=[loan_file.get_inbox_address()],
        auth_verdicts={"dmarcVerdict": "FAIL", "dmarcPolicy": "REJECT"},
    )
    triaged = await _message(
        db_session,
        to_addresses=[loan_file.get_inbox_address()],
        auth_verdicts={"dmarcVerdict": "FAIL", "dmarcPolicy": "NONE"},
    )

    for message, expected in ((rejected, Disposition.REJECT), (triaged, Disposition.TRIAGE)):
        outcome = await route_message(db_session, message=message)
        disposition, _reason = await decide_disposition(
            db_session, message=message, outcome=outcome
        )
        assert disposition is expected


# --------------------------------------------------------------------------------------------- #
# Applying the routing
# --------------------------------------------------------------------------------------------- #
async def test_applying_routing_writes_the_company_from_the_file(
    db_session: AsyncSession,
) -> None:
    """THE INVARIANT, at the point it is written. `message.company_id` comes from
    `loan_file.company_id` and from nowhere else."""
    from app.models.inbound_message import InboundRoutingState
    from app.services.inbound_routing import apply_routing

    company, loan_file = await _company_with_file(db_session, slug="theirs")
    _other, _other_file = await _company_with_file(db_session, slug="mine")
    message = await _message(db_session, to_addresses=[loan_file.get_inbox_address()])

    await apply_routing(db_session, message=message)

    assert message.company_id == company.id
    assert message.loan_file_id == loan_file.id
    assert message.routing_state is InboundRoutingState.ROUTED
    assert message.routing_signal == "inbox_token"


async def test_an_unrouted_message_is_owned_by_nobody(db_session: AsyncSession) -> None:
    """No company is guessed from the sender. That guess is exactly the derivation this module exists
    to confine, and an unrouted message genuinely belongs to nobody yet."""
    from app.models.inbound_message import InboundRoutingState
    from app.services.inbound_routing import apply_routing

    await _company_with_file(db_session, slug="theirs")
    message = await _message(db_session, to_addresses=["stranger@example.com"])

    await apply_routing(db_session, message=message)

    assert message.company_id is None
    assert message.loan_file_id is None
    assert message.routing_state is InboundRoutingState.UNROUTED


async def test_routing_opens_the_correspondence_record(db_session: AsyncSession) -> None:
    """`Communication(INBOUND, RECEIVED)` and `COMMUNICATION_RECEIVED` — the model and the enum value
    have both existed since LP-20 and neither has ever been used."""
    from app.models.activity_log import ActivityLog, ActivityType
    from app.models.communication import Communication, CommunicationDirection
    from app.services.inbound_routing import apply_routing
    from sqlalchemy import select

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    message = await _message(db_session, to_addresses=[loan_file.get_inbox_address()])

    await apply_routing(db_session, message=message)

    inbound = (
        await db_session.execute(
            select(Communication).where(
                Communication.loan_file_id == loan_file.id,
                Communication.direction == CommunicationDirection.INBOUND,
            )
        )
    ).scalar_one()
    # NO subject, NO body, NO sender — they live on the inbound_message row, whose readonly view
    # already drops them. Copying them here would put borrower prose in a second place with its own
    # exposure decisions.
    assert inbound.subject is None
    assert inbound.body is None
    assert inbound.sender is None

    activity = (
        await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == loan_file.id,
                ActivityLog.activity_type == ActivityType.COMMUNICATION_RECEIVED,
            )
        )
    ).scalar_one()
    assert activity.detail["routing_signal"] == "inbox_token"
    assert "akash@example.com" not in f"{activity.summary} {activity.detail}"


# --------------------------------------------------------------------------------------------- #
# Participants
# --------------------------------------------------------------------------------------------- #
async def test_participants_are_seeded_from_what_already_exists(
    db_session: AsyncSession,
) -> None:
    from app.models.borrower import Borrower
    from app.services.inbound_participants import is_participant, seed_participants

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Akash",
            last_name="Patel",
            email="Akash@Example.com",
        )
    )
    loan_file.loan_officer_email = "lo@lender.example.com"
    await db_session.flush()

    added = await seed_participants(db_session, loan_file=loan_file)

    assert added == 2
    assert await is_participant(db_session, loan_file_id=loan_file.id, address="akash@example.com")
    assert await is_participant(
        db_session, loan_file_id=loan_file.id, address="LO@LENDER.EXAMPLE.COM"
    )


async def test_seeding_is_idempotent(db_session: AsyncSession) -> None:
    """It runs again whenever a borrower's email is edited or an officer is assigned, so it must
    converge rather than accumulate."""
    from app.models.borrower import Borrower
    from app.models.loan_file_participant import LoanFileParticipant
    from app.services.inbound_participants import seed_participants
    from sqlalchemy import func, select

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Akash",
            last_name="Patel",
            email="akash@example.com",
        )
    )
    await db_session.flush()

    await seed_participants(db_session, loan_file=loan_file)
    second = await seed_participants(db_session, loan_file=loan_file)

    assert second == 0
    count = await db_session.scalar(select(func.count()).select_from(LoanFileParticipant))
    assert count == 1


async def test_seeding_never_grants_trust(db_session: AsyncSession) -> None:
    """MEMBERSHIP IS NOT TRUST. If seeding set it, every borrower would be trusted the moment their
    email was recorded — the exact opposite of "quarantine is the default"."""
    from app.models.borrower import Borrower
    from app.services.inbound_participants import is_trusted_sender, seed_participants

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Akash",
            last_name="Patel",
            email="akash@example.com",
        )
    )
    await db_session.flush()
    await seed_participants(db_session, loan_file=loan_file)

    assert not await is_trusted_sender(
        db_session, loan_file_id=loan_file.id, address="akash@example.com"
    )


async def test_seeding_does_not_revoke_trust_a_person_granted(
    db_session: AsyncSession,
) -> None:
    """Re-seeding must not quietly undo a decision somebody made."""
    from app.models.borrower import Borrower
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
    from app.services.inbound_participants import is_trusted_sender, seed_participants

    _company, loan_file = await _company_with_file(db_session, slug="theirs")
    db_session.add(
        Borrower(
            loan_file_id=loan_file.id,
            first_name="Akash",
            last_name="Patel",
            email="akash@example.com",
        )
    )
    db_session.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.BORROWER,
            email="akash@example.com",
            is_trusted_sender=True,
        )
    )
    await db_session.flush()

    await seed_participants(db_session, loan_file=loan_file)

    assert await is_trusted_sender(
        db_session, loan_file_id=loan_file.id, address="akash@example.com"
    )


async def test_a_participant_on_one_file_is_not_a_participant_on_another(
    db_session: AsyncSession,
) -> None:
    """The same address is routinely on two companies' files — a borrower shopping two brokers. A
    participant list that answered across files would make "is this sender known?" a question with a
    cross-tenant answer."""
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
    from app.services.inbound_participants import is_participant

    _theirs, their_file = await _company_with_file(db_session, slug="theirs")
    _mine, my_file = await _company_with_file(db_session, slug="mine")
    db_session.add(
        LoanFileParticipant(
            loan_file_id=their_file.id,
            role=ParticipantRole.BORROWER,
            email="akash@example.com",
        )
    )
    await db_session.flush()

    assert await is_participant(db_session, loan_file_id=their_file.id, address="akash@example.com")
    assert not await is_participant(
        db_session, loan_file_id=my_file.id, address="akash@example.com"
    )


# --------------------------------------------------------------------------------------------- #
# The token lookup has to be able to use an index (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_the_token_lookup_uses_an_index(db_session: AsyncSession) -> None:
    """`resolve_loan_file_by_address` compares `lower(inbox_token)`, and a plain btree index on the
    raw column cannot serve an expression.

    Asserted through the PLANNER rather than by checking the index exists, because the index
    existing and the query using it are different claims — a differently-spelled expression, or an
    index built on the wrong one, would leave this scanning while `pg_indexes` still looked right.
    `enable_seqscan = off` makes a sequential scan cost ten billion, so a Seq Scan in this plan
    means no index could serve the query at all rather than that the planner merely preferred not
    to. Measured before the index existed: Seq Scan even under that setting.

    It matters because this is the hottest path in inbound routing — every message resolves a token
    — and it is also the path an attacker probes by mailing guessed addresses, which LP-805 records
    as having no rate limit. A full table scan per guess is the wrong cost to hand them.
    """
    await db_session.execute(sa_text("SET enable_seqscan = off"))
    plan = (
        (
            await db_session.execute(
                sa_text("EXPLAIN SELECT id FROM loan_files WHERE lower(inbox_token) = 'abc'")
            )
        )
        .scalars()
        .all()
    )

    assert "Seq Scan" not in plan[0], f"the token lookup cannot use an index: {plan[0]}"
    assert "ix_loan_files_inbox_token_lower" in plan[0], plan[0]
