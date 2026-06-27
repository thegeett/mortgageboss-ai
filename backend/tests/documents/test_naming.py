"""LP-72 standard naming — a derived {Type}_{Identifier}_{Date} display name.

Covers: Tier-1 rich data → the full derived name (no spaces); the per-type identifier +
date come from the extracted data; sparse/Tier-3/pending → the {Type}_{UploadDate}
fallback; slugging (spaces/punctuation → hyphens); only non-PII fields feed the name.
"""

from datetime import UTC, datetime

from app.documents.naming import standard_name
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.extraction import Extraction, ExtractionStatus

CREATED = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _doc(document_type: str | None, *, filename: str = "scan1.pdf") -> Document:
    doc = Document(
        loan_file_id=None,
        original_filename=filename,
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path="x",
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
    )
    doc.created_at = CREATED
    return doc


def _ext(fields: dict[str, object]) -> Extraction:
    data = {key: {"value": value, "source": None} for key, value in fields.items()}
    return Extraction(
        document_id=None,
        version=1,
        extracted_data=data,
        extraction_status=ExtractionStatus.SUCCEEDED,
    )


def test_pay_stub_name_from_employer_and_pay_date() -> None:
    name = standard_name(
        _doc("pay_stub"),
        _ext({"employer_name": "Thermofisher PPD, Inc.", "pay_date": "2026-05-22"}),
    )
    assert name == "Pay-Stub_Thermofisher-PPD-Inc_2026-05-22"
    assert " " not in name  # no spaces


def test_bank_statement_name_from_bank_and_period_end() -> None:
    name = standard_name(
        _doc("bank_statement"),
        _ext({"bank_name": "Bank of America", "statement_period_end": "2026-04-30"}),
    )
    assert name == "Bank-Statement_Bank-of-America_2026-04-30"


def test_tax_return_name_uses_year_not_a_full_date() -> None:
    name = standard_name(
        _doc("tax_return"),
        _ext({"taxpayer_names": "Mahesh Chhotala", "tax_year": 2024}),
    )
    assert name == "Tax-Return-1040_Mahesh-Chhotala_2024"


def test_w2_year_as_string_is_handled() -> None:
    name = standard_name(_doc("w2"), _ext({"employer_name": "Acme", "tax_year": "2025"}))
    assert name == "W-2_Acme_2025"


def test_drivers_license_name_has_no_date_component() -> None:
    name = standard_name(_doc("drivers_license"), _ext({"full_name": "Chirag Rachhadia"}))
    assert name == "Drivers-License_Chirag-Rachhadia"


def test_recognized_type_without_a_rule_falls_back_to_type_and_upload_date() -> None:
    # A Tier-2 recognized type with no naming rule → humanized type + upload date.
    name = standard_name(_doc("credit_report"), None)
    assert name == "Credit-Report_2026-06-24"


def test_untyped_or_pending_falls_back_to_document_and_upload_date() -> None:
    name = standard_name(_doc(None), None)
    assert name == "Document_2026-06-24"


def test_rule_type_with_missing_identifier_falls_back_to_type_and_date() -> None:
    # A pay stub whose extraction didn't capture the employer → fallback (not just the bare label).
    name = standard_name(_doc("pay_stub"), _ext({"pay_date": None}))
    assert name == "Pay-Stub_2026-06-24"


def test_name_never_contains_spaces() -> None:
    name = standard_name(
        _doc("bank_statement"),
        _ext({"bank_name": "  Wells   Fargo  Bank  ", "statement_period_end": "2026-01-31"}),
    )
    assert " " not in name
    assert name == "Bank-Statement_Wells-Fargo-Bank_2026-01-31"
