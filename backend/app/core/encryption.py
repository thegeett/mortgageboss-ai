"""Application-level encryption for sensitive PII at rest (LP-14, ADR-051).

The most sensitive field in the system — a borrower's SSN — is GLBA-covered and
must be encrypted at rest. We encrypt and decrypt in *application* code rather
than using PostgreSQL's pgcrypto (the LP-9 assumption, now reconsidered in
ADR-051): the database stores only ciphertext, and the key lives in settings /
environment, never in the database. So a database-only compromise (a leaked
dump, a read replica, a backup) yields ciphertext but never the key.

We use Fernet from the ``cryptography`` library: authenticated symmetric
encryption (AES-128-CBC + HMAC-SHA256). "Authenticated" means tampering with the
ciphertext is detected on decrypt rather than silently returning garbage. Each
``encrypt`` call embeds a fresh IV and a timestamp, so encrypting the same
plaintext twice yields different ciphertext — that is by design, not a bug.

This module is deliberately small and value-oriented (``str``/``None`` in and
out). The SQLAlchemy glue that makes a column transparently encrypted lives in
:mod:`app.models.encrypted_types`.

Security invariants:
  * Plaintext is NEVER placed in an exception message, log, or repr here.
  * The key is read from :data:`app.core.config.settings`, never hardcoded.
  * Key rotation and secret-manager integration are out of scope for V1
    (Phase 7); a single active key is used.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


@lru_cache(maxsize=1)
def get_cipher() -> Fernet:
    """Return the process-wide Fernet cipher built from the configured key.

    Cached: the key is fixed for the life of the process, so we build the
    cipher once. ``Fernet(...)`` validates the key format and raises if it is
    not a 32-byte urlsafe-base64 key, surfacing misconfiguration at first use.
    """
    return Fernet(settings.encryption_key.encode())


def encrypt_value(plaintext: str | None) -> str | None:
    """Encrypt a plaintext string, returning urlsafe-base64 ciphertext.

    ``None`` and the empty string are treated as "no value" and map to
    ``None`` (the column stores SQL ``NULL`` rather than ciphertext of an empty
    string), so the stated/absent distinction is preserved and empty PII never
    occupies a ciphertext slot.

    The returned token is a ``str`` (urlsafe base64), safe to store in a text
    column. The same plaintext encrypts to different ciphertext each call — see
    the module docstring.
    """
    if not plaintext:
        return None
    token = get_cipher().encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_value(ciphertext: str | None) -> str | None:
    """Decrypt urlsafe-base64 ciphertext back to plaintext.

    ``None`` and the empty string map to ``None`` (mirrors :func:`encrypt_value`
    for round-tripping). Raises :class:`ValueError` if the token is invalid or
    was tampered with — deliberately without echoing the ciphertext, so nothing
    sensitive leaks into the error.
    """
    if not ciphertext:
        return None
    try:
        plaintext = get_cipher().decrypt(ciphertext.encode("ascii"))
    except InvalidToken as exc:
        # Never include the token or any value in the message.
        raise ValueError("Failed to decrypt value: invalid or tampered ciphertext") from exc
    return plaintext.decode("utf-8")
