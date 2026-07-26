"""Snapshot Field primitive (LP-203) — absent≠empty + nullable confidence."""

from datetime import date
from decimal import Decimal

import pytest
from app.models.extraction import ConfidenceSource
from app.verification.snapshot.fields import Field, FieldSource
from pydantic import ValidationError


def test_absent_is_distinct_from_present_empty() -> None:
    """A field NO source supplied (absent) must be distinguishable from a present null."""
    absent = Field.missing()
    present_null = Field.present(None, source=FieldSource.PARSED)

    assert absent.absent is True
    assert absent.is_present is False
    assert absent.value is None and absent.source is None

    assert present_null.absent is False
    assert present_null.is_present is True
    assert present_null.value is None  # a source supplied an explicit null/empty
    assert present_null.source is FieldSource.PARSED

    # The two are NOT equal — the distinction is real, not collapsed into null-value.
    assert absent != present_null


@pytest.mark.parametrize("value", ["", 0, 0.0, False])
def test_present_but_empty_values_are_present(value: object) -> None:
    """Empty string / zero / False are present values, not absent."""
    field = Field.present(value, source=FieldSource.EXTRACTED)
    assert field.is_present is True
    assert field.value == value


def test_confidence_is_nullable_and_never_defaulted() -> None:
    no_conf = Field.present("x", source=FieldSource.PARSED)
    assert no_conf.confidence is None
    assert no_conf.confidence_source is ConfidenceSource.NOT_PROVIDED

    rated = Field.present("x", source=FieldSource.EXTRACTED, confidence=0.9)
    assert rated.confidence == 0.9
    assert rated.confidence_source is ConfidenceSource.MODEL_SELF_REPORTED


def test_present_field_requires_a_source() -> None:
    with pytest.raises(ValidationError):
        Field(value="x", absent=False, source=None)


def test_absent_field_may_not_carry_value_source_or_confidence() -> None:
    with pytest.raises(ValidationError):
        Field(absent=True, value="x")
    with pytest.raises(ValidationError):
        Field(absent=True, source=FieldSource.PARSED)
    with pytest.raises(ValidationError):
        Field(absent=True, confidence=0.5)


@pytest.mark.parametrize("bad", [Decimal("1234.56"), date(2026, 1, 1)])
def test_non_json_scalar_value_is_rejected_never_silently_coerced(bad: object) -> None:
    """A Decimal (money) must NOT be silently floated; a date must not slip through either."""
    with pytest.raises(ValidationError):
        Field.present(bad, source=FieldSource.PARSED)  # type: ignore[arg-type]


def test_field_is_frozen_and_closed() -> None:
    field = Field.present("x", source=FieldSource.PARSED)
    with pytest.raises(ValidationError):
        field.value = "y"  # frozen
    with pytest.raises(ValidationError):
        Field(value="x", source=FieldSource.PARSED, extra="nope")  # extra=forbid
