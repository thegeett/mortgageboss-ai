"""LP-808 — Route B, the third tenancy inversion, and ladder rungs 3-5.

THE INVERSION IS THE THING TO READ FIRST. `resolve_connection_by_address` derives a COMPANY from a
token in an address a stranger sent. The execution protocol permitted two such places and this is a
third; §3.5 is amended in the same commit, as that rule itself instructs.

It is weaker than the other two in one respect and the tests are shaped around that: the other two
resolve a loan FILE, so a wrong answer misfiles one message. This resolves a COMPANY, so a wrong
answer puts a message in the wrong company's queue entirely. Everything below is either "it refuses"
or "it refuses identically" for that reason.

AND RUNGS 3-5 ARE COMPANY-SCOPED WHILE 1-2 ARE NOT. That asymmetry is the second thing under test.
Rungs 1 and 2 match on something unguessable, so the match itself proves the company. Rungs 3, 4 and
5 match on a display id, a sender address and a subject line — none unguessable — so scoping is the
only thing stopping `[LF-7K3M]` in a stranger's subject from reaching whichever company holds it.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from app.models import Company, LoanProgram
from app.models.base import utcnow
from app.models.inbound_message import InboundMessage, InboundRoutingState
from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
from app.models.mailbox_connection import MailboxConnectionStatus, MailboxVerification
from app.services.inbound_routing import RoutingSignal, attach_route_b_company, route_message
from app.services.mailbox_connections import (
    create_connection,
    is_stale,
    record_arrival,
    resolve_connection_by_address,
    revoke_connection,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _company(db: AsyncSession, slug: str) -> Company:
    company = Company(name=slug.title(), slug=f"{slug}-{uuid4().hex[:8]}")
    db.add(company)
    await db.flush()
    return company


async def _file(db: AsyncSession, company: Company):
    from app.services.loan_files import create_loan_file

    return await create_loan_file(db, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL)


async def _arrived(db: AsyncSession, *, to: list[str], **overrides) -> InboundMessage:
    message = InboundMessage(
        ingest_key=f"key-{uuid4().hex[:12]}",
        to_addresses=to,
        from_address=overrides.pop("from_address", "jane@borrower.example"),
        subject=overrides.pop("subject", "Documents"),
        routing_state=InboundRoutingState.PENDING,
        auth_verdicts={},
        **overrides,
    )
    db.add(message)
    await db.flush()
    return message


# --------------------------------------------------------------------------------------------- #
# The inversion
# --------------------------------------------------------------------------------------------- #
async def test_the_alias_resolves_to_its_own_company(db_session: AsyncSession) -> None:
    company = await _company(db_session, "acme")
    connection = await create_connection(db_session, company_id=company.id)

    resolved = await resolve_connection_by_address(
        db_session, address=connection.get_ingest_address()
    )

    assert resolved is not None
    assert resolved.company_id == company.id


async def test_every_failure_is_the_same_answer(db_session: AsyncSession) -> None:
    """FOUR REAL STATES, each built. A distinguishable answer tells a prober which token is worth
    another guess — and here a right guess reaches a whole company's triage queue, not one file."""
    company = await _company(db_session, "probe")
    revoked = await create_connection(db_session, company_id=company.id)
    await revoke_connection(db_session, connection=revoked)
    deleted = await create_connection(db_session, company_id=company.id)
    deleted.deleted_at = utcnow()
    live = await create_connection(db_session, company_id=company.id)
    await db_session.flush()

    wrong_domain = live.get_ingest_address().replace(
        live.get_ingest_address().split("@", 1)[1], "elsewhere.example"
    )
    for address in (
        "co-neverexisted@" + live.get_ingest_address().split("@", 1)[1],
        revoked.get_ingest_address(),
        deleted.get_ingest_address(),
        wrong_domain,
        "not-an-address",
        "",
        None,
    ):
        assert await resolve_connection_by_address(db_session, address=address) is None


async def test_the_live_one_still_resolves(db_session: AsyncSession) -> None:
    """THE CONTROL. Without it the refusals above pass against a resolver that answers None always,
    which is the shape a broken allowlist takes."""
    company = await _company(db_session, "control")
    connection = await create_connection(db_session, company_id=company.id)

    assert (
        await resolve_connection_by_address(db_session, address=connection.get_ingest_address())
    ) is not None


async def test_the_lookup_is_case_insensitive(db_session: AsyncSession) -> None:
    """A relay may rewrite the local part. A case-sensitive lookup drops a company's mail on the
    floor for a reason nobody can see."""
    company = await _company(db_session, "case")
    connection = await create_connection(db_session, company_id=company.id)

    resolved = await resolve_connection_by_address(
        db_session, address=connection.get_ingest_address().upper()
    )

    assert resolved is not None


async def test_a_file_address_does_not_resolve_as_a_connection(db_session: AsyncSession) -> None:
    """`lf-` and `co-` resolve to different things. A resolver accepting either would make "which
    kind of address is this" a question answered by whichever lookup happened to hit."""
    company = await _company(db_session, "prefixes")
    loan_file = await _file(db_session, company)

    assert (
        await resolve_connection_by_address(db_session, address=loan_file.get_inbox_address())
    ) is None


# --------------------------------------------------------------------------------------------- #
# Attaching the company, and what it does not do
# --------------------------------------------------------------------------------------------- #
async def test_a_forwarded_message_gets_its_company(db_session: AsyncSession) -> None:
    company = await _company(db_session, "forwarded")
    connection = await create_connection(db_session, company_id=company.id)
    message = await _arrived(db_session, to=[connection.get_ingest_address()])

    assert await attach_route_b_company(db_session, message=message) is True
    assert message.company_id == company.id
    # THE FILE IS STILL UNKNOWN. The connection decides the company; the ladder decides the file, and
    # keeping those separate is what leaves the file-level tenancy invariant untouched.
    assert message.loan_file_id is None


async def test_an_already_owned_message_is_left_alone(db_session: AsyncSession) -> None:
    """Rung 1 resolved a file and read the company off it. Re-deriving from an alias would be a
    second answer to a question already settled by the stronger signal."""
    company = await _company(db_session, "owned")
    other = await _company(db_session, "other")
    connection = await create_connection(db_session, company_id=other.id)
    message = await _arrived(db_session, to=[connection.get_ingest_address()])
    message.company_id = company.id
    await db_session.flush()

    assert await attach_route_b_company(db_session, message=message) is False
    assert message.company_id == company.id


async def test_arrival_verifies_the_connection(db_session: AsyncSession) -> None:
    """§3: "the moment anything arrives at that address we flip it to verified". No button — one
    would let somebody mark a connection working before the admin had made the rule, and the banner
    that exists to catch silence would then never fire."""
    company = await _company(db_session, "verify")
    connection = await create_connection(db_session, company_id=company.id)
    assert connection.verification is MailboxVerification.NOT_VERIFIED
    message = await _arrived(db_session, to=[connection.get_ingest_address()])

    await attach_route_b_company(db_session, message=message)

    await db_session.refresh(connection)
    assert connection.verification is MailboxVerification.VERIFIED
    assert connection.last_success_at is not None


async def test_a_revoked_connection_takes_no_more_mail(db_session: AsyncSession) -> None:
    company = await _company(db_session, "revoked")
    connection = await create_connection(db_session, company_id=company.id)
    await revoke_connection(db_session, connection=connection)
    message = await _arrived(db_session, to=[connection.get_ingest_address()])

    assert await attach_route_b_company(db_session, message=message) is False
    assert message.company_id is None


# --------------------------------------------------------------------------------------------- #
# Rungs 3-5, and the scoping that makes them safe
# --------------------------------------------------------------------------------------------- #
async def test_a_footer_tag_routes_within_the_company(db_session: AsyncSession) -> None:
    company = await _company(db_session, "footer")
    loan_file = await _file(db_session, company)
    message = await _arrived(
        db_session, to=["docs@herco.example"], subject=f"Re: docs [{loan_file.display_id}]"
    )
    message.company_id = company.id
    await db_session.flush()

    outcome = await route_message(db_session, message=message)

    assert outcome.loan_file is not None
    assert outcome.loan_file.id == loan_file.id
    assert outcome.signal is RoutingSignal.FOOTER_TAG
    # HIGH, NOT CERTAIN — a display id is an identifier anyone who has seen one of our emails can
    # write, so it routes and must not auto-accept.
    assert outcome.confidence is not None
    assert outcome.confidence < 1.0


async def test_a_footer_tag_does_not_reach_another_companys_file(
    db_session: AsyncSession,
) -> None:
    """THE ONE THAT MATTERS. Display ids are short and not secret; without company scoping, a
    stranger writing `[LF-XXXX]` in a subject reaches whichever company holds that id."""
    theirs = await _company(db_session, "tag-theirs")
    mine = await _company(db_session, "tag-mine")
    their_file = await _file(db_session, theirs)
    message = await _arrived(db_session, to=["x@y.example"], subject=f"[{their_file.display_id}]")
    message.company_id = mine.id
    await db_session.flush()

    outcome = await route_message(db_session, message=message)

    assert outcome.loan_file is None


async def test_a_message_with_no_company_matches_no_file_on_rungs_three_to_five(
    db_session: AsyncSession,
) -> None:
    """NO COMPANY MEANS NO CANDIDATES. Returning "all files" would be the cross-tenant failure the
    scoping exists to prevent, and it is the natural thing an unscoped query does."""
    company = await _company(db_session, "orphan")
    loan_file = await _file(db_session, company)
    message = await _arrived(db_session, to=["x@y.example"], subject=f"[{loan_file.display_id}]")

    assert (await route_message(db_session, message=message)).loan_file is None


async def test_a_participant_routes_when_exactly_one_file_matches(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session, "participant")
    loan_file = await _file(db_session, company)
    db_session.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.BORROWER,
            email="jane@borrower.example",
            is_trusted_sender=False,
        )
    )
    message = await _arrived(db_session, to=["docs@herco.example"], subject="no reference here")
    message.company_id = company.id
    await db_session.flush()

    outcome = await route_message(db_session, message=message)

    assert outcome.signal is RoutingSignal.PARTICIPANT
    assert outcome.loan_file is not None
    assert outcome.loan_file.id == loan_file.id


async def test_a_participant_on_two_files_goes_to_triage(db_session: AsyncSession) -> None:
    """EXACTLY ONE, and the word is load-bearing. A borrower with two files in progress is ordinary;
    picking either would file half their documents in the wrong place while looking confident."""
    company = await _company(db_session, "ambiguous")
    for _ in range(2):
        loan_file = await _file(db_session, company)
        db_session.add(
            LoanFileParticipant(
                loan_file_id=loan_file.id,
                role=ParticipantRole.BORROWER,
                email="jane@borrower.example",
                is_trusted_sender=False,
            )
        )
    message = await _arrived(db_session, to=["docs@herco.example"], subject="no reference")
    message.company_id = company.id
    await db_session.flush()

    assert (await route_message(db_session, message=message)).loan_file is None


async def test_a_bare_display_id_in_the_subject_routes_as_a_weaker_signal(
    db_session: AsyncSession,
) -> None:
    """Separate from the footer rung because the grade is stored and they are graded differently: a
    bracketed tag is our own footer coming back, a bare id is somebody typing a reference."""
    company = await _company(db_session, "subject")
    loan_file = await _file(db_session, company)
    message = await _arrived(
        db_session, to=["docs@herco.example"], subject=f"About {loan_file.display_id} please"
    )
    message.company_id = company.id
    await db_session.flush()

    outcome = await route_message(db_session, message=message)

    assert outcome.signal is RoutingSignal.SUBJECT_REFERENCE


async def test_the_token_rung_still_wins(db_session: AsyncSession) -> None:
    """FIRST HIT WINS, and the order is by strength. A forwarded message that still carries the
    borrower's `lf-<token>@` in `X-Gm-Original-To` must route on that, with certainty, rather than on
    a subject line."""
    company = await _company(db_session, "order")
    loan_file = await _file(db_session, company)
    other = await _file(db_session, company)
    message = await _arrived(
        db_session,
        to=[loan_file.get_inbox_address()],
        subject=f"About {other.display_id}",
    )
    message.company_id = company.id
    await db_session.flush()

    outcome = await route_message(db_session, message=message)

    assert outcome.signal is RoutingSignal.INBOX_TOKEN
    assert outcome.loan_file is not None
    assert outcome.loan_file.id == loan_file.id


# --------------------------------------------------------------------------------------------- #
# Staleness — the failure that is silent
# --------------------------------------------------------------------------------------------- #
async def test_a_quiet_verified_connection_is_stale(db_session: AsyncSession) -> None:
    """The worst failure here is silent: the rule was removed, nothing errored, and documents
    stopped arriving."""
    company = await _company(db_session, "stale")
    connection = await create_connection(db_session, company_id=company.id)
    await record_arrival(db_session, connection=connection)
    connection.last_success_at = utcnow() - timedelta(days=5)

    assert is_stale(connection) is True


async def test_a_connection_that_never_worked_is_not_stale(db_session: AsyncSession) -> None:
    """It is UNFINISHED, not broken. Saying "no mail received in 4 days" to somebody whose admin has
    not made the rule yet describes a failure that has not happened and hides the one that has."""
    company = await _company(db_session, "unfinished")
    connection = await create_connection(db_session, company_id=company.id)

    assert is_stale(connection) is False


async def test_a_recently_used_connection_is_not_stale(db_session: AsyncSession) -> None:
    """THE CONTROL. Without it a predicate returning True always is green against the first test."""
    company = await _company(db_session, "fresh")
    connection = await create_connection(db_session, company_id=company.id)
    await record_arrival(db_session, connection=connection)

    assert is_stale(connection) is False


async def test_arrival_clears_a_degraded_status(db_session: AsyncSession) -> None:
    """A connection that went quiet and then received something is working again. Leaving the status
    would keep a banner up that is no longer true, which teaches a processor to ignore it."""
    company = await _company(db_session, "recovered")
    connection = await create_connection(db_session, company_id=company.id)
    connection.status = MailboxConnectionStatus.DEGRADED
    connection.consecutive_failures = 3
    await db_session.flush()

    await record_arrival(db_session, connection=connection)

    assert connection.status is MailboxConnectionStatus.CONNECTED
    assert connection.consecutive_failures == 0
