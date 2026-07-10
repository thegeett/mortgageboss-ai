"""Frozen three-section snapshot model (LP-204) — immutability, round-trip, invariants.

Uses hand-built dummy Fields/PiiFields — NOT real loan data.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    SNAPSHOT_VERSION,
    BorrowerRef,
    CalcBreakdownLine,
    CalculationEntry,
    CalculationsSection,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
)
from app.verification.snapshot.pii import PiiField, PiiKind
from pydantic import ValidationError

_LF = uuid4()
_RUN = uuid4()
_B1 = uuid4()
_B2 = uuid4()
_WHEN = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _sample() -> Snapshot:
    """A fully-populated snapshot exercising every shape (dummy data)."""
    return Snapshot(
        loan_file_id=_LF,
        run_id=_RUN,
        created_at=_WHEN,
        mismo=MismoSection.present(
            {
                "borrower.1.income.base_monthly": Field.present(
                    "6000", source=FieldSource.PARSED, confidence=0.9
                ),
                "borrower.1.ssn": PiiField.from_raw(
                    "123-45-6789", kind=PiiKind.SSN, loan_file_id=_LF, source=FieldSource.PARSED
                ),
                "property.county": Field.missing(),  # absent — no source supplied
                "property.hoa_dues": Field.present(
                    None, source=FieldSource.PARSED
                ),  # present-empty
            }
        ),
        documents=DocumentsSection.present(
            [
                DocumentEntry(
                    document_type="pay_stub",
                    belongs_to=(BorrowerRef(borrower_id=_B1, name="Akash Patel"),),
                    fields={
                        "employee_name": Field.present("Akash Patel", source=FieldSource.EXTRACTED)
                    },
                ),
                DocumentEntry(
                    document_type="bank_statement",
                    belongs_to=(
                        BorrowerRef(borrower_id=_B1, name="Akash Patel"),
                        BorrowerRef(borrower_id=_B2, name="Priya Patel"),
                    ),
                    fields={
                        "account_number": PiiField.from_raw(
                            "000123456789",
                            kind=PiiKind.ACCOUNT,
                            loan_file_id=_LF,
                            source=FieldSource.EXTRACTED,
                        )
                    },
                ),
                DocumentEntry(document_type="appraisal", belongs_to=None, fields={}),  # unresolved
            ]
        ),
        calculations=CalculationsSection.present(
            dti=CalculationEntry(
                value={"back_end_dti": "43.10", "front_end_dti": None},
                breakdown=[
                    CalcBreakdownLine(key="income.1", label="Base", amount="6000", source="stated"),
                    CalcBreakdownLine(
                        key="housing.tax", label="Tax", amount="300", source="extracted"
                    ),
                    CalcBreakdownLine(
                        key="housing.mi", label="MI", amount="120", source="computed"
                    ),
                ],
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# Immutability
# --------------------------------------------------------------------------- #


def test_snapshot_is_immutable_at_every_level() -> None:
    """Every model attribute is frozen — reassignment raises, top-level to leaf."""
    snap = _sample()
    with pytest.raises(ValidationError):
        snap.snapshot_version = 2
    with pytest.raises(ValidationError):
        snap.mismo.absent = True
    with pytest.raises(ValidationError):
        snap.documents.entries[0].document_type = "w2"
    with pytest.raises(ValidationError):
        snap.documents.entries[0].belongs_to[0].name = "x"
    with pytest.raises(ValidationError):
        snap.mismo.facts["borrower.1.income.base_monthly"].value = "9999"


def test_default_sections_are_present_empty() -> None:
    snap = Snapshot(loan_file_id=_LF, run_id=_RUN, created_at=_WHEN)
    assert snap.snapshot_version == SNAPSHOT_VERSION
    assert snap.mismo.is_present and snap.mismo.facts == {}
    assert snap.documents.is_present and snap.documents.entries == []
    assert snap.calculations.is_present


# --------------------------------------------------------------------------- #
# JSON round-trip (the acceptance bar for LP-209)
# --------------------------------------------------------------------------- #


def test_full_snapshot_round_trips_losslessly() -> None:
    snap = _sample()
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back == snap


def test_union_field_vs_piifield_survives_round_trip() -> None:
    back = Snapshot.model_validate_json(_sample().model_dump_json())
    assert isinstance(back.mismo.facts["borrower.1.income.base_monthly"], Field)
    assert isinstance(back.mismo.facts["borrower.1.ssn"], PiiField)


def test_pii_raw_value_never_appears_in_json() -> None:
    dumped = _sample().model_dump_json()
    assert "123456789" not in dumped
    assert "123-45-6789" not in dumped
    back = Snapshot.model_validate_json(dumped)
    ssn = back.mismo.facts["borrower.1.ssn"]
    assert isinstance(ssn, PiiField)
    assert ssn.display == "***-**-6789"
    assert ssn.match_hash is not None and ssn.match_hash.startswith("v1:")


def test_confidence_and_source_preserved_never_fabricated() -> None:
    back = Snapshot.model_validate_json(_sample().model_dump_json())
    rated = back.mismo.facts["borrower.1.income.base_monthly"]
    assert rated.confidence == 0.9 and rated.source is FieldSource.PARSED
    # A field with no confidence stays None (not fabricated) after round-trip.
    name = back.documents.entries[0].fields["employee_name"]
    assert name.confidence is None


# --------------------------------------------------------------------------- #
# Absent ≠ empty (field and section level)
# --------------------------------------------------------------------------- #


def test_absent_and_present_empty_field_stay_distinct_after_round_trip() -> None:
    back = Snapshot.model_validate_json(_sample().model_dump_json())
    absent = back.mismo.facts["property.county"]
    present_empty = back.mismo.facts["property.hoa_dues"]
    assert absent.absent is True and absent.is_present is False
    assert present_empty.absent is False and present_empty.value is None
    assert absent != present_empty


def test_empty_documents_section_differs_from_absent_section() -> None:
    empty = DocumentsSection.present([])
    absent = DocumentsSection.missing()
    assert empty.is_present and empty.entries == []
    assert absent.is_present is False
    assert empty != absent
    # survives round-trip inside a snapshot
    snap = Snapshot(loan_file_id=_LF, run_id=_RUN, created_at=_WHEN, documents=absent)
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back.documents.absent is True


def test_absent_section_may_not_carry_payload() -> None:
    with pytest.raises(ValidationError):
        MismoSection(absent=True, facts={"x": Field.missing()})
    with pytest.raises(ValidationError):
        DocumentsSection(absent=True, entries=[DocumentEntry()])
    with pytest.raises(ValidationError):
        CalculationsSection(absent=True, dti=CalculationEntry())


# --------------------------------------------------------------------------- #
# belongsTo: null / single / joint
# --------------------------------------------------------------------------- #


def test_belongs_to_null_single_and_joint_all_representable() -> None:
    null = DocumentEntry(document_type="appraisal", belongs_to=None)
    single = DocumentEntry(
        document_type="pay_stub",
        belongs_to=(BorrowerRef(borrower_id=_B1, name="Akash Patel"),),
    )
    joint = DocumentEntry(
        document_type="bank_statement",
        belongs_to=(
            BorrowerRef(borrower_id=_B1, name="Akash Patel"),
            BorrowerRef(borrower_id=_B2, name="Priya Patel"),
        ),
    )
    assert null.belongs_to is None
    assert len(single.belongs_to) == 1
    assert len(joint.belongs_to) == 2


def test_belongs_to_empty_list_is_rejected_use_none() -> None:
    """'Resolved to nobody' must be None, never an empty list."""
    with pytest.raises(ValidationError):
        DocumentEntry(document_type="pay_stub", belongs_to=[])


def test_belongs_to_rejects_duplicate_borrower() -> None:
    """A document must not claim the same borrower twice (DB UNIQUE(doc, borrower))."""
    with pytest.raises(ValidationError):
        DocumentEntry(
            document_type="bank_statement",
            belongs_to=(
                BorrowerRef(borrower_id=_B1, name="Akash Patel"),
                BorrowerRef(borrower_id=_B1, name="Akash P"),
            ),
        )


# --------------------------------------------------------------------------- #
# Value/metadata guards
# --------------------------------------------------------------------------- #


def test_calculation_value_rejects_unstringified_number() -> None:
    """A raw int must NOT silently become a bool (1 → True); the calculator stringifies."""
    with pytest.raises(ValidationError):
        CalculationEntry(value={"reserve_months": 6})
    # A genuine bool flag and a stringified number are both fine.
    ok = CalculationEntry(value={"is_arm": True, "back_end_dti": "43.10", "front_end_dti": None})
    assert ok.value == {"is_arm": True, "back_end_dti": "43.10", "front_end_dti": None}


def test_created_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        Snapshot(loan_file_id=_LF, run_id=_RUN, created_at=datetime(2026, 7, 9, 12, 0))  # naive


def test_unknown_snapshot_version_is_rejected() -> None:
    """A blob whose version this reader doesn't understand fails loudly, not silently."""
    good = _sample().model_dump()
    good["snapshot_version"] = 999
    with pytest.raises(ValidationError):
        Snapshot.model_validate(good)


# --------------------------------------------------------------------------- #
# Calculations: source tags survive
# --------------------------------------------------------------------------- #


def test_calculation_breakdown_source_tags_round_trip() -> None:
    back = Snapshot.model_validate_json(_sample().model_dump_json())
    dti = back.calculations.dti
    assert dti is not None
    tags = {line.source for line in dti.breakdown}
    assert tags == {"stated", "extracted", "computed"}
    assert dti.value["back_end_dti"] == "43.10"
    assert dti.value["front_end_dti"] is None


# --------------------------------------------------------------------------- #
# Section failed(reason) invariant (LP-208 amendment)
# --------------------------------------------------------------------------- #


def test_section_failed_carries_reason_present_never_does() -> None:
    failed = MismoSection.failed("mismo assembler raised RuntimeError")
    assert failed.absent is True and not failed.is_present
    assert failed.reason == "mismo assembler raised RuntimeError"
    # missing() is absent without a reason; present() never carries one.
    assert MismoSection.missing().reason is None
    assert MismoSection.present({}).reason is None
    with pytest.raises(ValidationError):
        MismoSection(absent=False, reason="not allowed on a present section")
    # round-trips
    back = MismoSection.model_validate_json(failed.model_dump_json())
    assert back == failed
