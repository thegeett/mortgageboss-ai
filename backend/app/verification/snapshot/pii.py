"""Snapshot PII handling (LP-203, ADR-240) — mask + keyed match-hash + PiiField.

A ``PiiField`` never stores the raw value. It stores only a **masked display**
(last-4) and a **match-hash** that lets rules match same-value fields (a bank
statement's account == a MISMO asset's account) without the raw value ever
existing in the snapshot.

## The match-hash construction (security-critical)

    match_hash = f"{V}:" + HMAC-SHA256(key=K, msg=f"{kind}:{loan_file_id}:{value}")
    K          = derive_key(b"snapshot-pii-match-hash-v1")   (app-secret keyed)

Where ``value`` is the normalized value, ``loan_file_id`` is canonicalized, and
``V`` is the hash version carried in the output. Why each piece:

* **Kind-bound** — the ``PiiKind`` is in the message, so an SSN and an account
  number that happen to share a digit-string (``123-45-6789`` vs ``123456789``)
  do NOT collide into a spurious cross-kind match.
* **Per-loan-file salt** — ``loan_file_id`` is in the message, so the *same* SSN in
  two different loan files hashes *differently* (no cross-file correlation).
  Canonicalized (UUID form), so ``str(uuid)`` and an upper-cased rendering of the
  same id match; an empty/falsy id is rejected (it would collapse the salt).
  Consistent *within* a file; ``normalized`` (alphanumerics, lowercased) makes
  ``"123-45-6789"`` and ``"123456789"`` match.
* **Non-matchable for empty/absent** — a value that normalizes to fewer than
  ``_MIN_MATCH_LEN`` characters (``""`` / whitespace / punctuation / ``None``)
  returns ``None``, NOT a real hash: two absent/blank values must never "match".
* **Application secret (the crux for a low-entropy input)** — an SSN has only
  ~10^9 possibilities and ``loan_file_id`` is **not** secret, so a bare
  ``sha256(loan_file_id + ssn)`` is trivially brute-forced by anyone holding the
  hash. Keying the HMAC with an app secret (``K``, derived via
  :func:`app.core.encryption.derive_key` from the same Fernet ``encryption_key``
  that protects PII at rest, ADR-051) means the hash is only reproducible by the
  system — not un-reversible in an absolute sense (a holder of the snapshot AND
  the secret could still brute-force a low-entropy input), but no weaker than the
  encryption-at-rest boundary, and un-computable by any party without ``K``.
* **Versioned** — the output carries its version (``v1:``), so once snapshots
  persist (LP-204) a construction bump is an incremental, detectable migration,
  not a silent global match failure.

An absent PII fact (no source supplied it) is :meth:`PiiField.missing` — no
display, no hash — distinct from a source that supplied a blank (present-but-empty:
a masked placeholder display, a ``None`` match_hash).
"""

from __future__ import annotations

import hashlib
import hmac
from enum import StrEnum
from typing import assert_never
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.core.encryption import derive_key
from app.models.extraction import ConfidenceSource
from app.verification.snapshot.fields import FieldSource

# The hash version, carried in the output (``v1:<hex>``) so rotation is detectable.
# Bump only if the construction changes (would invalidate stored hashes).
_HASH_VERSION = "v1"
_HASH_PURPOSE = b"snapshot-pii-match-hash-" + _HASH_VERSION.encode()

# Fewer normalized characters than this → NON-matchable (match_hash returns None).
# Empty/whitespace/punctuation/None all fall here; a real SSN/account clears it.
_MIN_MATCH_LEN = 4

# A masked display always starts with one of these (SSN / account shapes); a raw
# value never does — the PiiField validator uses this to reject an unmasked display.
_MASK_PREFIXES = ("***-**-", "****")


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

    Honest by construction: ``None`` / empty / malformed / too-short (four or fewer
    significant characters) all yield a fully-masked placeholder — never the raw
    value, never a crash. Only the last four characters of a value **longer than
    four** are ever revealed (a 4-char value is shown as a placeholder, not whole).
    """
    raw = "" if value is None else str(value)
    if kind is PiiKind.SSN:
        digits = _digits(raw)
        return f"***-**-{digits[-4:]}" if len(digits) > 4 else "***-**-****"
    if kind is PiiKind.ACCOUNT:
        chars = _alnum(raw)
        return f"****{chars[-4:]}" if len(chars) > 4 else "****"
    assert_never(kind)  # a new PiiKind must declare its own mask shape, not fall through


def _normalize_pii(value: object) -> str:
    """Alphanumerics, lowercased — so ``123-45-6789`` and ``123456789`` match.

    Reuses :func:`_alnum` so the alphanumeric rule can't drift from the account
    mask; ``None`` normalizes to ``""`` (an absent value, never the token ``none``).
    """
    return _alnum("" if value is None else str(value)).lower()


def _canonical_loan_file_id(loan_file_id: UUID | str) -> str:
    """Canonical UUID string for the per-file salt; reject an empty/falsy id.

    A ``UUID`` renders to its canonical lowercase form; a string is parsed as a
    UUID so an upper-cased or otherwise re-rendered id of the same file matches. An
    empty id is rejected — it would collapse the salt and reintroduce cross-file
    correlation.
    """
    if isinstance(loan_file_id, UUID):
        return str(loan_file_id)
    text = str(loan_file_id).strip()
    if not text:
        raise ValueError("match_hash requires a non-empty loan_file_id")
    return str(UUID(text))  # canonicalize case/format (raises if not a UUID)


def _match_key() -> bytes:
    """The purpose-separated HMAC key, derived from the app PII secret (ADR-051)."""
    return derive_key(_HASH_PURPOSE)


def match_hash(value: object, *, kind: PiiKind, loan_file_id: UUID | str) -> str | None:
    """A per-loan-file, kind-bound, app-secret-keyed, versioned hash of the value.

    Returns ``None`` (NON-matchable) when the value normalizes to fewer than
    ``_MIN_MATCH_LEN`` characters — an empty/absent value must never produce a hash
    that collides with another empty/absent value. Raises ``ValueError`` for an
    empty ``loan_file_id``. See the module docstring for the full construction.
    """
    normalized = _normalize_pii(value)
    if len(normalized) < _MIN_MATCH_LEN:
        return None
    message = f"{kind.value}:{_canonical_loan_file_id(loan_file_id)}:{normalized}".encode()
    digest = hmac.new(_match_key(), message, hashlib.sha256).hexdigest()
    return f"{_HASH_VERSION}:{digest}"


class PiiField(BaseModel):
    """A sensitive snapshot fact: masked display + match-hash, **no raw value**.

    Frozen and closed (``extra="forbid"``); a validator additionally rejects an
    unmasked ``display``, so a raw value cannot be attached even by direct
    construction — build via :meth:`from_raw`, which masks + hashes and discards the
    raw value. ``match_hash`` is ``None`` when the value is empty/too-short
    (present-but-empty → non-matchable). An absent fact is :meth:`missing` (no
    display, no hash), distinct from a source-supplied blank.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    display: str | None = None
    match_hash: str | None = None
    confidence: float | None = None
    source: FieldSource | None = None
    # Explicit "no source supplied this" marker — distinct from a supplied blank.
    absent: bool = False

    @model_validator(mode="after")
    def _absent_present_and_masked(self) -> PiiField:
        if self.absent:
            if (
                self.display is not None
                or self.match_hash is not None
                or self.source is not None
                or self.confidence is not None
            ):
                raise ValueError(
                    "an absent PiiField carries no display, hash, source, or confidence"
                )
            return self
        if self.source is None:
            raise ValueError("a present PiiField must carry a source")
        if self.display is None or not self.display.startswith(_MASK_PREFIXES):
            raise ValueError("a present PiiField must carry a masked display (build via from_raw)")
        return self

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
            match_hash=match_hash(value, kind=kind, loan_file_id=loan_file_id),
            source=source,
            confidence=confidence,
        )

    @classmethod
    def pre_masked(
        cls,
        value: object,
        *,
        kind: PiiKind,
        source: FieldSource,
        confidence: float | None = None,
    ) -> PiiField:
        """Build a PiiField from an ALREADY-MASKED value (its raw form never reached us).

        ``match_hash`` is ``None`` (non-matchable — only the masked form was ever
        captured). The display is the canonical last-4 shape rendered from the value's
        last four alphanumerics, so even a badly-masked or over-masked input reveals at
        most four characters. Use :meth:`from_raw` for a value that is still raw.
        """
        last4 = _alnum(str(value))[-4:]
        if kind is PiiKind.SSN:
            display = f"***-**-{last4}" if len(last4) == 4 else "***-**-****"
        elif kind is PiiKind.ACCOUNT:
            display = f"****{last4}" if len(last4) == 4 else "****"
        else:
            assert_never(kind)  # a new PiiKind must declare its masked-display shape
        return cls(display=display, match_hash=None, source=source, confidence=confidence)

    @classmethod
    def missing(cls) -> PiiField:
        """A sensitive fact NO source supplied — absent, no display, no hash."""
        return cls(absent=True)

    @property
    def is_present(self) -> bool:
        """True when a source supplied this fact (even if the value was blank)."""
        return not self.absent

    @property
    def confidence_source(self) -> ConfidenceSource:
        """The derived confidence provenance (LP-201's single derivation rule)."""
        return ConfidenceSource.for_confidence(self.confidence)
