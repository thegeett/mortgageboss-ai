"""Tests for the deterministic PDF text-layer extractor (LP-40).

Real PDFs (no AI), generated in-memory with PyMuPDF so there are no binary
fixtures to commit. Covers a text-layer PDF, multi-page, an empty (no-text) PDF,
corrupt/invalid input (graceful, never raises), and the privacy rule that the
extracted text is never logged.
"""

import pymupdf
import structlog
from app.services.pdf_utils import extract_text_from_pdf


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
