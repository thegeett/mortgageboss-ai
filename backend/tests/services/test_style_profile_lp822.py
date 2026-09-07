"""LP-822 — the writing voice a draft is composed in, and the cache key that keeps it separate.

The ticket exists to resolve a collision, not to add a field. Spec 4.1 wants drafts to sound like
the processor; LP-810 scopes the per-draft fact bundle to almost nothing because bug-008 showed a
wide bundle rewording every draft whenever anything in it changed. The resolution is two caches
keyed apart — so the test that matters most here is the pair asserting that editing a voice moves
the style key and that a voice which did not change does not move it.

The other half is containment. An exemplar is put in front of the model on EVERY draft, for every
borrower, so a borrower's details left in one can surface in another borrower's email.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.models import Company, User, UserRole
from app.services.style_profile import (
    NEUTRAL_STYLE,
    InvalidExemplar,
    ResolvedStyle,
    resolve_style,
    set_style_profile,
    validate_exemplars,
)
from sqlalchemy.ext.asyncio import AsyncSession


async def _user(db: AsyncSession) -> User:
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
    return user


# --------------------------------------------------------------------------------------------- #
# The default, and the bit that says it is the default
# --------------------------------------------------------------------------------------------- #
async def test_a_user_with_no_profile_gets_the_neutral_voice(db_session: AsyncSession) -> None:
    """Never `None`, so no caller branches and nobody sends with a half-populated voice."""
    user = await _user(db_session)

    style = await resolve_style(db_session, user_id=user.id)

    assert style == NEUTRAL_STYLE
    assert style.is_default is True
    assert style.greeting and style.closing


async def test_a_saved_profile_is_not_marked_default(db_session: AsyncSession) -> None:
    """The positive control. Without it, `is_default=True` on everything would satisfy the test
    above — and the spec's failure mode is precisely a drafter writing in generic voice while
    nothing says so."""
    user = await _user(db_session)
    await set_style_profile(
        db_session,
        user_id=user.id,
        greeting="Hi $borrower_first_name,",
        closing="Best,",
        signature_block="Priya\nSenior Processor",
    )

    style = await resolve_style(db_session, user_id=user.id)

    assert style.is_default is False
    assert style.greeting == "Hi $borrower_first_name,"
    assert style.signature_block == "Priya\nSenior Processor"


async def test_saving_twice_replaces_rather_than_accumulates(db_session: AsyncSession) -> None:
    """One row per user. Two would make the drafter choose, and there is no basis on which to."""
    user = await _user(db_session)
    await set_style_profile(db_session, user_id=user.id, greeting="Hi,", closing="Best,")
    await set_style_profile(db_session, user_id=user.id, greeting="Hello,", closing="Thanks,")

    style = await resolve_style(db_session, user_id=user.id)

    assert style.greeting == "Hello,"
    assert style.closing == "Thanks,"


# --------------------------------------------------------------------------------------------- #
# The fingerprint — the whole point of the ticket
# --------------------------------------------------------------------------------------------- #
def _style(**overrides: object) -> ResolvedStyle:
    base = {
        "greeting": "Hello $borrower_first_name,",
        "closing": "Thanks,",
        "signature_block": "Priya",
        "exemplars": (),
        "is_default": False,
    }
    return ResolvedStyle(**{**base, **overrides})  # type: ignore[arg-type]


def test_editing_the_voice_moves_the_style_key() -> None:
    """What LP-810 caches style on. If this did not move, a processor could edit their signature
    and keep receiving drafts in the old one with nothing to show why."""
    assert _style().fingerprint != _style(signature_block="Priya S.").fingerprint
    assert _style().fingerprint != _style(greeting="Hi,").fingerprint
    assert _style().fingerprint != _style(exemplars=("a sample",)).fingerprint


def test_an_unchanged_voice_keeps_its_key() -> None:
    """The other half, and the reason the hash is over CONTENT and not `updated_at`: a save that
    changed nothing must not invalidate a cache."""
    assert _style().fingerprint == _style().fingerprint


def test_the_key_ignores_whether_it_is_the_default() -> None:
    """`is_default` is a label for a UI, not part of the voice. Two identical voices are one cache
    entry whether or not one of them was filled in by hand."""
    assert _style(is_default=True).fingerprint == _style(is_default=False).fingerprint


def test_the_neutral_voice_has_its_own_key() -> None:
    """So a user who fills in a profile gets a different key with no special case anywhere."""
    assert NEUTRAL_STYLE.fingerprint != _style().fingerprint


def test_the_key_separates_fields_rather_than_concatenating_them() -> None:
    """Two voices that concatenate to the same string are still two voices. Without a separator,
    greeting "AB"/closing "C" and greeting "A"/closing "BC" would share a cache entry — so one
    processor's drafts would be written in another's voice."""
    assert (
        _style(greeting="AB", closing="C").fingerprint
        != _style(greeting="A", closing="BC").fingerprint
    )


# --------------------------------------------------------------------------------------------- #
# Exemplar containment
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("exemplar", "expected"),
    [
        ("Please send the W-2. Ref 123-45-6789 thanks.", "Social Security number"),
        ("Reply to priya@example.com when ready.", "email address"),
        ("Call me on (555) 123-4567 with questions.", "phone number"),
        ("Your loan 400123456789 is progressing.", "account or loan number"),
    ],
)
async def test_an_exemplar_carrying_an_identifier_shape_is_refused(
    exemplar: str, expected: str
) -> None:
    """The spec asks Priya for her ACTUAL SENDS, and an actual send names a borrower and what they
    owe. This is a tripwire for the shapes it can recognise, not a guarantee — a name has no shape —
    but the shapes it does catch are the ones most often left in a pasted email."""
    with pytest.raises(InvalidExemplar, match=expected):
        validate_exemplars((exemplar,))


def test_the_refusal_does_not_quote_what_it_found() -> None:
    """The message travels into logs. An error about a leaked identifier must not be the thing that
    leaks it."""
    with pytest.raises(InvalidExemplar) as caught:
        validate_exemplars(("Ref 123-45-6789 thanks.",))
    assert "123-45-6789" not in str(caught.value)


def test_ordinary_prose_about_tone_is_not_refused() -> None:
    """The control for every refusal above. A guard that turned away legitimate text would be green
    by construction, and nobody would find out until a profile could not be saved.

    Every number here is one a real request email carries and a narrower digit rule would reject:
    an unseparated amount, a tax year, a form number. An earlier version of this test used only
    "$12,500.00" and claimed to pin the 8-digit threshold — it did not. The commas break the run, so
    widening the rule to four digits left this test green. A control has to contain the thing it
    says it protects."""
    text = (
        "Hi Sam, just a quick nudge on the bank statements - no rush at all. "
        "We still need $12500 documented before Friday, and the 2024 W-2 rather than the 1099. "
        "Thanks so much!"
    )
    assert validate_exemplars((text,)) == (text,)


@pytest.mark.parametrize(
    ("digits", "accepted"),
    [(7, True), (8, False)],
)
def test_the_loan_number_threshold_is_where_it_says_it_is(digits: int, accepted: bool) -> None:
    """The boundary itself, both sides. Without the accepted case the rule could be widened to any
    length and every other test here would stay green; without the refused case it could be dropped
    entirely.

    Seven digits is still a plausible figure in prose. Eight consecutive is not something anyone
    writes about tone, which is why that is where the line sits."""
    exemplar = f"Reference {'9' * digits} for the file."
    if accepted:
        assert validate_exemplars((exemplar,)) == (exemplar,)
    else:
        with pytest.raises(InvalidExemplar, match="account or loan number"):
            validate_exemplars((exemplar,))


def test_too_many_exemplars_are_refused() -> None:
    """More is not a richer voice; it is a longer prompt and more places for a detail to hide."""
    with pytest.raises(InvalidExemplar, match="at most 3"):
        validate_exemplars(("a", "b", "c", "d"))


def test_an_overlong_exemplar_is_refused() -> None:
    """A paragraph shows voice as well as a whole thread does, and a cap is containment too."""
    with pytest.raises(InvalidExemplar, match="limit is 1200"):
        validate_exemplars(("x" * 1201,))


def test_an_empty_exemplar_is_refused() -> None:
    with pytest.raises(InvalidExemplar, match="empty"):
        validate_exemplars(("   ",))


async def test_a_bad_exemplar_is_refused_before_anything_is_written(
    db_session: AsyncSession,
) -> None:
    """Validation runs BEFORE the upsert. A half-saved profile would leave the drafter with a voice
    nobody chose, which is worse than the default it would otherwise have used."""
    user = await _user(db_session)

    with pytest.raises(InvalidExemplar):
        await set_style_profile(
            db_session,
            user_id=user.id,
            greeting="Hi,",
            closing="Best,",
            exemplars=("Call (555) 123-4567.",),
        )

    assert (await resolve_style(db_session, user_id=user.id)).is_default is True


async def test_a_profile_needs_both_a_greeting_and_a_closing(db_session: AsyncSession) -> None:
    """A voice missing either is a half-populated voice, which is the thing `resolve_style`
    returning a value object exists to make impossible."""
    user = await _user(db_session)
    with pytest.raises(InvalidExemplar, match="greeting and a closing"):
        await set_style_profile(db_session, user_id=user.id, greeting="  ", closing="Best,")
