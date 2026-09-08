"""LP-810 at the layer a draft is actually built — flag off, flag on, cache, and fallback.

The guards are unit-tested beside the engine. What this file asserts is the wiring, which is where
the flag's promise lives: with it OFF the plain path is a COMPLETE email rather than a degraded one,
and with it ON a rejected composition falls back to that same complete email rather than to a gap.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.ai.email_draft import DraftComposition
from app.communications.templates import plain_framing
from app.models import Company, LoanProgram
from app.models.email_draft_prose import EmailDraftProse
from app.models.needs_item import NeedsItem, NeedsItemOrigin
from app.services.email_draft import add_needs_to_draft, compose_open_draft_prose
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

_COMPOSED = DraftComposition(
    opening="A quick note about your file.",
    bridge="These are the items still outstanding:",
    closing="Reply here with anything you would like explained.",
)


async def _setup(db: AsyncSession):
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
    need = NeedsItem(
        loan_file_id=loan_file.id,
        title="Bank statements",
        needs_type="bank_statement",
        origin=NeedsItemOrigin.FINDING,
    )
    db.add(need)
    await db.flush()
    return loan_file, user.id, need


async def test_with_the_flag_off_the_plain_framing_is_used_and_no_model_is_called(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag ships off, so this is the path every draft takes today. `compose` is replaced with a
    function that fails the test if called — asserting only on the OUTPUT would pass while the model
    was called and its result thrown away, which is the expensive version of the same bug."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_draft_enabled", False)

    async def _never(*_args: object, **_kwargs: object) -> DraftComposition:
        raise AssertionError("the model was called with the flag off")

    monkeypatch.setattr("app.services.email_draft.compose", _never)
    loan_file, actor, need = await _setup(db_session)

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert plain_framing().opening in result.draft.body
    assert _COMPOSED.opening not in result.draft.body


async def test_with_the_flag_on_the_composed_framing_reaches_the_draft(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_draft_enabled", True)

    async def _compose(*_args: object, **_kwargs: object) -> DraftComposition:
        return _COMPOSED

    monkeypatch.setattr("app.services.email_draft.compose", _compose)
    loan_file, actor, need = await _setup(db_session)

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    # LP-809 review — THE ADD NO LONGER COMPOSES; the worker does, and this is that worker's call.
    # The draft is a complete email in between, which the assertion below the composition checks.
    assert plain_framing().opening in result.draft.body  # what the processor sees immediately
    assert await compose_open_draft_prose(db_session, loan_file=loan_file) is True

    assert _COMPOSED.opening in result.draft.body
    assert plain_framing().opening not in result.draft.body
    # The structure the template owns is untouched — the model replaced three sentences, not the email.
    assert loan_file.get_inbox_address() in result.draft.body
    assert "Every page of each statement" in result.draft.body


async def test_a_refused_composition_falls_back_to_a_complete_email(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`compose` returns None for every failure — transport, truncation, malformed, guard rejection.
    The fallback has to be the whole plain email, not a gap where the framing was: a draft missing
    its opening line still looks like a draft, and a processor might send it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_draft_enabled", True)

    async def _refused(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.services.email_draft.compose", _refused)
    loan_file, actor, need = await _setup(db_session)

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    assert await compose_open_draft_prose(db_session, loan_file=loan_file) is False

    framing = plain_framing()
    assert framing.opening in result.draft.body
    assert framing.bridge in result.draft.body
    assert framing.closing in result.draft.body
    assert loan_file.get_inbox_address() in result.draft.body


async def test_a_second_regeneration_reuses_the_cache_rather_than_recomposing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Determinism, and the reason the cache exists. LP-809 regenerates on every add and remove, so
    without this a processor who adds a document watches the other paragraphs reword under their
    cursor — bug-008 on text a person is editing.

    Counted, not inferred: the call counter is what distinguishes "cached" from "composed the same
    thing twice", and only one of those is what the ticket claims."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_draft_enabled", True)
    calls = 0

    async def _counting(*_args: object, **_kwargs: object) -> DraftComposition:
        nonlocal calls
        calls += 1
        return _COMPOSED

    monkeypatch.setattr("app.services.email_draft.compose", _counting)
    loan_file, actor, need = await _setup(db_session)

    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)
    assert await compose_open_draft_prose(db_session, loan_file=loan_file) is True
    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)
    # The second enqueue for the same draft: it must find the cache warm and do nothing. This is
    # what makes enqueueing on every request-docs click harmless.
    assert await compose_open_draft_prose(db_session, loan_file=loan_file) is False

    assert calls == 1
    cached = await db_session.scalar(select(func.count()).select_from(EmailDraftProse))
    assert cached == 1


async def test_a_cached_composition_is_re_checked_on_the_way_out(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-601's lesson, which cost a shipped defect the first time. `compose` runs only on a cache
    MISS, so a composition stored before a guard existed would be served forever and the guard would
    never see it. The cache is filtered through the same `rejection_reason` on the way out.

    Simulated by storing a row that today's guards refuse — which is exactly the state a pre-guard
    row would be in."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_draft_enabled", True)

    async def _never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("should not recompose; the cached row should simply be refused")

    loan_file, actor, need = await _setup(db_session)

    # Prime the cache with the key this draft will look up, holding text a guard now refuses.
    from app.services.email_draft import _draft_facts

    key = _draft_facts(loan_file, [need]).cache_key()
    db_session.add(
        EmailDraftProse(
            fact_hash=key,
            body="Good news, your loan is approved.\n\nHere is the list:\n\nAsk us anything.",
            template_key="initial_documentation_request",
        )
    )
    await db_session.flush()
    monkeypatch.setattr("app.services.email_draft.compose", _never)

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )

    assert "approved" not in result.draft.body
    assert plain_framing().opening in result.draft.body


async def test_the_add_itself_never_calls_the_model_even_with_the_flag_on(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-809 review — a processor's click must not carry an Anthropic round-trip.

    `add_needs_to_draft` regenerates the body, and both request-docs routes call it synchronously
    inside the HTTP request. While `_composed_framing` composed there, every click waited on the
    model — and missed the cache every time, because the key is built from the requested labels and
    every add changes them. CLAUDE.md: long work runs on Celery, not in the request.

    Asserted by making `compose` fail the test if reached, not by timing: the flag is ON here, so a
    version that composed in the request would be caught rather than merely be slow. The positive
    control is the second half — the SAME `compose` is reached, and reached once, through the worker
    path, so this cannot pass by the model having become unreachable.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_draft_enabled", True)
    in_request = True

    async def _guarded(*_args: object, **_kwargs: object) -> DraftComposition:
        if in_request:
            raise AssertionError("the model was called inside the request path")
        return _COMPOSED

    monkeypatch.setattr("app.services.email_draft.compose", _guarded)
    loan_file, actor, need = await _setup(db_session)

    result = await add_needs_to_draft(
        db_session, loan_file=loan_file, needs=[need], actor_user_id=actor
    )
    assert plain_framing().opening in result.draft.body

    in_request = False
    assert await compose_open_draft_prose(db_session, loan_file=loan_file) is True
    assert _COMPOSED.opening in result.draft.body


async def test_the_compose_is_handed_the_draft_the_request_made(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LP-833 REVIEW — the compose asked for "this file's newest open draft" while holding one.

    `compose_request` creates a draft and then called `compose_open_draft_prose(db,
    loan_file=loan_file)`, which resolves the newest. Those are the same row today only because
    nothing runs between the two statements — a property of the current code rather than of the
    function, and the same shape LP-832's review found in `remove_need_from_draft`. The row lock
    covers a concurrent request; it does not cover a future caller inside this transaction.

    ASSERTED ON THE ARGUMENT, and the first version of this test was not. Asserting the OUTCOME —
    that each request's framing lands on its own draft — is true either way, because the draft a
    request creates IS the newest at the moment it composes. That test passed under the mutant that
    dropped the parameter, which makes it a statement about today's call order rather than about the
    wiring. The divergence it defends against cannot be produced from outside, so the honest
    assertion is that the caller hands over the row it means.
    """
    from app.core.config import settings
    from app.services import email_draft
    from app.services.email_draft import compose_request

    monkeypatch.setattr(settings, "email_draft_enabled", True)
    seen: list[object] = []
    real = email_draft.compose_open_draft_prose

    async def _spy(db, *, loan_file, draft=None):  # type: ignore[no-untyped-def]
        seen.append(draft)
        return await real(db, loan_file=loan_file, draft=draft)

    async def _compose(*_args: object, **_kwargs: object) -> DraftComposition:
        return _COMPOSED

    monkeypatch.setattr("app.services.email_draft.compose", _compose)
    monkeypatch.setattr(email_draft, "compose_open_draft_prose", _spy)
    loan_file, actor, _need = await _setup(db_session)

    result = await compose_request(
        db_session, loan_file=loan_file, document_types=["bank_statement"], actor_user_id=actor
    )

    assert result.update.draft is not None
    assert seen == [result.update.draft], (
        "the compose was not handed the draft this request created — it resolved one instead"
    )
    # The control: it did compose, so the assertion above is not being satisfied by a call that
    # never happened.
    assert result.composed_by_model is True
    assert _COMPOSED.opening in (result.update.draft.body or "")
