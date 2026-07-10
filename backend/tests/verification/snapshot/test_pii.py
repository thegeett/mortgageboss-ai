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


def test_mask_does_not_reveal_an_exactly_four_char_value() -> None:
    """A value with exactly four significant chars is masked, not shown whole."""
    assert mask("3312", PiiKind.ACCOUNT) == "****"  # not "****3312"
    assert mask("6789", PiiKind.SSN) == "***-**-****"  # not "***-**-6789"


# --------------------------------------------------------------------------- #
# match_hash() — the security-critical properties
# --------------------------------------------------------------------------- #


def test_same_value_same_file_hashes_equal_matching_works() -> None:
    lf = uuid4()
    assert match_hash("123-45-6789", kind=PiiKind.SSN, loan_file_id=lf) == match_hash(
        "123456789", kind=PiiKind.SSN, loan_file_id=lf
    )


def test_same_value_different_file_hashes_differ_no_cross_file_correlation() -> None:
    lf1, lf2 = uuid4(), uuid4()
    assert match_hash(_SSN, kind=PiiKind.SSN, loan_file_id=lf1) != match_hash(
        _SSN, kind=PiiKind.SSN, loan_file_id=lf2
    )


def test_empty_or_absent_value_is_non_matchable() -> None:
    """Empty / whitespace / punctuation / None → None (never a colliding hash)."""
    lf = uuid4()
    for value in ("", "   ", "--", None):
        assert match_hash(value, kind=PiiKind.ACCOUNT, loan_file_id=lf) is None
    # Two absent/blank values must NOT match (both None, not one shared token).
    a = match_hash("", kind=PiiKind.ACCOUNT, loan_file_id=lf)
    b = match_hash("   ", kind=PiiKind.ACCOUNT, loan_file_id=lf)
    assert a is None and b is None


def test_different_kinds_with_equal_digits_do_not_collide() -> None:
    """An SSN and an account sharing a digit-string must NOT produce the same hash."""
    lf = uuid4()
    assert match_hash("123-45-6789", kind=PiiKind.SSN, loan_file_id=lf) != match_hash(
        "123456789", kind=PiiKind.ACCOUNT, loan_file_id=lf
    )


def test_loan_file_id_is_canonicalized_and_empty_is_rejected() -> None:
    lf = uuid4()
    # str(uuid) vs an upper-cased rendering of the same id → the SAME hash.
    assert match_hash(_ACCT, kind=PiiKind.ACCOUNT, loan_file_id=str(lf)) == match_hash(
        _ACCT, kind=PiiKind.ACCOUNT, loan_file_id=str(lf).upper()
    )
    # An empty loan_file_id is rejected, never silently hashed against a collapsed salt.
    with pytest.raises(ValueError):
        match_hash(_ACCT, kind=PiiKind.ACCOUNT, loan_file_id="")


def test_hash_is_versioned() -> None:
    lf = uuid4()
    h = match_hash(_SSN, kind=PiiKind.SSN, loan_file_id=lf)
    assert h is not None and h.startswith("v1:")


def test_hash_depends_on_the_app_secret_not_brute_forceable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The construction folds in settings.encryption_key — a party without it can't reproduce it."""
    lf = uuid4()
    normalized = "123456789"
    naive = hashlib.sha256(f"{lf}:{normalized}".encode()).hexdigest()
    real = match_hash(_SSN, kind=PiiKind.SSN, loan_file_id=lf)
    assert real is not None and naive not in real  # (a) not the secret-free construction

    before = match_hash(_SSN, kind=PiiKind.SSN, loan_file_id=lf)
    monkeypatch.setattr(settings, "encryption_key", "a-different-application-secret-value")
    after = match_hash(_SSN, kind=PiiKind.SSN, loan_file_id=lf)
    assert before != after  # (b) secret-dependent


# --------------------------------------------------------------------------- #
# PiiField
# --------------------------------------------------------------------------- #


def test_pii_field_never_carries_the_raw_value() -> None:
    lf = uuid4()
    pf = PiiField.from_raw(_SSN, kind=PiiKind.SSN, loan_file_id=lf, source=FieldSource.PARSED)
    dumped = pf.model_dump()

    assert pf.display == "***-**-6789"
    assert pf.match_hash == match_hash(_SSN, kind=PiiKind.SSN, loan_file_id=lf)
    # The raw value is nowhere on the model.
    assert "value" not in dumped
    assert "123456789" not in str(dumped)
    assert _SSN not in str(dumped)


def test_pii_field_rejects_an_unmasked_display() -> None:
    """The raw value cannot be smuggled into `display` — the validator rejects it."""
    with pytest.raises(ValidationError):
        PiiField(display=_SSN, match_hash="v1:abc", source=FieldSource.PARSED)
    with pytest.raises(ValidationError):
        PiiField(display="123456789", match_hash="v1:abc", source=FieldSource.EXTRACTED)


def test_pii_field_is_frozen_and_closed() -> None:
    lf = uuid4()
    pf = PiiField.from_raw(
        "acct-3312", kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.EXTRACTED
    )
    with pytest.raises(ValidationError):
        pf.display = "oops"  # frozen
    with pytest.raises(ValidationError):
        # extra="forbid" structurally prevents attaching a raw value under a new key.
        PiiField(
            display="****3312", match_hash="v1:y", source=FieldSource.PARSED, value="123456789"
        )


def test_pii_field_missing_is_absent_and_distinct_from_a_blank() -> None:
    """missing() carries no display and no hash — distinct from a source-supplied blank."""
    lf = uuid4()
    absent = PiiField.missing()
    assert absent.absent is True and absent.is_present is False
    assert absent.display is None and absent.match_hash is None

    # A source that supplied a BLANK account: present-but-empty → masked placeholder,
    # non-matchable hash (None), but NOT absent.
    blank = PiiField.from_raw("", kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.PARSED)
    assert blank.absent is False and blank.is_present is True
    assert blank.display == "****" and blank.match_hash is None
    assert absent != blank


def test_matches_requires_two_real_equal_hashes_none_never_matches() -> None:
    """matches() enforces absent-is-not-matchable: a None hash never matches (a bare
    ``==`` on match_hash would wrongly return True for None == None — LP-302a accounts)."""
    lf = uuid4()
    a = PiiField.from_raw(_ACCT, kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.PARSED)
    same = PiiField.from_raw(
        _ACCT, kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.PARSED
    )
    other = PiiField.from_raw(
        "9999888877776666", kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.PARSED
    )
    # Positive: same raw value + same per-file salt → same real hash → match.
    assert a.is_matchable is True and a.matches(same) is True
    # Negative: a different value must NOT match.
    assert a.matches(other) is False
    # Non-matchable: two pre-masked accounts (match_hash=None) NEVER match — not each
    # other (no same-last-4 false collision), not a real-hash field.
    m1 = PiiField.pre_masked("****5667", kind=PiiKind.ACCOUNT, source=FieldSource.EXTRACTED)
    m2 = PiiField.pre_masked("****5667", kind=PiiKind.ACCOUNT, source=FieldSource.EXTRACTED)
    assert m1.is_matchable is False
    assert m1.matches(m2) is False and m2.matches(m1) is False  # identical display, still no match
    assert m1.matches(a) is False and a.matches(m1) is False
    assert PiiField.missing().matches(PiiField.missing()) is False  # absent never matches


def test_pii_field_confidence_nullable_and_derived_source() -> None:
    from app.models.extraction import ConfidenceSource

    lf = uuid4()
    pf = PiiField.from_raw(
        "acct-3312", kind=PiiKind.ACCOUNT, loan_file_id=lf, source=FieldSource.PARSED
    )
    assert pf.confidence is None
    assert pf.confidence_source is ConfidenceSource.NOT_PROVIDED
