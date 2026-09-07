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
from app.services.email_draft import add_needs_to_draft
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
    await add_needs_to_draft(db_session, loan_file=loan_file, needs=[need], actor_user_id=actor)

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
