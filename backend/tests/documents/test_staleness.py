"""LP-71 staleness detection — deterministic, date-driven (no AI).

Covers: a date past its recency window → flagged with reason; within → not; an expired
ID → flagged; no usable date / no window → not flagged; a resolution clears the flag;
package fitness (current + fresh → fit; historical/stale → flagged); the windows are
configurable.
"""

from datetime import date

from app.documents.staleness import (
    RECENCY_WINDOWS,
    ExpirationRule,
    RecencyRule,
    evaluate_staleness,
    package_fitness,
)
from app.models.document import Document, DocumentStatus, StalenessResolution, UploadSource
from app.models.extraction import Extraction, ExtractionStatus

TODAY = date(2026, 6, 24)


def _doc(document_type: str, *, is_current: bool = True, resolution=None) -> Document:
    return Document(
        loan_file_id=None,
        original_filename="x.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        storage_path="x",
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
        upload_source=UploadSource.USER_UPLOAD,
        is_current=is_current,
        staleness_resolution=resolution,
    )


def _extraction(fields: dict[str, str]) -> Extraction:
    data = {key: {"value": value, "source": None} for key, value in fields.items()}
    return Extraction(
        document_id=None,
        version=1,
        extracted_data=data,
        extraction_status=ExtractionStatus.SUCCEEDED,
    )


# --------------------------------------------------------------------------- #
# Recency windows
# --------------------------------------------------------------------------- #


def test_pay_stub_past_window_is_flagged() -> None:
    # Pay date 45 days ago — past the ~30-day window.
    doc = _doc("pay_stub")
    ext = _extraction({"pay_date": (date(2026, 5, 10)).isoformat()})
    info = evaluate_staleness(doc, ext, today=TODAY)
    assert info.is_stale is True
    assert info.kind == "aged"
    assert "30-day window" in (info.reason or "")
    assert info.as_of_date == date(2026, 5, 10)


def test_pay_stub_within_window_is_fresh() -> None:
    doc = _doc("pay_stub")
    ext = _extraction({"pay_date": (date(2026, 6, 10)).isoformat()})  # 14 days ago
    info = evaluate_staleness(doc, ext, today=TODAY)
    assert info.is_stale is False
    assert info.kind is None


def test_bank_statement_uses_its_own_wider_window() -> None:
    doc = _doc("bank_statement")
    # 50 days ago — past pay-stub's 30 but within bank-statement's 60.
    ext = _extraction({"statement_period_end": (date(2026, 5, 5)).isoformat()})
    assert evaluate_staleness(doc, ext, today=TODAY).is_stale is False


def test_pay_stub_falls_back_to_period_end_when_no_pay_date() -> None:
    doc = _doc("pay_stub")
    ext = _extraction({"pay_period_end": (date(2026, 5, 1)).isoformat()})  # 54 days ago
    info = evaluate_staleness(doc, ext, today=TODAY)
    assert info.is_stale is True and info.kind == "aged"


# --------------------------------------------------------------------------- #
# Expiration
# --------------------------------------------------------------------------- #


def test_expired_id_is_flagged() -> None:
    doc = _doc("drivers_license")
    ext = _extraction({"expiration_date": (date(2026, 1, 1)).isoformat()})  # already passed
    info = evaluate_staleness(doc, ext, today=TODAY)
    assert info.is_stale is True
    assert info.kind == "expired"
    assert "Expired" in (info.reason or "")


def test_unexpired_id_is_fresh() -> None:
    doc = _doc("drivers_license")
    ext = _extraction({"expiration_date": (date(2028, 1, 1)).isoformat()})
    assert evaluate_staleness(doc, ext, today=TODAY).is_stale is False


# --------------------------------------------------------------------------- #
# No window / no date / resolution
# --------------------------------------------------------------------------- #


def test_type_without_a_window_is_never_flagged() -> None:
    doc = _doc("w2")  # tax-year doc — no recency window configured
    ext = _extraction({"tax_year": "2020"})
    assert evaluate_staleness(doc, ext, today=TODAY).is_stale is False


def test_missing_date_is_not_flagged() -> None:
    doc = _doc("pay_stub")
    assert evaluate_staleness(doc, None, today=TODAY).is_stale is False  # no extraction


def test_resolution_clears_the_flag_but_is_reported() -> None:
    doc = _doc("pay_stub", resolution=StalenessResolution.WAIVED)
    ext = _extraction({"pay_date": (date(2026, 5, 1)).isoformat()})  # would be aged
    info = evaluate_staleness(doc, ext, today=TODAY)
    assert info.is_stale is False  # the processor resolved it
    assert info.resolution is StalenessResolution.WAIVED
    assert info.kind == "aged"  # the underlying reason is still known


# --------------------------------------------------------------------------- #
# Package fitness (current + fresh)
# --------------------------------------------------------------------------- #


def test_current_fresh_document_is_package_fit() -> None:
    doc = _doc("pay_stub")
    ext = _extraction({"pay_date": (date(2026, 6, 18)).isoformat()})
    fit = package_fitness(doc, evaluate_staleness(doc, ext, today=TODAY))
    assert fit.fit is True and fit.reason is None


def test_superseded_document_is_not_fit() -> None:
    doc = _doc("pay_stub", is_current=False)  # a newer version is current
    ext = _extraction({"pay_date": (date(2026, 6, 18)).isoformat()})  # even if fresh
    fit = package_fitness(doc, evaluate_staleness(doc, ext, today=TODAY))
    assert fit.fit is False and fit.reason == "superseded"


def test_stale_document_is_not_fit() -> None:
    doc = _doc("pay_stub")
    ext = _extraction({"pay_date": (date(2026, 4, 1)).isoformat()})  # aged
    fit = package_fitness(doc, evaluate_staleness(doc, ext, today=TODAY))
    assert fit.fit is False and fit.reason == "stale"


# --------------------------------------------------------------------------- #
# Configurable windows (refine-with-Priya)
# --------------------------------------------------------------------------- #


def test_windows_are_configurable() -> None:
    """The windows are a plain config dict — editing them changes the verdict."""
    assert isinstance(RECENCY_WINDOWS["pay_stub"], RecencyRule)
    assert RECENCY_WINDOWS["pay_stub"].max_age_days == 30
    # The structure supports both rule kinds for Priya's refinement.
    assert isinstance(ExpirationRule(fields=("expiration_date",)), ExpirationRule)
