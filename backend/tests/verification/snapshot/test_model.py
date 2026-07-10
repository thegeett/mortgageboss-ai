"""Frozen three-section snapshot model (LP-204).

Covers: immutability (top-level and nested), JSON round-trip across all three
sections, the ``Field | PiiField`` union round-tripping all four variants,
absent!=empty surviving serialization, snake_case JSON keys, and the structural
no-correlation guarantee.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    SNAPSHOT_SCHEMA_VERSION,
    CalcSource,
    Calculation,
    CalculationLine,
    Calculations,
    DocumentSnapshot,
    Snapshot,
)
from app.verification.snapshot.pii import PiiField, PiiKind
from pydantic import ValidationError

_LF = uuid4()


def _pii() -> PiiField:
    return PiiField.from_raw(
        "123-45-6789", kind=PiiKind.SSN, loan_file_id=_LF, source=FieldSource.PARSED
    )


def _full_snapshot() -> Snapshot:
    """A snapshot exercising all three sections, both field variants, and a None calc."""
    return Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        mismo={
            "borrower.1.first_name": Field.present("Akash", source=FieldSource.PARSED),
            "borrower.1.ssn": _pii(),
            "borrower.1.middle_name": Field.missing(),  # absent
        },
        documents=(
            DocumentSnapshot(
                document_type="pay_stub",
                belongs_to="Akash Patel",
                fields={
                    "employer_name": Field.present(
                        "Acme", source=FieldSource.EXTRACTED, confidence=0.91
                    ),
                    "account_number": PiiField.from_raw(
                        "000123456789",
                        kind=PiiKind.ACCOUNT,
                        loan_file_id=_LF,
                        source=FieldSource.EXTRACTED,
                    ),
                },
            ),
            DocumentSnapshot(document_type="appraisal", belongs_to=None, fields={}),
        ),
        calculations=Calculations(
            dti=Calculation(
                value="0.43",
                breakdown=(
                    CalculationLine(label="monthly_income", value="8000", source=CalcSource.STATED),
                    CalculationLine(label="monthly_debt", value="3440", source=CalcSource.COMPUTED),
                ),
            ),
            ltv=Calculation(value="0.80"),
            mi=None,  # not computed
            reserves=None,
        ),
    )


def test_snapshot_is_frozen_top_level() -> None:
    snap = _full_snapshot()
    with pytest.raises(ValidationError):
        snap.snapshot_version = 2
    with pytest.raises(ValidationError):
        snap.mismo = {}


def test_nested_models_are_frozen_and_sequences_are_tuples() -> None:
    snap = _full_snapshot()
    # documents / breakdown are tuples — no append, and reassigning a nested attr raises.
    assert isinstance(snap.documents, tuple)
    assert isinstance(snap.calculations.dti.breakdown, tuple)
    with pytest.raises(AttributeError):
        snap.documents.append(DocumentSnapshot(document_type="w2"))  # type: ignore[attr-defined]
    with pytest.raises(ValidationError):
        snap.documents[0].document_type = "w2"


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Snapshot(
            loan_file_id=_LF,
            run_id=uuid4(),
            created_at=datetime.now(UTC),
            surprise="nope",
        )


def test_default_version_and_empty_sections() -> None:
    snap = Snapshot(loan_file_id=_LF, run_id=uuid4(), created_at=datetime.now(UTC))
    assert snap.snapshot_version == SNAPSHOT_SCHEMA_VERSION
    assert snap.mismo == {}
    assert snap.documents == ()
    assert snap.calculations == Calculations()


def test_json_round_trip_full_snapshot() -> None:
    snap = _full_snapshot()
    restored = Snapshot.model_validate_json(snap.model_dump_json())
    assert restored == snap


@pytest.mark.parametrize(
    "field",
    [
        Field.present("v", source=FieldSource.PARSED),  # present scalar
        Field.missing(),  # absent scalar
        _pii(),  # present PII
        PiiField.missing(),  # absent PII
    ],
)
def test_union_round_trips_all_four_variants(field: Field | PiiField) -> None:
    """Field vs PiiField must survive a JSON round-trip as the SAME type (smart union)."""
    snap = Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        mismo={"k": field},
    )
    restored = Snapshot.model_validate_json(snap.model_dump_json())
    assert type(restored.mismo["k"]) is type(field)
    assert restored.mismo["k"] == field


def test_absent_vs_present_empty_distinguishable_after_round_trip() -> None:
    snap = Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        mismo={
            "absent": Field.missing(),
            "present_empty": Field.present(None, source=FieldSource.PARSED),
        },
    )
    restored = Snapshot.model_validate_json(snap.model_dump_json())
    assert restored.mismo["absent"].absent is True
    assert restored.mismo["present_empty"].absent is False
    assert restored.mismo["absent"] != restored.mismo["present_empty"]


def test_json_keys_are_snake_case() -> None:
    dumped = _full_snapshot().model_dump(mode="json")
    assert "loan_file_id" in dumped and "snapshot_version" in dumped
    assert "document_type" in dumped["documents"][0]
    assert "belongs_to" in dumped["documents"][0]


@pytest.mark.parametrize("model", [Calculation, CalculationLine])
def test_calculation_value_rejects_non_json_scalar(model: type) -> None:
    """A Decimal (money) must not be silently floated — same guard as Field (ADR-240)."""
    kwargs = {"label": "x"} if model is CalculationLine else {}
    with pytest.raises(ValidationError):
        model(value=Decimal("1234.56"), **kwargs)


def test_belongs_to_is_a_raw_string_not_a_borrower_id() -> None:
    """No-correlation guarantee: belongs_to holds a raw name or None, never an entity id."""
    doc = DocumentSnapshot(document_type="pay_stub", belongs_to="Akash Patel")
    assert doc.belongs_to == "Akash Patel"
    assert DocumentSnapshot(document_type="appraisal").belongs_to is None
