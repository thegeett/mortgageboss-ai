"""LP-821 — the evidence record, and the legal hold that has to exist before anything purges.

TWO PROPERTIES CARRY THE TICKET AND BOTH ARE ABOUT WHAT CANNOT HAPPEN:

* **The record is append-only.** §6: *"Soft delete is fine for the UX; the audit record must not be
  soft-deletable."* That is asserted structurally — the model has no `deleted_at` and no
  `updated_at` — and behaviourally, by a second `record_sent` being refused rather than overwriting.
* **The composed draft is captured before it is destroyed.** `send_draft` overwrites `draft.body`
  with the processor's edit, so the composed version exists for exactly one statement. The test that
  matters sends a message whose edit DIFFERS from the draft and asserts both survive — a fixture
  where they matched would pass against code that recorded the same string twice and reported a diff
  of nothing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import Company, LoanProgram, User, UserRole
from app.models.communication import (
    Communication,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.communication_evidence import CommunicationEvidence, EvidenceEvent
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.evidence import (
    EvidenceError,
    LegalHoldError,
    evidence_for,
    held_file_ids,
    is_held,
    lift_hold,
    place_hold,
    record_received,
    record_sent,
    refuse_if_held,
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


# --------------------------------------------------------------------------------------------- #
# Append-only, structurally and behaviourally
# --------------------------------------------------------------------------------------------- #
def test_the_evidence_row_has_no_way_to_be_soft_deleted() -> None:
    """§6 outright: "the audit record must not be soft-deletable". Asserted on the MODEL rather than
    on a policy, because a policy is a sentence and a missing column is a type error.

    `updated_at` is absent for a related reason: on an append-only row it can only ever lie — either
    it equals `recorded_at` forever, or something updated a row that must not be updated.
    """
    columns = set(CommunicationEvidence.__table__.columns.keys())

    assert "deleted_at" not in columns
    assert "updated_at" not in columns
    assert "recorded_at" in columns


async def test_a_second_record_is_refused_rather_than_overwriting(
    db_session: AsyncSession,
) -> None:
    """A retried send is the case most likely to reach this, and an overwrite would be the one edit
    that makes the whole table untrustworthy."""
    company, loan_file = await _company_and_file(db_session, slug="dup")
    actor = await _actor(db_session, company)
    message = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
        body="what went out",
    )
    db_session.add(message)
    await db_session.flush()

    await record_sent(
        db_session, loan_file=loan_file, communication=message, approver_user_id=actor.id
    )

    with pytest.raises(EvidenceError, match="already has a sent record"):
        await record_sent(
            db_session, loan_file=loan_file, communication=message, approver_user_id=actor.id
        )


async def test_a_bounce_is_a_new_row_beside_the_send(db_session: AsyncSession) -> None:
    """The send record must not change after the fact — that is what append-only means — and "sent"
    and "sent, then bounced" are two events with two times."""
    from app.services.evidence import record_delivery_failed

    company, loan_file = await _company_and_file(db_session, slug="bounce")
    actor = await _actor(db_session, company)
    message = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
    )
    db_session.add(message)
    await db_session.flush()
    await record_sent(
        db_session, loan_file=loan_file, communication=message, approver_user_id=actor.id
    )

    await record_delivery_failed(
        db_session, loan_file=loan_file, communication=message, reason="550 no such mailbox"
    )

    rows = await evidence_for(db_session, loan_file=loan_file)
    assert [row.event for row in rows] == [
        EvidenceEvent.SENT,
        EvidenceEvent.DELIVERY_FAILED,
    ]


# --------------------------------------------------------------------------------------------- #
# The composed draft, captured in the one statement it exists for
# --------------------------------------------------------------------------------------------- #
async def test_the_send_path_captures_the_draft_before_it_is_overwritten(
    db_session: AsyncSession,
) -> None:
    """THE TEST THIS TICKET TURNS ON, and the fixture is what makes it mean something: the edit
    DIFFERS from the draft. With a fixture where they matched, code that recorded the same string
    twice — and reported a diff of nothing — would pass.

    `send_draft` replaces `draft.body` with the processor's edit, so the composed version exists for
    exactly one statement. Before LP-821 it was gone from there.
    """
    from app.services.email_draft import add_needs_to_draft
    from app.services.email_send import send_draft

    company, loan_file = await _company_and_file(db_session, slug="composed")
    actor = await _actor(db_session, company)
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add(need)
    await db_session.flush()
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor.id
    )
    composed = result.draft.body
    assert composed, "the drafter must have produced something, or this test is about nothing"

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=result.draft.id,
        recipient="jane@borrower.example",
        body="I rewrote this entirely before sending it.",
        approver_user_id=actor.id,
    )

    row = (
        await db_session.execute(
            select(CommunicationEvidence).where(
                CommunicationEvidence.communication_id == result.draft.id
            )
        )
    ).scalar_one()
    # LP-823 REVIEW — THE DRAFTED WORDS, not the raw stored string. `send_draft` now resolves
    # `$borrower_first_name` / `$processor_name` and stamps the footer tag through the SAME pipeline
    # for both copies, because `EvidencePublic.was_edited` is `body_composed != body_as_sent` and its
    # own comment says that means "the processor changed the drafted words". Comparing a stored body
    # holding placeholders against a sent body that never holds them made every message report as
    # edited, including one where nobody typed a character.
    #
    # So this asserts the SUBSTANCE rather than string identity: what was recorded is the draft, not
    # the rewrite. It still fails on code that recorded the edit twice — the fixture rewrites the
    # message entirely, so no sentence of the draft would survive.
    assert row.body_composed is not None
    assert "documents we still need from you" in row.body_composed
    assert "I rewrote this entirely" not in row.body_composed
    assert "$borrower_first_name" not in row.body_composed
    assert row.body_as_sent is not None
    assert "I rewrote this entirely" in row.body_as_sent
    assert row.body_composed != row.body_as_sent
    assert row.approver_user_id == actor.id


async def test_every_send_produces_a_record_without_the_route_asking(
    db_session: AsyncSession,
) -> None:
    """WRITTEN BY `send_draft`, NOT BY THE ENDPOINT. An evidence record that depends on a route
    remembering to ask for it is one that is missing exactly where somebody added a second route —
    and LP-820 added one this week."""
    from app.services.email_draft import add_needs_to_draft
    from app.services.email_send import send_draft

    company, loan_file = await _company_and_file(db_session, slug="always")
    actor = await _actor(db_session, company)
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="W-2",
        needs_type="w2",
        origin=NeedsItemOrigin.FINDING,
    )
    db_session.add(need)
    await db_session.flush()
    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor.id
    )

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=result.draft.id,
        recipient="jane@borrower.example",
        body="please send these",
        approver_user_id=actor.id,
    )

    assert len(await evidence_for(db_session, loan_file=loan_file)) == 1


async def test_an_inbound_record_carries_the_manifest_and_the_verdicts(
    db_session: AsyncSession,
) -> None:
    """§6 asks for the manifest WITH HASHES and for the inbound auth verdicts. The hash is the point:
    a filename is what somebody called a file, and a sha256 is what the file was."""
    from email import policy
    from email.message import EmailMessage
    from pathlib import Path

    from app.services.inbound_ingest import process_raw_message

    _company, loan_file = await _company_and_file(db_session, slug="inbound")
    pdf = (
        Path(__file__).resolve().parents[1] / "fixtures" / "attachments" / "clean.pdf"
    ).read_bytes()
    message = EmailMessage()
    message["From"] = "jane@borrower.example"
    message["To"] = loan_file.get_inbox_address()
    message["Subject"] = "Statements"
    message["Message-ID"] = "<ev1@example.com>"
    message.set_content("attached")
    message.add_attachment(pdf, maintype="application", subtype="pdf", filename="March.pdf")
    await process_raw_message(
        db_session,
        raw=message.as_bytes(policy=policy.default),
        raw_storage_path=None,
        store_raw=True,
        receipt={"dmarcVerdict": {"status": "PASS"}},
    )
    communication = (
        await db_session.execute(
            select(Communication).where(
                Communication.loan_file_id == loan_file.id,
                Communication.direction == CommunicationDirection.INBOUND,
            )
        )
    ).scalar_one()

    row = await record_received(db_session, loan_file=loan_file, communication=communication)

    assert [entry["filename"] for entry in row.attachment_manifest] == ["March.pdf"]
    assert len(row.attachment_manifest[0]["sha256"]) == 64
    assert row.auth_verdicts.get("dmarcVerdict") == "PASS"
    assert row.sender == "jane@borrower.example"


# --------------------------------------------------------------------------------------------- #
# The legal hold
# --------------------------------------------------------------------------------------------- #
async def test_a_hold_needs_a_reason(db_session: AsyncSession) -> None:
    """FRCP 37(e) asks what a party knew and when. A hold with no stated reason answers half."""
    company, loan_file = await _company_and_file(db_session, slug="noreason")
    actor = await _actor(db_session, company)

    with pytest.raises(LegalHoldError, match="reason"):
        await place_hold(db_session, loan_file=loan_file, reason="   ", actor_user_id=actor.id)


async def test_placing_a_hold_refuses_destruction(db_session: AsyncSession) -> None:
    """THE FUNCTION EXISTS BEFORE ITS CALLERS DO, deliberately. Nothing in this repo purges yet —
    INFRA-1's lifecycle expiry is written and unapplied — and §6 says the flag ships FIRST. A guard
    added after the purge is one the purge was already running without."""
    company, loan_file = await _company_and_file(db_session, slug="held")
    actor = await _actor(db_session, company)

    await place_hold(
        db_session,
        loan_file=loan_file,
        reason="Litigation hold, matter 2026-14",
        actor_user_id=actor.id,
    )

    assert is_held(loan_file) is True
    with pytest.raises(LegalHoldError, match="legal hold"):
        refuse_if_held(loan_file, action="Deleting the raw message")


async def test_an_unheld_file_is_not_refused(db_session: AsyncSession) -> None:
    """THE CONTROL. A guard that refused everything would pass the test above and stop every purge
    forever — which is the failure mode nobody notices, because nothing breaks."""
    _company, loan_file = await _company_and_file(db_session, slug="notheld")

    assert is_held(loan_file) is False
    refuse_if_held(loan_file, action="Deleting the raw message")


async def test_re_placing_a_hold_keeps_the_original_time(db_session: AsyncSession) -> None:
    """ "Since when" is the question a court asks, and the answer is when it was FIRST placed."""
    company, loan_file = await _company_and_file(db_session, slug="replace")
    actor = await _actor(db_session, company)
    await place_hold(db_session, loan_file=loan_file, reason="first", actor_user_id=actor.id)
    first_at = loan_file.legal_hold_at

    await place_hold(db_session, loan_file=loan_file, reason="clarified", actor_user_id=actor.id)

    assert loan_file.legal_hold_at == first_at
    assert loan_file.legal_hold_reason == "clarified"


async def test_lifting_clears_the_flag_and_the_activity_log_remembers(
    db_session: AsyncSession,
) -> None:
    """`legal_hold_at` is cleared so "is it held" and "was it ever held" stay different reads — the
    first is what a purge asks."""
    from app.models.activity_log import ActivityLog

    company, loan_file = await _company_and_file(db_session, slug="lift")
    actor = await _actor(db_session, company)
    await place_hold(db_session, loan_file=loan_file, reason="matter 9", actor_user_id=actor.id)

    await lift_hold(db_session, loan_file=loan_file, actor_user_id=actor.id)

    assert loan_file.legal_hold is False
    assert loan_file.legal_hold_at is None
    entries = (
        (
            await db_session.execute(
                select(ActivityLog).where(ActivityLog.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    summaries = [entry.summary for entry in entries]
    assert any("legal hold was placed" in summary for summary in summaries)
    assert any("hold on this file was lifted" in summary for summary in summaries)


async def test_the_held_set_is_company_scoped(db_session: AsyncSession) -> None:
    """A purge sweep asks once per batch rather than once per object. Company-scoped, because a
    sweep that saw another tenant's held ids would skip files it had no business knowing about —
    and, worse, would not skip its own."""
    theirs, their_file = await _company_and_file(db_session, slug="held-theirs")
    mine, my_file = await _company_and_file(db_session, slug="held-mine")
    actor = await _actor(db_session, theirs)
    await place_hold(db_session, loan_file=their_file, reason="matter 1", actor_user_id=actor.id)

    assert await held_file_ids(db_session, company_id=theirs.id) == {their_file.id}
    assert await held_file_ids(db_session, company_id=mine.id) == set()
    assert my_file.id not in await held_file_ids(db_session, company_id=theirs.id)


async def test_evidence_is_file_scoped(db_session: AsyncSession) -> None:
    """SAME COMPANY, TWO FILES. A company-scoped read would pass every cross-tenant test while
    showing one borrower's correspondence on another borrower's audit trail."""
    from app.services.loan_files import create_loan_file

    company, mine = await _company_and_file(db_session, slug="ev-scope")
    theirs = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    actor = await _actor(db_session, company)
    message = Communication(
        loan_file_id=theirs.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
    )
    db_session.add(message)
    await db_session.flush()
    await record_sent(
        db_session, loan_file=theirs, communication=message, approver_user_id=actor.id
    )

    assert await evidence_for(db_session, loan_file=mine) == []
    assert len(await evidence_for(db_session, loan_file=theirs)) == 1


# --------------------------------------------------------------------------------------------- #
# A bounce is not a guard (review finding)
# --------------------------------------------------------------------------------------------- #
async def test_a_bounce_reason_is_not_recorded_as_a_guardrail(db_session: AsyncSession) -> None:
    """`guardrail_fired` is documented as "which deterministic guard refused a composition".

    The provider's bounce diagnostic was being written into it — and since `send_draft` cannot reach
    LP-810's verdict yet, that made a bounce reason the ONLY thing that ever populated the column. So
    `550 5.1.1 user unknown` read, to anyone following the model docstring or the AI System
    Disclosure, as a compliance guard having fired. One column, two meanings, in the record that
    exists to be read by somebody who was not here.
    """
    from app.services.evidence import record_delivery_failed

    company, loan_file = await _company_and_file(db_session, slug="notaguard")
    actor = await _actor(db_session, company)
    message = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
    )
    db_session.add(message)
    await db_session.flush()
    await record_sent(
        db_session, loan_file=loan_file, communication=message, approver_user_id=actor.id
    )
    await record_delivery_failed(
        db_session,
        loan_file=loan_file,
        communication=message,
        reason="550 5.1.1 user unknown",
    )

    rows = await evidence_for(db_session, loan_file=loan_file)
    bounce = next(row for row in rows if row.event is EvidenceEvent.DELIVERY_FAILED)

    assert bounce.failure_reason == "550 5.1.1 user unknown"
    assert bounce.guardrail_fired is None


async def test_the_send_row_records_neither(db_session: AsyncSession) -> None:
    """The control, and the honest one.

    `guardrail_fired` is null on a send because the verdict is not threaded through yet — NOT
    because no guard fired. Asserting it here keeps the distinction visible: if a later change
    starts populating it, this test says so rather than the column quietly gaining a meaning.
    """
    company, loan_file = await _company_and_file(db_session, slug="neither")
    actor = await _actor(db_session, company)
    message = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        status=CommunicationStatus.SENT,
    )
    db_session.add(message)
    await db_session.flush()
    await record_sent(
        db_session, loan_file=loan_file, communication=message, approver_user_id=actor.id
    )

    (sent_row,) = [
        row
        for row in await evidence_for(db_session, loan_file=loan_file)
        if row.event is EvidenceEvent.SENT
    ]
    assert sent_row.failure_reason is None
    assert sent_row.guardrail_fired is None
