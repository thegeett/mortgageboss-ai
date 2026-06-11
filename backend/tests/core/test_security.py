"""Tests for password hashing and the minimal password policy (LP-22).

Exercises :mod:`app.core.security` directly (pure functions, no database):
that a hash is not the plaintext, that bcrypt's per-password salt makes the
same password hash differently while both still verify, that verification
succeeds only for the correct password, that a malformed hash fails closed
(returns ``False`` rather than raising), and that the length policy rejects
too-short and too-long passwords while accepting a valid one.
"""

import pytest
from app.core.security import (
    MAX_PASSWORD_BYTES,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    validate_password_strength,
    verify_password,
)

PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
WRONG_PASSWORD = "Tr0ub4dor&3"  # pragma: allowlist secret


def test_hash_is_not_plaintext() -> None:
    """The hash must not be (or contain) the plaintext password."""
    hashed = hash_password(PASSWORD)
    assert hashed != PASSWORD
    assert PASSWORD not in hashed


def test_same_password_hashes_differently_but_both_verify() -> None:
    """Per-password salt: equal passwords -> unequal hashes, both verifying."""
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert verify_password(PASSWORD, second)


def test_verify_true_for_correct_password() -> None:
    """verify_password returns True for the password that was hashed."""
    hashed = hash_password(PASSWORD)
    assert verify_password(PASSWORD, hashed) is True


def test_verify_false_for_incorrect_password() -> None:
    """verify_password returns False for a different password."""
    hashed = hash_password(PASSWORD)
    assert verify_password(WRONG_PASSWORD, hashed) is False


def test_verify_false_for_malformed_hash() -> None:
    """A garbage/non-bcrypt hash fails closed (returns False, does not raise)."""
    assert verify_password(PASSWORD, "not-a-real-bcrypt-hash") is False
    assert verify_password(PASSWORD, "") is False


def test_policy_accepts_valid_password() -> None:
    """A reasonable password passes the policy (no exception)."""
    validate_password_strength(PASSWORD)


def test_policy_rejects_too_short() -> None:
    """A password shorter than the minimum is rejected."""
    too_short = "a" * (MIN_PASSWORD_LENGTH - 1)
    with pytest.raises(PasswordPolicyError):
        validate_password_strength(too_short)


def test_policy_rejects_too_long() -> None:
    """A password longer than bcrypt's 72-byte limit is rejected."""
    too_long = "a" * (MAX_PASSWORD_BYTES + 1)
    with pytest.raises(PasswordPolicyError):
        validate_password_strength(too_long)


def test_policy_measures_max_in_utf8_bytes() -> None:
    """The max is enforced in UTF-8 bytes, not characters.

    A multi-byte character can exceed 72 bytes with fewer than 72 characters;
    such a password must be rejected so it never reaches bcrypt's truncation.
    """
    # Each "é" is 2 bytes in UTF-8; 37 of them = 74 bytes but only 37 chars.
    multibyte = "é" * 37
    assert len(multibyte) < MAX_PASSWORD_BYTES
    assert len(multibyte.encode("utf-8")) > MAX_PASSWORD_BYTES
    with pytest.raises(PasswordPolicyError):
        validate_password_strength(multibyte)
