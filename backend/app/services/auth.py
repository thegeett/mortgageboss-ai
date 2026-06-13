"""Authentication service — credential verification (LP-23).

Pure data-layer auth logic: look a user up by email, verify their password, and
check that the account is active. No HTTP here — the endpoints (:mod:`app.api.auth`)
translate these results and the raised errors into responses, so this stays
unit-testable against the database alone.

**Anti-enumeration:** an unknown email and a wrong password raise the *same*
:class:`AuthenticationError` with the same message, so a caller can never tell
whether an email is registered. To also avoid a *timing* signal (a missing user
returns instantly; a present one pays for a bcrypt compare), we verify the
supplied password against a throwaway hash when the user is absent, so both
paths do one bcrypt comparison.
"""

from functools import lru_cache
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User


class AuthenticationError(Exception):
    """Generic authentication failure (unknown email OR wrong password).

    Deliberately does NOT distinguish the two cases, so the response can't be
    used to discover whether an email is registered (anti-enumeration).
    """


class InactiveUserError(Exception):
    """The credentials are valid but the user account is inactive."""


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A bcrypt hash of a throwaway value, computed once.

    Used to spend a comparable amount of time hashing when the email is unknown,
    so the unknown-email path is not measurably faster than the wrong-password
    path. The plaintext is irrelevant — nothing ever verifies against it
    successfully.
    """
    return hash_password("dummy-password-for-constant-time-auth")  # pragma: allowlist secret


async def authenticate_user(db: AsyncSession, *, email: str, password: str) -> User:
    """Verify credentials and return the user.

    Raises:
        AuthenticationError: the email is unknown OR the password is wrong — the
            same error for both, by design (anti-enumeration).
        InactiveUserError: the credentials are valid but the account is inactive.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Spend the same work as a real verify so timing doesn't reveal that the
        # email is unknown, then fail with the identical generic error.
        verify_password(password, _dummy_password_hash())
        raise AuthenticationError("Invalid email or password")

    if not verify_password(password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")

    if not user.is_active:
        raise InactiveUserError("User account is inactive")

    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    """Fetch a user by id, or ``None`` if no such user exists.

    Used by the refresh endpoint to re-load the user named in a refresh token
    and re-check ``is_active`` before issuing a new access token.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
