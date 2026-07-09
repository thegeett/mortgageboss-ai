"""Snapshot PII handling (LP-203) — mask + keyed match-hash security properties."""

import hashlib
from uuid import uuid4

import pytest
from app.core.config import settings
from app.verification.snapshot.fields import FieldSource
from app.verification.snapshot.pii import (
    PiiField,
    PiiKind,
    mask,
    match_hash,
)
from pydantic import ValidationError

_SSN = "123-45-6789"
_ACCT = "0001234567893312"


# --------------------------------------------------------------------------- #
# mask()
# --------------------------------------------------------------------------- #


def test_mask_shows_only_last_four() -> None:
    assert mask("123456789", PiiKind.SSN) == "***-**-6789"
    assert mask("123-45-6789", PiiKind.SSN) == "***-**-6789"  # separators ignored
    assert mask("000123456789", PiiKind.ACCOUNT) == "****6789"
    assert mask("ACCT-3312", PiiKind.ACCOUNT) == "****3312"  # alnum last-4


@pytest.mark.parametrize("kind", list(PiiKind))
@pytest.mark.parametrize("value", [None, "", "12", "x", "!!", "  "])
def test_mask_short_malformed_or_null_is_safe_never_raw(value: object, kind: PiiKind) -> None:
    """Too-short / malformed / empty / null → a fully-masked placeholder, never raw, never crash."""
    out = mask(value, kind)
    assert out in {"***-**-****", "****"}
    if value:
        assert str(value) not in out


# --------------------------------------------------------------------------- #
# match_hash() — the security-critical properties
# --------------------------------------------------------------------------- #


def test_same_value_same_file_hashes_equal_matching_works() -> None:
    lf = uuid4()
    assert match_hash("123-45-6789", loan_file_id=lf) == match_hash("123456789", loan_file_id=lf)


def test_same_value_different_file_hashes_differ_no_cross_file_correlation() -> None:
    lf1, lf2 = uuid4(), uuid4()
    assert match_hash(_SSN, loan_file_id=lf1) != match_hash(_SSN, loan_file_id=lf2)


def test_hash_depends_on_the_app_secret_not_brute_forceable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The construction folds in settings.encryption_key — a party without it can't reproduce it.

    (a) The hash is NOT the naive ``sha256(loan_file_id:value)`` a party holding only the
        (non-secret) loan_file_id could compute — proving the secret is in the mix.
    (b) Changing the app secret changes the hash — proving the secret is load-bearing.
    """
    lf = uuid4()
    normalized = "123456789"
    naive = hashlib.sha256(f"{lf}:{normalized}".encode()).hexdigest()
    real = match_hash(_SSN, loan_file_id=lf)
    assert real != naive  # (a) not the secret-free construction

    before = match_hash(_SSN, loan_file_id=lf)
    monkeypatch.setattr(settings, "encryption_key", "a-different-application-secret-value")
    after = match_hash(_SSN, loan_file_id=lf)
    assert before != after  # (b) secret-dependent


# --------------------------------------------------------------------------- #
# PiiField
# --------------------------------------------------------------------------- #


def test_pii_field_never_carries_the_raw_value() -> None:
    lf = uuid4()
    pf = PiiField.from_raw(_SSN, kind=PiiKind.SSN, loan_file_id=lf, source=FieldSource.PARSED)
    dumped = pf.model_dump()

    assert pf.display == "***-**-6789"
    assert pf.match_hash == match_hash(_SSN, loan_file_id=lf)
    # The raw value is nowhere on the model.
    assert "value" not in dumped
    assert "123456789" not in str(dumped)
    assert _SSN not in str(dumped)


def test_pii_field_is_frozen_and_rejects_a_raw_value_field() -> None:
    lf = uuid4()
    pf = PiiField.from_raw(
        "acct-3312", kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.EXTRACTED
    )
    with pytest.raises(ValidationError):
        pf.display = "oops"  # frozen
    with pytest.raises(ValidationError):
        # extra="forbid" structurally prevents attaching a raw value.
        PiiField(display="x", match_hash="y", source=FieldSource.PARSED, value="123456789")


def test_pii_field_confidence_nullable_and_derived_source() -> None:
    from app.models.extraction import ConfidenceSource

    lf = uuid4()
    pf = PiiField.from_raw(
        "acct-3312", kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.PARSED
    )
    assert pf.confidence is None
    assert pf.confidence_source is ConfidenceSource.NOT_PROVIDED
