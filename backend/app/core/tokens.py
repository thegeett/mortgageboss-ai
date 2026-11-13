"""One-time secret tokens (LP-MB-Admin-04).

Generated here, emailed raw, stored only as a hash. Staff invites are the first user; the borrower
portal and password reset are expected to reuse these three functions rather than grow their own.
"""

import hashlib
import hmac
import secrets


def generate_token() -> str:
    """32 random bytes, URL-safe base64 without padding (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The SHA-256 hex digest stored in place of the token (64 characters).

    A plain hash, not a password hash: the token is 256 random bits, so there is nothing to guess and
    nothing for a slow hash to protect. A fast hash is what lets the lookup be one indexed query.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(a: str, b: str) -> bool:
    """Constant-time comparison, for any check that compares secrets directly."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
