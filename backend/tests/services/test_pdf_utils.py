"""Tests for the deterministic PDF text-layer extractor (LP-40).

Real PDFs (no AI), generated in-memory with PyMuPDF so there are no binary
fixtures to commit. Covers a text-layer PDF, multi-page, an empty (no-text) PDF,
corrupt/invalid input (graceful, never raises), and the privacy rule that the
extracted text is never logged.
"""

import pymupdf
import structlog
from app.services.pdf_utils import (
    encoded_payload_size,
    extract_text_from_pdf,
    first_n_pages,
    fit_pdf_to_payload_budget,
    pdf_page_count,
)


def _make_pdf(pages: list[str]) -> bytes:
    """Build a small PDF whose pages carry the given text via the text layer."""
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        if body:
            page.insert_text((72, 72), body)
    data: bytes = doc.tobytes()
    doc.close()
    return data


async def test_text_layer_pdf() -> None:
    pdf = _make_pdf(["Employer ACME Corp gross pay 4200 net 3180"])
    result = await extract_text_from_pdf(pdf)
    assert result.extraction_ok is True
    assert result.has_text is True
    assert result.page_count == 1
    assert "ACME Corp" in result.text


async def test_multi_page_pdf() -> None:
    pdf = _make_pdf(
        [
            "Page one earnings statement for the pay period",
            "Page two year to date totals and deductions",
            "Page three employer and employee details",
        ]
    )
    result = await extract_text_from_pdf(pdf)
    assert result.extraction_ok is True
    assert result.page_count == 3
    assert "Page one" in result.text
    assert "Page two" in result.text
    assert "Page three" in result.text


async def test_empty_pdf_has_no_text() -> None:
    """A blank page → extraction succeeds but has_text is False (scan-like signal)."""
    pdf = _make_pdf([""])
    result = await extract_text_from_pdf(pdf)
    assert result.extraction_ok is True
    assert result.has_text is False
    assert result.page_count == 1
    assert result.text.strip() == ""


async def test_short_text_below_threshold_has_no_text() -> None:
    pdf = _make_pdf(["hi"])  # below the 20-char threshold
    result = await extract_text_from_pdf(pdf)
    assert result.extraction_ok is True
    assert result.has_text is False


async def test_corrupt_input_is_graceful() -> None:
    result = await extract_text_from_pdf(b"this is not a pdf at all")
    assert result.extraction_ok is False
    assert result.has_text is False
    assert result.page_count == 0
    assert result.error_reason is not None  # a reason, not a crash


async def test_truncated_pdf_is_graceful() -> None:
    pdf = _make_pdf(["some real content here for the page"])
    result = await extract_text_from_pdf(pdf[: len(pdf) // 2])  # cut it in half
    # Either it fails gracefully or recovers partial text — but it must not raise.
    assert isinstance(result.extraction_ok, bool)


async def test_empty_bytes_is_graceful() -> None:
    result = await extract_text_from_pdf(b"")
    assert result.extraction_ok is False
    assert result.has_text is False


async def test_extracted_text_is_not_logged() -> None:
    pii_text = "CONFIDENTIAL borrower SSN 123-45-6789 income 99999"
    pdf = _make_pdf([pii_text])
    with structlog.testing.capture_logs() as logs:
        result = await extract_text_from_pdf(pdf)

    assert "123-45-6789" in result.text  # returned to the caller
    blob = " ".join(repr(e) for e in logs)
    assert "123-45-6789" not in blob  # but never logged
    assert pii_text not in blob
    # Metadata IS logged.
    assert any(e["event"] == "pdf_text_layer_extracted" for e in logs)


# --------------------------------------------------------------------------- #
# LP-462 — first_n_pages (the classification page cap)
# --------------------------------------------------------------------------- #


async def test_first_n_pages_slices_over_cap() -> None:
    pdf = _make_pdf([f"page {i}" for i in range(30)])
    out = await first_n_pages(pdf, 15)
    assert out is not None
    doc = pymupdf.open(stream=out, filetype="pdf")
    assert doc.page_count == 15
    doc.close()


async def test_first_n_pages_within_cap_is_byte_identical() -> None:
    pdf = _make_pdf(["a", "b", "c"])
    out = await first_n_pages(pdf, 15)
    assert out == pdf  # already under the cap → original bytes, no re-encode


async def test_first_n_pages_non_pdf_returns_none() -> None:
    assert await first_n_pages(b"not a pdf at all", 15) is None  # caller sends original unchanged


async def test_first_n_pages_never_logs_content() -> None:
    pdf = _make_pdf([f"SSN 123-45-6789 page {i}" for i in range(20)])
    with structlog.testing.capture_logs() as logs:
        out = await first_n_pages(pdf, 5)
    assert out is not None
    blob = " ".join(repr(e) for e in logs)
    assert "123-45-6789" not in blob  # the slice never logs content


# --------------------------------------------------------------------------- #
# LP-636 defect 4 — the byte budget
# --------------------------------------------------------------------------- #


def test_encoded_payload_size_accounts_for_base64_expansion() -> None:
    """The provider's 32 MB ceiling is on the ENCODED request, and base64 is 4/3 the size.

    Anyone reasoning in raw megabytes is a third under the number actually being checked — which
    is how a 23.8 MB contract, comfortably "under 32 MB", was rejected."""
    assert encoded_payload_size(3) == 4
    assert encoded_payload_size(1) == 4  # padded to a 4-byte group
    assert encoded_payload_size(24_925_587) > 33_000_000  # LF-ZE9N's contract, over 32 MB encoded


async def test_a_document_within_budget_is_returned_untouched() -> None:
    """The common case must not re-encode: byte-identical out, and nothing reported as dropped."""
    pdf = _make_pdf(["one", "two", "three"])

    payload, dropped = await fit_pdf_to_payload_budget(pdf, "application/pdf", max_pages=50)

    assert payload == pdf
    assert dropped is None


async def test_pages_are_dropped_until_the_payload_fits() -> None:
    """The fix itself. A document inside the PAGE cap but over the BYTE budget is trimmed further.

    This is the LF-ZE9N shape: the 23.8 MB contract was already within the 15-page classification
    cap, so the page cap was a no-op and the call died on size with no data at all."""
    pdf = _make_pdf([f"page {i} " + ("filler " * 400) for i in range(16)])

    payload, dropped = await fit_pdf_to_payload_budget(
        pdf, "application/pdf", max_pages=50, max_bytes=encoded_payload_size(len(pdf)) // 3
    )

    assert dropped is not None and dropped > 0
    assert len(payload) < len(pdf)
    kept = await pdf_page_count(payload)
    assert kept is not None and 1 <= kept < 16


async def test_the_page_cap_still_applies_before_the_byte_budget() -> None:
    """Pages first, bytes second — a 20-page document with a 5-page cap comes back at 5 even when
    it would have fitted the byte budget whole."""
    pdf = _make_pdf([f"page {i}" for i in range(20)])

    payload, dropped = await fit_pdf_to_payload_budget(pdf, "application/pdf", max_pages=5)

    assert dropped is None  # size never bound
    assert await pdf_page_count(payload) == 5


async def test_a_non_pdf_is_passed_through_unchanged() -> None:
    """Only PDFs are sliceable. An image goes to the existing error path untouched rather than
    being mangled here."""
    blob = b"\xff\xd8\xff" + b"x" * 5000

    payload, dropped = await fit_pdf_to_payload_budget(blob, "image/jpeg", max_pages=5)

    assert payload == blob
    assert dropped is None


async def test_a_single_page_over_budget_fails_honestly_rather_than_silently() -> None:
    """Page-dropping cannot rescue a document whose FIRST page is already too big.

    It returns what it has and lets the call be rejected as oversized, which is visible. Returning
    an empty or zero-page PDF would look like a successful read of nothing."""
    pdf = _make_pdf(["only page " + ("filler " * 2000)])

    payload, dropped = await fit_pdf_to_payload_budget(
        pdf, "application/pdf", max_pages=50, max_bytes=10
    )

    assert dropped is None
    assert await pdf_page_count(payload) == 1
