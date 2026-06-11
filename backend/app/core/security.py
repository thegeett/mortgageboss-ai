"""Password hashing and password-policy utilities (LP-22).

Uses ``bcrypt`` directly (a maintained, focused library) rather than passlib,
which has a known runtime incompatibility with modern bcrypt releases (ADR
covering the choice in ``decisions.md``). Passwords are hashed with a
per-password salt, so identical passwords produce different hashes. Plaintext
passwords exist only transiently in memory and are NEVER stored or logged.

These are pure functions: no FastAPI dependencies, no database access, no
knowledge of the User model. The login flow (LP-23) and current-user lookup
(LP-24) call into them.

bcrypt operates on at most the first 72 bytes of input. Rather than letting it
silently truncate, :func:`validate_password_strength` rejects anything longer so
the behaviour is explicit and a long password never has a misleading "any suffix
works" property.
"""

import bcrypt

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt operates on (at most) the first 72 bytes


class PasswordPolicyError(ValueError):
    """Raised when a password fails the minimal V1 strength policy."""


def validate_password_strength(password: str) -> None:
    """Validate a password against the minimal V1 policy.

    Raises :class:`PasswordPolicyError` if the password is too short (< 8
    characters) or too long (> 72 bytes, bcrypt's input limit). Intentionally
    minimal for V1 — length only; complexity and breach-list checks are out of
    scope.

    Length is measured in characters for the minimum (user-facing) and in UTF-8
    bytes for the maximum (because that is the unit bcrypt truncates on; a
    multi-byte character can push a short-looking password past 72 bytes).
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordPolicyError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt (auto-salted). Returns the hash as a string.

    A fresh salt is generated per call, so hashing the same password twice
    yields different hashes; both verify. The returned value is the full bcrypt
    modular-crypt string (algorithm, cost, salt, and digest), safe to store in a
    text column.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Returns ``False`` (does not raise) on a malformed or non-bcrypt hash, so
    callers can treat every failure uniformly as "does not match" without
    branching on exception type. bcrypt's ``checkpw`` does a constant-time
    comparison of the digests, avoiding timing leaks on the compare itself.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False
