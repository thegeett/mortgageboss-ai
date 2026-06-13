"""JWT creation and verification utilities (PyJWT, HS256) — LP-22.

Tokens carry MINIMAL standard claims: ``sub`` (user UUID as a string),
``type`` (access/refresh), ``exp`` (expiry), and ``iat`` (issued-at). They
deliberately carry NO role, email, company, or other PII. JWTs are *signed,
not encrypted*, so the payload is readable by anyone holding the token;
encoding authorization data (role, is_active) would let a long-lived token
assert stale permissions. Authorization is therefore looked up live from the
database (LP-24) and never trusted from the token — the token proves identity
only.

These are pure functions: no FastAPI dependencies, no database access. The
login/refresh endpoints (LP-23) and the current-user dependency (LP-24) build
on them. Verification distinguishes three failure modes via distinct exception
classes — expired, invalid (bad signature/malformed/missing claims), and
wrong-type — so LP-24 can map each to the right HTTP response.

All timestamps are timezone-aware UTC. PyJWT performs the ``exp`` comparison
itself on decode, raising :class:`jwt.ExpiredSignatureError` for expired tokens.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

import jwt
from pydantic import BaseModel

from app.core.config import settings


class TokenType(StrEnum):
    """The kind of token, recorded in the ``type`` claim."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    """The verified, typed result of decoding a token.

    Only the fields the rest of the system needs: who the token is for
    (``subject``) and which kind it is (``token_type``).
    """

    subject: UUID
    token_type: TokenType


class TokenError(Exception):
    """Base class for token verification errors."""


class TokenExpiredError(TokenError):
    """The token is well-formed and correctly signed but has expired."""


class InvalidTokenError(TokenError):
    """The token is malformed, tampered, signed with the wrong key, or is
    missing required claims / has an unparseable subject."""


class WrongTokenTypeError(TokenError):
    """The token is valid but of the wrong type (e.g. a refresh token supplied
    where an access token was expected)."""


def _create_token(
    subject: str | UUID,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    """Build and sign a token with the minimal standard claim set."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(subject: str | UUID, expires_delta: timedelta | None = None) -> str:
    """Create a signed access token for ``subject`` (a user UUID).

    The lifetime defaults to ``settings.jwt_access_token_expire_minutes`` and
    can be overridden via ``expires_delta`` (e.g. a negative delta in tests to
    produce an already-expired token).
    """
    delta = expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes)
    return _create_token(subject, TokenType.ACCESS, delta)


def create_refresh_token(subject: str | UUID, expires_delta: timedelta | None = None) -> str:
    """Create a signed refresh token for ``subject`` (a user UUID).

    The lifetime defaults to ``settings.jwt_refresh_token_expire_days`` and can
    be overridden via ``expires_delta``.
    """
    delta = expires_delta or timedelta(days=settings.jwt_refresh_token_expire_days)
    return _create_token(subject, TokenType.REFRESH, delta)


def verify_token(token: str, expected_type: TokenType) -> TokenPayload:
    """Verify a token's signature, expiry, and type; return a typed payload.

    Raises:
        TokenExpiredError: the signature is valid but the token has expired.
        InvalidTokenError: bad signature, malformed token, wrong signing key,
            missing required claims, or a non-UUID subject.
        WrongTokenTypeError: a valid token whose ``type`` is not
            ``expected_type``.
    """
    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Token is invalid") from exc

    raw_type = decoded.get("type")
    raw_sub = decoded.get("sub")
    if raw_type is None or raw_sub is None:
        raise InvalidTokenError("Token is missing required claims")

    if raw_type != expected_type.value:
        raise WrongTokenTypeError(f"Expected {expected_type.value} token, got {raw_type}")

    try:
        subject = UUID(str(raw_sub))
    except (ValueError, AttributeError) as exc:
        raise InvalidTokenError("Token subject is not a valid UUID") from exc

    return TokenPayload(subject=subject, token_type=TokenType(raw_type))
