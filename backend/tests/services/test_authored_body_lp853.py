"""LP-853 — the body becomes HTML the moment a person touches it.

The column is also the flag: `body_format == 'html'` IS LP-851's `body_edited`. One fact, one place.

EVERY "IS NOT REWRITTEN" ASSERTION HERE IS PAIRED WITH A CONTROL THAT IS. A test that a plain body
survives `_regenerate` passes in any fixture where the call was never going to rewrite anything —
it would pass against a `_regenerate` that returned immediately, against a draft with no audience,
against a template that had not moved. So each refusal is asserted beside the same call on a
`plain` draft, in the same test, actually changing the body. Without the control the assertion
proves only that the code did not run.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.communications.templates import TEMPLATES, TemplateKey
from app.documents.catalog import ResponsibleParty
from app.models import Company, LoanProgram
from app.models.communication import BodyFormat, Communication, CommunicationStatus
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import (
    DraftIsAuthored,
    DraftNotEditable,
    OnConflict,
    _regenerate,
    add_needs_to_draft,
    attach_upload_link,
    draft_body_edited,
    refresh_if_stale,
    remove_need_from_draft,
    save_draft_body,
)
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


async def _draft(
    db: AsyncSession, *, title: str = "Bank statements", needs_type: str = "bank_statement"
):
    loan_file, actor = await _file_and_actor(db)
    need = await _need(db, loan_file, title=title, needs_type=needs_type)
    update = await add_needs_to_draft(db, loan_file=loan_file, needs=[need], actor_user_id=actor)
    assert update.draft is not None
    return loan_file, actor, update.draft, need


def _stale(draft: Communication) -> None:
    """Make `refresh_if_stale` want to rewrite this draft, without touching its body."""
    draft.template_version = "v0-not-a-real-version"


# --------------------------------------------------------------------------------------------- #
# Acceptance 1 + 2 — a generated body is plain, and stays plain until somebody types
# --------------------------------------------------------------------------------------------- #
async def test_a_generated_draft_is_plain(db_session: AsyncSession) -> None:
    _loan_file, _actor, draft, _first = await _draft(db_session)
    assert draft.body_format is BodyFormat.PLAIN
    assert draft_body_edited(draft) is False


def test_no_backend_template_emits_markup() -> None:
    """THE DECISION THAT KILLS LP-849's FIRST OBJECTION, asserted over EVERY template file rather
    than over the one this ticket happened to render.

    LP-849 refused HTML storage partly because "every backend template would have to emit HTML (all
    of them, each a new ADR-401 version and fingerprint)". LP-853's answer is that none of them
    does: generated bodies stay plain, and only a processor's edit is HTML. A template that grew a
    tag would break `emailBodyToHtml`'s escape-first guarantee and silently mean the plain path was
    no longer plain.

    THE FILES ON DISK, GLOBBED, not a list of the ones anybody remembered — including the retired
    versions, because ADR-401 keeps them resolvable and a pinned audit row still renders them.
    """
    from pathlib import Path

    directory = Path(__file__).resolve().parents[2] / "app" / "communications" / "templates"
    files = sorted(directory.glob("*.txt"))
    assert len(files) >= 10, f"the scan found {len(files)} templates; it proved nothing"

    offenders = [f.name for f in files if "<" in f.read_text(encoding="utf-8")]
    assert not offenders, (
        f"these templates emit markup, which the plain path cannot carry: {offenders}"
    )


async def test_reading_a_draft_does_not_make_it_edited(db_session: AsyncSession) -> None:
    """ACCEPTANCE 2 — FOCUS IS NOT AN EDIT, at the layer that can actually promise it.

    Nothing on a read path writes the format. The client rule (post only when the editor's content
    has moved) is the other half and lives in `message-dialog.test.tsx`; this is the half that holds
    even if a client posts on open.
    """
    loan_file, actor, draft, _first = await _draft(db_session)
    from app.models.user import User
    from app.services.email_draft import draft_for_reading

    reader = await db_session.get(User, actor)
    assert reader is not None
    await draft_for_reading(db_session, draft=draft, loan_file=loan_file, reader=reader)
    await refresh_if_stale(db_session, draft=draft, loan_file=loan_file)

    await db_session.refresh(draft)
    assert draft.body_format is BodyFormat.PLAIN


# --------------------------------------------------------------------------------------------- #
# Acceptance 3 — the first edit flips it, and the rewriters then refuse
# --------------------------------------------------------------------------------------------- #
async def test_saving_flips_the_format_and_is_the_edited_flag(db_session: AsyncSession) -> None:
    loan_file, _actor, draft, _first = await _draft(db_session)
    assert draft_body_edited(draft) is False

    await save_draft_body(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        body_html="<p>March statement only, not February.</p>",
    )

    await db_session.refresh(draft)
    assert draft.body_format is BodyFormat.HTML
    assert draft.body == "<p>March statement only, not February.</p>"
    # LP-851 reads the SAME fact, and there is no second column for it to disagree with.
    assert draft_body_edited(draft) is True


async def test_regenerate_refuses_an_authored_body_and_rewrites_a_plain_one(
    db_session: AsyncSession,
) -> None:
    """THE REFUSAL, WITH ITS CONTROL. The second half is what stops this passing against a
    `_regenerate` that does nothing at all."""
    loan_file, _actor, plain_draft, _need = await _draft(db_session)

    # CONTROL — the same call, on a plain body, really does rewrite.
    plain_draft.body = "something a template would never write"
    await db_session.flush()
    await _regenerate(db_session, draft=plain_draft, loan_file=loan_file)
    assert plain_draft.body != "something a template would never write"
    assert "Bank statements" in (plain_draft.body or "")

    # THE REFUSAL — same function, same draft, one column different.
    await save_draft_body(
        db_session,
        loan_file=loan_file,
        draft_id=plain_draft.id,
        body_html="<p>My own words.</p>",
    )
    with pytest.raises(DraftIsAuthored):
        await _regenerate(db_session, draft=plain_draft, loan_file=loan_file)
    await db_session.refresh(plain_draft)
    assert plain_draft.body == "<p>My own words.</p>"


async def test_refresh_if_stale_heals_a_plain_draft_and_leaves_an_authored_one(
    db_session: AsyncSession,
) -> None:
    """LP-848's heal, with its control.

    `refresh_if_stale`'s own docstring says it "becomes destructive and must move behind an explicit
    action" the day a save exists. It is a READ path, so there is no action to move it behind — a
    processor opening their own draft must simply not have it rewritten.
    """
    loan_file, _actor, draft, _first = await _draft(db_session)

    # CONTROL — a stale PLAIN draft is healed, so the fixture genuinely reaches the rewrite.
    _stale(draft)
    await db_session.flush()
    assert await refresh_if_stale(db_session, draft=draft, loan_file=loan_file) is True
    assert draft.template_version == TEMPLATES[TemplateKey(draft.template_key)].version

    # THE REFUSAL — same staleness, same call, on a body a person wrote.
    await save_draft_body(
        db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>Mine.</p>"
    )
    _stale(draft)
    await db_session.flush()
    assert await refresh_if_stale(db_session, draft=draft, loan_file=loan_file) is False
    await db_session.refresh(draft)
    assert draft.body == "<p>Mine.</p>"


async def test_attaching_a_link_refuses_an_authored_draft_and_works_on_a_plain_one(
    db_session: AsyncSession,
) -> None:
    """THE THIRD REWRITER, and the one with a cost that cannot be undone.

    The link's token is hashed in `upload_links`, so a link that never reaches the body is
    unrecoverable — LP-834's whole reason for the column. The refusal therefore comes BEFORE
    anything is minted or revoked, which the second half checks: the draft still carries the link
    it had.
    """
    loan_file, _actor, draft, _first = await _draft(db_session)

    # CONTROL — on a plain draft, the link is minted and reaches the words.
    await attach_upload_link(db_session, loan_file=loan_file, draft=draft)
    first_url = draft.upload_link_url
    assert first_url is not None
    assert "/upload/" in (draft.body or "")

    # THE REFUSAL — and nothing was minted or revoked on the way to it.
    await save_draft_body(
        db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>Mine.</p>"
    )
    with pytest.raises(DraftIsAuthored):
        await attach_upload_link(db_session, loan_file=loan_file, draft=draft)
    await db_session.refresh(draft)
    assert draft.upload_link_url == first_url, "a link was minted despite the refusal"
    assert draft.body == "<p>Mine.</p>"


async def test_removing_a_document_refuses_an_authored_draft_and_works_on_a_plain_one(
    db_session: AsyncSession,
) -> None:
    """Refused BEFORE the membership changes, or the draft would keep listing a document it no
    longer asks for."""
    from app.models.communication_needs_item import CommunicationNeedsItem

    loan_file, actor, draft, first = await _draft(db_session)
    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.APPEND,
    )

    # CONTROL — on a plain draft the line goes, and so does the membership row.
    await remove_need_from_draft(
        db_session, loan_file=loan_file, needs_item_id=second.id, communication_id=draft.id
    )
    assert "Pay stubs" not in (draft.body or "")

    await save_draft_body(
        db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>Mine.</p>"
    )
    with pytest.raises(DraftIsAuthored):
        await remove_need_from_draft(
            db_session, loan_file=loan_file, needs_item_id=first.id, communication_id=draft.id
        )
    # THE MEMBERSHIP IS INTACT — the refusal came first.
    assert (await db_session.get(CommunicationNeedsItem, (draft.id, first.id))) is not None


async def test_a_party_request_refuses_an_authored_draft(db_session: AsyncSession) -> None:
    """`build_party_draft` is a `_regenerate` caller and nothing on its path warns anybody, so it
    takes the refusal rather than the override.

    IT BECAME A CALLER IN LP-850's REVIEW, which is also what made it able to find a draft
    `email_draft` created — so this is the first ticket where an edited draft is reachable from it
    at all.
    """
    from app.models.loan_file_participant import LoanFileParticipant, ParticipantRole
    from app.services.party_requests import build_party_draft

    loan_file, actor = await _file_and_actor(db_session)
    db_session.add(
        LoanFileParticipant(
            loan_file_id=loan_file.id,
            role=ParticipantRole.TITLE,
            name="Acme Title",
            email="closings@acmetitle.example",
        )
    )
    await _need(db_session, loan_file, title="Title commitment", needs_type="title_commitment")
    await db_session.flush()

    # CONTROL — while it is plain, the build succeeds and the words name the document.
    draft = await build_party_draft(
        db_session,
        loan_file=loan_file,
        party=ResponsibleParty.TITLE,
        actor_user_id=actor,
    )
    assert "Title commitment" in (draft.body or "")

    await save_draft_body(
        db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>Mine.</p>"
    )
    await _need(db_session, loan_file, title="Payoff statement", needs_type="payoff_statement")
    await db_session.flush()
    with pytest.raises(DraftIsAuthored):
        await build_party_draft(
            db_session,
            loan_file=loan_file,
            party=ResponsibleParty.TITLE,
            actor_user_id=actor,
        )
    await db_session.refresh(draft)
    assert draft.body == "<p>Mine.</p>"


# --------------------------------------------------------------------------------------------- #
# The one override, and that it is behind the warning
# --------------------------------------------------------------------------------------------- #
async def test_the_warned_append_does_rewrite_an_authored_body(db_session: AsyncSession) -> None:
    """LP-851's Screen 5 says "Adding a document rewrites the message from the template, and your
    changes will be lost". THAT SENTENCE IS A CLAIM ABOUT THE SYSTEM, and this is what makes it
    true. An unconditional refusal would make it false in the worse direction — the membership
    would grow and the words would not, so the draft would ask for a document its own body never
    names and the borrower would never be asked.
    """
    loan_file, actor, draft, _first = await _draft(db_session)
    await save_draft_body(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        body_html="<p>March statement only, not February.</p>",
    )

    second = await _need(db_session, loan_file, title="Pay stubs", needs_type="pay_stub")
    update = await add_needs_to_draft(
        db_session,
        loan_file=loan_file,
        needs=[second],
        actor_user_id=actor,
        on_conflict=OnConflict.APPEND,
    )
    assert update.draft is not None and update.draft.id == draft.id

    await db_session.refresh(draft)
    assert "Pay stubs" in (draft.body or ""), "the document joined the draft and not its words"
    assert "March statement only" not in (draft.body or ""), (
        "the warning says the edit is lost; it was not"
    )
    # AND THE BODY IS THE TEMPLATE'S AGAIN, so the flag has to say so — otherwise the next request
    # would be refused over a body no processor wrote.
    assert draft.body_format is BodyFormat.PLAIN
    assert draft_body_edited(draft) is False


async def test_only_the_append_forces_a_rewrite() -> None:
    """WHICH CALL SITES HOLD THE OVERRIDE, asserted rather than left to a comment.

    `force=True` is the one way past the refusal, so a second caller acquiring it is LP-851's
    warning becoming false somewhere nobody warned anybody. Behavioural tests above cover each
    refusal; this covers the class — a new call site has to be added here deliberately.
    """
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[2] / "app"
    sites: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"_regenerate\(\s*db[^)]*\)", source):
            if "force=True" in match.group(0):
                sites.append(f"{path.relative_to(app_dir)}")
    assert sites == ["services/email_draft.py"], sites
    # AND THE SCAN CAN SEE A FORCE AT ALL. Without this it passes on a codebase where the parameter
    # was renamed and nothing forces anything, which is the silent-refusal bug.
    assert len(sites) == 1


# --------------------------------------------------------------------------------------------- #
# Saving — what may be saved, and what may not
# --------------------------------------------------------------------------------------------- #
async def test_a_sent_message_cannot_be_saved(db_session: AsyncSession) -> None:
    """LP-821's evidence record is what actually went out and must not change afterwards."""
    loan_file, _actor, draft, _first = await _draft(db_session)
    draft.status = CommunicationStatus.SENT
    await db_session.flush()

    with pytest.raises(DraftNotEditable):
        await save_draft_body(
            db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>x</p>"
        )


async def test_a_draft_on_another_file_cannot_be_saved(db_session: AsyncSession) -> None:
    _loan_file, _actor, draft, _first = await _draft(db_session)
    other_file, _other_actor = await _file_and_actor(db_session)

    with pytest.raises(DraftNotEditable):
        await save_draft_body(
            db_session, loan_file=other_file, draft_id=draft.id, body_html="<p>x</p>"
        )
    await db_session.refresh(draft)
    assert draft.body_format is BodyFormat.PLAIN


async def test_the_subject_rides_along_with_the_body(db_session: AsyncSession) -> None:
    loan_file, _actor, draft, _first = await _draft(db_session)
    await save_draft_body(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        body_html="<p>x</p>",
        subject="Documents for your loan",
    )
    await db_session.refresh(draft)
    assert draft.subject == "Documents for your loan"


async def test_omitting_the_subject_keeps_the_one_on_the_draft(db_session: AsyncSession) -> None:
    loan_file, _actor, draft, _first = await _draft(db_session)
    before = draft.subject
    await save_draft_body(db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>x</p>")
    await db_session.refresh(draft)
    assert draft.subject == before


async def test_the_send_cannot_put_unsanitised_markup_in_the_column(
    db_session: AsyncSession,
) -> None:
    """LP-853 REVIEW — THE FIFTH BODY WRITER, and the one the allowlist was not applied to.

    `sanitise.py` states the guarantee the modal relies on by name: the column "never holds anything
    that was not allowed", so every reader "inherits the guarantee without knowing the rule".
    `message-dialog.tsx` renders an `html` row through `dangerouslySetInnerHTML` on exactly that
    basis.

    `send_draft` writes the same column from a client-supplied body and does not change
    `body_format`, so before this guard a send could store `<img src=x onerror=...>` on a row marked
    `html` — and the next person in the company to open the sent message ran it. Measured, then
    fixed: a stored XSS across a user boundary.
    """
    from app.services.email_send import send_draft

    loan_file, actor, draft, _first = await _draft(db_session)
    await save_draft_body(
        db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>mine</p>"
    )
    await db_session.refresh(draft)
    assert draft.body_format is BodyFormat.HTML

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="s@example.com",
        body='<p>Keep this.</p><img src=x onerror="alert(1)"><script>alert(2)</script>',
        subject=draft.subject,
        approver_user_id=actor,
    )
    await db_session.refresh(draft)
    stored = draft.body or ""

    assert "onerror" not in stored, f"the send stored an event handler: {stored!r}"
    assert "<script" not in stored, f"the send stored a script tag: {stored!r}"
    assert "<img" not in stored, f"the send stored an img tag: {stored!r}"
    # THE POSITIVE CONTROL. Without it this passes on a send that stored nothing at all, or that
    # escaped the processor's own formatting into unreadable source.
    assert "<p>Keep this.</p>" in stored, (
        f"the allowlisted markup the processor wrote did not survive: {stored!r}"
    )


async def test_a_plain_send_is_not_touched_by_the_allowlist(db_session: AsyncSession) -> None:
    """THE OTHER HALF. A plain row is escaped by `emailBodyToHtml` at render — LP-844's
    escape-first argument — and must keep its newlines, which the sanitiser would not preserve."""
    from app.services.email_send import send_draft

    loan_file, actor, draft, _first = await _draft(db_session)
    assert draft.body_format is BodyFormat.PLAIN

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="s@example.com",
        body="Hello Sarah,\n\nPlease send the statements.\n\nDana",
        subject=draft.subject,
        approver_user_id=actor,
    )
    await db_session.refresh(draft)

    assert "Hello Sarah,\n\nPlease send the statements." in (draft.body or "")
    assert draft.body_format is BodyFormat.PLAIN


async def test_an_authored_body_gets_its_loan_tag_as_a_paragraph(
    db_session: AsyncSession,
) -> None:
    """LP-853 REVIEW — THE TAG IN THE BODY'S OWN LANGUAGE.

    Every body was plain text until this ticket, so `\n\n[LF-XXXX]` put the tag on its own line. In
    HTML a newline is whitespace: the tag rendered inline, running on from the processor's last
    sentence in the message the borrower reads.
    """
    from app.services.email_send import send_draft

    loan_file, actor, draft, _first = await _draft(db_session)
    await save_draft_body(
        db_session, loan_file=loan_file, draft_id=draft.id, body_html="<p>Only March.</p>"
    )
    await db_session.refresh(draft)

    await send_draft(
        db_session,
        loan_file=loan_file,
        draft_id=draft.id,
        recipient="s@example.com",
        body="<p>Only March.</p>",
        subject=draft.subject,
        approver_user_id=actor,
    )
    await db_session.refresh(draft)
    stored = draft.body or ""

    tag = f"[{loan_file.display_id}]"
    assert f"<p>{tag}</p>" in stored, f"the tag is not a paragraph: {stored!r}"
    assert f"\n\n{tag}" not in stored, f"the plain-text tag survived into an html body: {stored!r}"
    # THE THREADING MATCH IS ON THE TEXT, and it has to keep working — `inbound_routing` finds the
    # file by this tag, so a change of spelling that lost it would silently orphan every reply.
    assert tag in stored
