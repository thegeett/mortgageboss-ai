"""Snapshot PII handling (LP-203, ADR-240) — mask + keyed match-hash + PiiField.

A ``PiiField`` never stores the raw value. It stores only a **masked display**
(last-4) and a **match-hash** that lets rules match same-value fields (a bank
statement's account == a MISMO asset's account) without the raw value ever
existing in the snapshot.

## The match-hash construction (security-critical)

    match_hash = HMAC-SHA256(key=K, msg=f"{loan_file_id}:{normalized_value}")
    K          = SHA256(b"snapshot-pii-match-hash-v1:" + settings.encryption_key)

Why each piece:

* **Per-loan-file salt** — ``loan_file_id`` is in the HMAC message, so the *same*
  SSN in two different loan files hashes *differently* (no cross-file correlation
  by hash). Consistent *within* a file (same value + same file → same hash), so
  rule-matching works; ``normalized_value`` (alphanumerics, lowercased) makes
  ``"123-45-6789"`` and ``"123456789"`` match.
* **Application secret (the crux for a low-entropy input)** — an SSN has only
  ~10^9 possibilities and ``loan_file_id`` is **not** secret, so a bare
  ``sha256(loan_file_id + ssn)`` is trivially brute-forced by anyone holding the
  hash: enumerate all SSNs, hash each, compare. Keying the HMAC with an
  application secret (``K``, derived from the same Fernet ``encryption_key`` that
  already protects PII at rest, ADR-051) means the hash is only reproducible by
  the system — an attacker without ``K`` cannot compute it for any candidate, so
  brute force is defeated regardless of the input's low entropy.
* **Purpose-separated key** — ``K`` is ``SHA256(purpose || encryption_key)``, not
  the raw Fernet key, so this HMAC key is cryptographically distinct from the
  encryption key (no cross-use of a Fernet key as an HMAC key; independent
  rotation reasoning). It reuses the *existing* secret store, inventing no new one.
"""

from __future__ import annotations

import hashlib
import hmac
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from app.core.config import settings
from app.models.extraction import ConfidenceSource
from app.verification.snapshot.fields import FieldSource

# Bumped only if the construction changes (would invalidate stored hashes).
_HASH_PURPOSE = b"snapshot-pii-match-hash-v1"


class PiiKind(StrEnum):
    """The kind of sensitive value, which selects the mask shape."""

    SSN = "ssn"  # → ***-**-1234
    ACCOUNT = "account"  # → ****3312 (bank/investment/loan account numbers, etc.)


def _digits(raw: str) -> str:
    return "".join(c for c in raw if c.isdigit())


def _alnum(raw: str) -> str:
    return "".join(c for c in raw if c.isalnum())


def mask(value: object, kind: PiiKind) -> str:
    """Return the last-4 masked display for a sensitive value.

    Honest by construction: ``None`` / empty / malformed / too-short-to-mask all
    yield a fully-masked placeholder — never the raw value, never a crash. Only the
    last four characters of a long-enough value are ever revealed.
    """
    raw = "" if value is None else str(value)
    if kind is PiiKind.SSN:
        digits = _digits(raw)
        return f"***-**-{digits[-4:]}" if len(digits) >= 4 else "***-**-****"
    chars = _alnum(raw)
    return f"****{chars[-4:]}" if len(chars) >= 4 else "****"


def _normalize_pii(value: object) -> str:
    """Alphanumerics, lowercased — so ``123-45-6789`` and ``123456789`` match."""
    return "".join(c for c in str(value) if c.isalnum()).lower()


def _match_key() -> bytes:
    """The purpose-separated HMAC key, derived from the app PII secret.

    Read per call (not cached) so a rotated ``encryption_key`` takes effect and so
    tests can exercise secret-dependence.
    """
    return hashlib.sha256(_HASH_PURPOSE + b":" + settings.encryption_key.encode()).digest()


def match_hash(value: object, *, loan_file_id: UUID | str) -> str:
    """A per-loan-file, app-secret-keyed hash of the full value (raw never stored).

    See the module docstring for the construction and why it resists brute-forcing
    a low-entropy SSN/account number.
    """
    message = f"{loan_file_id}:{_normalize_pii(value)}".encode()
    return hmac.new(_match_key(), message, hashlib.sha256).hexdigest()


class PiiField(BaseModel):
    """A sensitive snapshot fact: masked display + match-hash, **no raw value**.

    Frozen and closed (``extra="forbid"``) so a raw value can't be attached even by
    accident. Build one via :meth:`from_raw`, which masks + hashes internally and
    discards the raw value — callers never hand-store it.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    display: str
    match_hash: str
    confidence: float | None = None
    source: FieldSource

    @classmethod
    def from_raw(
        cls,
        value: object,
        *,
        kind: PiiKind,
        loan_file_id: UUID | str,
        source: FieldSource,
        confidence: float | None = None,
    ) -> PiiField:
        """Build a PiiField from a raw value — masks + hashes here; raw is not retained."""
        return cls(
            display=mask(value, kind),
            match_hash=match_hash(value, loan_file_id=loan_file_id),
            source=source,
            confidence=confidence,
        )

    @property
    def confidence_source(self) -> ConfidenceSource:
        """The derived confidence provenance (LP-201's single derivation rule)."""
        return ConfidenceSource.for_confidence(self.confidence)
