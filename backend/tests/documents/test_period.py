"""LP-105 — the consolidated, type-aware document period line.

Covers each period concept (range / tax year / single labeled date / expiry / verbatim), the
graceful absence (no period concept, or the date not extracted yet → None), and that two
same-type documents with different periods produce distinguishable period values.
"""

from datetime import UTC, datetime

from app.documents.period import DocumentPeriod, document_period
from app.models.document import Document, DocumentStatus, UploadSource
from app.models.extraction import Extraction, ExtractionStatus

CREATED = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _doc(document_type: str | None) -> Document:
    doc = Document(
        loan_file_id=None,
        original_filename="scan1.pdf",
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


# --- Range concept (statement / pay / reporting / employment / policy) --------


def test_pay_stub_period_is_a_range() -> None:
    p = document_period(
        _doc("pay_stub"), _ext({"pay_period_start": "2026-06-01", "pay_period_end": "2026-06-15"})
    )
    assert p == DocumentPeriod(label="Period", value="Jun 1 - Jun 15, 2026")


def test_statement_range_collapses_shared_year() -> None:
    p = document_period(
        _doc("investment_account"),
        _ext({"statement_period_start": "2026-05-01", "statement_period_end": "2026-05-31"}),
    )
    assert p is not None and p.value == "May 1 - May 31, 2026"


def test_range_spanning_years_shows_both_full_dates() -> None:
    p = document_period(
        _doc("bank_statement"),
        _ext({"statement_period_start": "2025-12-15", "statement_period_end": "2026-01-14"}),
    )
    assert p is not None and p.value == "Dec 15, 2025 - Jan 14, 2026"


def test_insurance_is_a_policy_term_range() -> None:
    p = document_period(
        _doc("homeowners_insurance"),
        _ext({"effective_date": "2026-01-01", "expiration_date": "2026-12-31"}),
    )
    assert p == DocumentPeriod(label="Policy", value="Jan 1 - Dec 31, 2026")


def test_partial_range_surfaces_the_one_date() -> None:
    p = document_period(_doc("pay_stub"), _ext({"pay_period_end": "2026-06-15"}))
    assert p is not None and p.value == "Jun 15, 2026"


# --- Tax year concept ---------------------------------------------------------


def test_w2_period_is_the_tax_year() -> None:
    assert document_period(_doc("w2"), _ext({"tax_year": 2025})) == DocumentPeriod(
        label="Tax year", value="2025"
    )


def test_tax_year_from_string_year() -> None:
    p = document_period(_doc("tax_return"), _ext({"tax_year": "2024"}))
    assert p is not None and p.value == "2024"


# --- Single labeled event date ------------------------------------------------


def test_purchase_agreement_closes_date() -> None:
    assert document_period(_doc("purchase_agreement"), _ext({"closing_date": "2026-08-15"})) == (
        DocumentPeriod(label="Closes", value="Aug 15, 2026")
    )


def test_drivers_license_expires_date() -> None:
    assert document_period(_doc("drivers_license"), _ext({"expiration_date": "2028-03-01"})) == (
        DocumentPeriod(label="Expires", value="Mar 1, 2028")
    )


def test_divorce_decree_effective_date() -> None:
    p = document_period(_doc("divorce_decree"), _ext({"effective_date": "2024-02-10"}))
    assert p == DocumentPeriod(label="Effective", value="Feb 10, 2024")


# --- Verbatim (property tax bill) ---------------------------------------------


def test_property_tax_bill_shows_verbatim_due_dates() -> None:
    p = document_period(
        _doc("property_tax_bill"), _ext({"due_dates": "Nov 1, 2026 and Feb 1, 2027"})
    )
    assert p == DocumentPeriod(label="Due", value="Nov 1, 2026 and Feb 1, 2027")


# --- Graceful absence ---------------------------------------------------------


def test_gift_letter_has_no_period_concept() -> None:
    assert document_period(_doc("gift_letter"), _ext({"donor_name": "Aunt May"})) is None


def test_no_period_when_date_not_extracted() -> None:
    assert document_period(_doc("pay_stub"), _ext({})) is None  # pending/failed extraction
    assert document_period(_doc("pay_stub"), None) is None


def test_unknown_type_has_no_period() -> None:
    assert document_period(_doc("credit_report"), _ext({"foo": "bar"})) is None


# --- Distinguishability (the LF-XU26 pain) ------------------------------------


def test_two_pay_stubs_with_different_periods_are_distinguishable() -> None:
    first = document_period(
        _doc("pay_stub"), _ext({"pay_period_start": "2026-06-01", "pay_period_end": "2026-06-15"})
    )
    second = document_period(
        _doc("pay_stub"), _ext({"pay_period_start": "2026-06-16", "pay_period_end": "2026-06-30"})
    )
    assert first is not None and second is not None
    assert first.value != second.value
