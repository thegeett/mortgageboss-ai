"""Tests for application-level PII encryption (LP-14).

Exercises the value-level crypto in :mod:`app.core.encryption` directly (no
database): round-tripping, that the output is genuinely encrypted and differs
from the plaintext, that Fernet's per-call IV makes the same plaintext encrypt
to different ciphertext while still decrypting back, and that None/empty values
are handled gracefully. The encryption-*at-rest* check (raw DB column holds
ciphertext) lives in the Borrower model tests.

The ENCRYPTION_KEY used here comes from the environment / ``.env`` like the rest
of the settings, so these tests run against the real cipher.
"""

import pytest
from app.core.encryption import decrypt_value, encrypt_value, get_cipher

SSN = "123-45-6789"


def test_encrypt_then_decrypt_round_trips() -> None:
    """A value survives an encrypt -> decrypt round trip unchanged."""
    token = encrypt_value(SSN)
    assert token is not None
    assert decrypt_value(token) == SSN


def test_ciphertext_differs_from_plaintext() -> None:
    """The encrypted output is not the plaintext (it is actually encrypted)."""
    token = encrypt_value(SSN)
    assert token is not None
    assert token != SSN
    assert SSN not in token


def test_same_plaintext_encrypts_to_different_ciphertext() -> None:
    """Fernet embeds a fresh IV/timestamp, so equal plaintext -> unequal tokens.

    Both tokens must still decrypt back to the same plaintext. This is why an
    encrypted column cannot be queried by equality.
    """
    first = encrypt_value(SSN)
    second = encrypt_value(SSN)
    assert first != second
    assert decrypt_value(first) == SSN
    assert decrypt_value(second) == SSN


def test_none_is_handled_gracefully() -> None:
    """None maps to None on both encrypt and decrypt (column stays NULL)."""
    assert encrypt_value(None) is None
    assert decrypt_value(None) is None


def test_empty_string_is_treated_as_no_value() -> None:
    """The empty string is treated as 'no value' and maps to None."""
    assert encrypt_value("") is None
    assert decrypt_value("") is None


def test_decrypt_rejects_tampered_ciphertext() -> None:
    """A tampered/invalid token raises ValueError without leaking the value."""
    token = encrypt_value(SSN)
    assert token is not None
    # Corrupt the FIRST character: its bits are always significant. (The last
    # base64 char can carry unused trailing bits, so flipping it sometimes
    # decodes to the same bytes — leaving the token valid and the test flaky.)
    tampered = ("A" if token[0] != "A" else "B") + token[1:]
    with pytest.raises(ValueError) as exc_info:
        decrypt_value(tampered)
    # The error message must not contain the plaintext.
    assert SSN not in str(exc_info.value)


def test_get_cipher_is_cached() -> None:
    """The cipher is built once and reused for the life of the process."""
    assert get_cipher() is get_cipher()
