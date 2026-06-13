"""Tests for the authentication service (LP-23).

Exercises :mod:`app.services.auth` against the rollback ``db_session`` fixture:
that valid credentials return the user, that an unknown email and a wrong
password raise the *identical* generic error (anti-enumeration), that an
inactive user is rejected distinctly, and that ``get_user_by_id`` round-trips.
"""

import pytest
from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.services.auth import (
    AuthenticationError,
    InactiveUserError,
    authenticate_user,
    get_user_by_id,
)
from sqlalchemy.ext.asyncio import AsyncSession

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
WRONG_PASSWORD = "Tr0ub4dor&3"  # pragma: allowlist secret


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str = "processor@acme.test",
    password: str = PASSWORD,
    is_active: bool = True,
) -> User:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email=email,
        hashed_password=hash_password(password),
        first_name="Pat",
        last_name="Processor",
        role=UserRole.PROCESSOR,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_authenticate_returns_user_for_valid_credentials(
    db_session: AsyncSession,
) -> None:
    """Correct email + password returns the matching user."""
    user = await _make_user(db_session)
    result = await authenticate_user(db_session, email="processor@acme.test", password=PASSWORD)
    assert result.id == user.id


async def test_unknown_email_and_wrong_password_raise_identical_error(
    db_session: AsyncSession,
) -> None:
    """Anti-enumeration: unknown email and wrong password are indistinguishable.

    Same exception type AND same message, so a caller can never learn whether an
    email is registered.
    """
    await _make_user(db_session, email="known@acme.test")

    with pytest.raises(AuthenticationError) as wrong_pw:
        await authenticate_user(db_session, email="known@acme.test", password=WRONG_PASSWORD)
    with pytest.raises(AuthenticationError) as unknown_email:
        await authenticate_user(db_session, email="nobody@acme.test", password=PASSWORD)

    assert type(wrong_pw.value) is type(unknown_email.value)
    assert str(wrong_pw.value) == str(unknown_email.value)


async def test_inactive_user_raises_inactive_error(db_session: AsyncSession) -> None:
    """A valid-credential but inactive account raises InactiveUserError.

    Distinct from AuthenticationError: the credentials are correct, so this is
    not an enumeration concern (the caller already proved they know the password).
    """
    await _make_user(db_session, email="inactive@acme.test", is_active=False)
    with pytest.raises(InactiveUserError):
        await authenticate_user(db_session, email="inactive@acme.test", password=PASSWORD)


async def test_get_user_by_id_returns_user_then_none(
    db_session: AsyncSession,
) -> None:
    """get_user_by_id returns the user for a known id and None otherwise."""
    user = await _make_user(db_session)
    assert (await get_user_by_id(db_session, user.id)) is not None

    from uuid import uuid4

    assert (await get_user_by_id(db_session, uuid4())) is None
