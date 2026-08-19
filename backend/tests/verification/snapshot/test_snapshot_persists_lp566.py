"""LP-566 — the snapshot must actually persist. Proven per field, not assumed.

Staging had 22 completed runs and ZERO persisted snapshots: the at-rest PII guard refused every write,
and the call site logged only the exception CLASS, so the reason it was already computing went nowhere.

This test is the check that was missing. It feeds the identifier-shaped value each real field was found
carrying through the snapshot's own field builder, serializes, and runs the REAL guard. Anything that
would refuse a write fails here instead — on a machine, before a run.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.verification.snapshot.documents_section import build_document_fields
from app.verification.snapshot.persistence import RawPiiAtRestError, _assert_no_raw_pii

# Every (document_type, field) a staging query found carrying an identifier-shaped value, with a
# stand-in value of the same shape. The point is the SHAPE — a 9+-digit run is what the guard refuses.
_REAL_FIELDS_CARRYING_DIGIT_RUNS = [
    ("property_tax_bill", "parcel_or_apn", "123456789012"),
    ("property_tax_bill", "tax_bill_or_account_number", "987654321098"),
    ("property_tax_bill", "tax_year", "2025 998877665544"),  # an extraction defect, not PII
    ("homeowners_insurance", "policy_number", "445566778899"),
    ("homeowners_insurance", "policy_status", "Active 112233445566"),  # likewise
    ("closing_disclosure", "loan_number", "556677889900"),
    ("form_1098", "account_number", "667788990011"),
    ("uscis_notice_of_action", "i94_number", "778899001122"),
    ("drivers_license", "id_number_masked", "889900112233"),
    ("bank_statement", "account_number_masked", "990011223344"),
]


@pytest.mark.parametrize(
    ("document_type", "field", "value"),
    _REAL_FIELDS_CARRYING_DIGIT_RUNS,
    ids=[f"{d}.{f}" for d, f, _ in _REAL_FIELDS_CARRYING_DIGIT_RUNS],
)
def test_no_real_field_refuses_the_write(document_type: str, field: str, value: str) -> None:
    """Each is either masked (`_PII_FIELDS`) or scrubbed (`_SCRUB_FREE_TEXT_FIELDS`). A field in
    neither reaches the guard raw and costs the WHOLE loan file its snapshot — every tag, every
    calculation, the DTI and LTV inputs — which is why this is asserted per field."""
    fields = build_document_fields(
        {field: {"value": value, "confidence": 0.9}}, document_type, loan_file_id=uuid4()
    )

    _assert_no_raw_pii(json.dumps({k: v.model_dump(mode="json") for k, v in fields.items()}))


def test_the_guard_still_refuses_something_it_should() -> None:
    """The mirror. A test that only proves things pass would also pass with the guard deleted, and the
    guard is why the read-only query path can promise raw identifiers never come back."""
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"borrower": {"value": "123-45-6789"}}))


def test_a_nested_structure_never_becomes_a_field() -> None:
    """`transactions`, `additional_accounts` and `additional_sections` all carry identifier-shaped
    values in the real extractions, and all three are nested. `_scalar` returns None for those, so they
    never reach the snapshot's typed fields — which is why they need no masking entry and why adding
    one would have been cargo-culting a fix onto a path the guard never sees."""
    fields = build_document_fields(
        {"transactions": [{"description": "ACH 123456789012"}]},
        "bank_statement",
        loan_file_id=uuid4(),
    )

    assert "transactions" not in fields
