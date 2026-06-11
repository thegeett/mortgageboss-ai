"""Tests for JWT creation and verification utilities (LP-22).

Exercises :mod:`app.core.jwt` directly (pure functions, no database): that
access and refresh tokens round-trip and recover the correct subject, that the
subject survives whether passed as a ``UUID`` or a ``str``, that the three
failure modes raise distinct typed errors (expired / invalid / wrong-type),
and — importantly — that the token payload carries only the minimal standard
claims and NO role/email/company PII.
"""

from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from app.core.config import settings
from app.core.jwt import (
    InvalidTokenError,
    TokenExpiredError,
    TokenType,
    WrongTokenTypeError,
    create_access_token,
    create_refresh_token,
    verify_token,
)


def test_access_token_round_trips() -> None:
    """An access token verifies as ACCESS and recovers the subject."""
    subject = uuid4()
    token = create_access_token(subject)
    payload = verify_token(token, TokenType.ACCESS)
    assert payload.subject == subject
    assert payload.token_type == TokenType.ACCESS


def test_refresh_token_round_trips() -> None:
    """A refresh token verifies as REFRESH and recovers the subject."""
    subject = uuid4()
    token = create_refresh_token(subject)
    payload = verify_token(token, TokenType.REFRESH)
    assert payload.subject == subject
    assert payload.token_type == TokenType.REFRESH


def test_subject_round_trips_as_uuid_or_str() -> None:
    """The subject recovers identically whether passed as a UUID or a str."""
    subject = uuid4()
    from_uuid = verify_token(create_access_token(subject), TokenType.ACCESS)
    from_str = verify_token(create_access_token(str(subject)), TokenType.ACCESS)
    assert from_uuid.subject == subject
    assert from_str.subject == subject


def test_access_token_verified_as_refresh_raises_wrong_type() -> None:
    """An access token checked as REFRESH raises WrongTokenTypeError."""
    token = create_access_token(uuid4())
    with pytest.raises(WrongTokenTypeError):
        verify_token(token, TokenType.REFRESH)


def test_refresh_token_verified_as_access_raises_wrong_type() -> None:
    """A refresh token checked as ACCESS raises WrongTokenTypeError."""
    token = create_refresh_token(uuid4())
    with pytest.raises(WrongTokenTypeError):
        verify_token(token, TokenType.ACCESS)


def test_expired_token_raises_expired_error() -> None:
    """A token with a past expiry raises TokenExpiredError (distinct error)."""
    token = create_access_token(uuid4(), expires_delta=timedelta(seconds=-1))
    with pytest.raises(TokenExpiredError):
        verify_token(token, TokenType.ACCESS)


def test_garbage_token_raises_invalid_error() -> None:
    """A malformed/garbage token raises InvalidTokenError."""
    with pytest.raises(InvalidTokenError):
        verify_token("not.a.jwt", TokenType.ACCESS)


def test_tampered_token_raises_invalid_error() -> None:
    """Flipping a character in the signature raises InvalidTokenError."""
    token = create_access_token(uuid4())
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(InvalidTokenError):
        verify_token(tampered, TokenType.ACCESS)


def test_token_signed_with_different_secret_raises_invalid_error() -> None:
    """A token signed with a different key fails signature verification."""
    other_secret = "a" * 64  # different from settings.jwt_secret_key
    forged = jwt.encode(
        {"sub": str(uuid4()), "type": "access"},
        other_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        verify_token(forged, TokenType.ACCESS)


def test_payload_has_minimal_claims_and_no_pii() -> None:
    """The token carries sub/type/exp/iat and NO role/email/company PII.

    Decoded with verification so we assert against the genuine signed payload.
    """
    subject = uuid4()
    token = create_access_token(subject)
    decoded = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert set(decoded.keys()) == {"sub", "type", "exp", "iat"}
    assert decoded["sub"] == str(subject)
    assert decoded["type"] == "access"
    for forbidden in ("role", "email", "company_id", "company", "is_active"):
        assert forbidden not in decoded


def test_missing_claims_raise_invalid_error() -> None:
    """A correctly-signed token missing required claims raises InvalidTokenError."""
    token = jwt.encode(
        {"foo": "bar"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        verify_token(token, TokenType.ACCESS)


def test_non_uuid_subject_raises_invalid_error() -> None:
    """A valid token whose subject is not a UUID raises InvalidTokenError."""
    token = jwt.encode(
        {"sub": "not-a-uuid", "type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        verify_token(token, TokenType.ACCESS)
