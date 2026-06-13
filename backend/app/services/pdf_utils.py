"""Deterministic PDF text-layer extraction (LP-40) — a DEV-ONLY tool.

This is **not** a pipeline step. The production pipeline reads documents with AI
directly (full-document native reading, LP-38/39). This utility extracts a PDF's
embedded **text layer** deterministically (no AI, no OCR) so a developer can
compare that output against the AI's reading on real documents — an experiment
harness behind a dev-gated endpoint (``app/api/dev.py``), informing a possible
future hybrid (cheap deterministic text for easy cases, AI for the rest).

``has_text`` is **informational** (a "this looks like a scanned image — the text
layer is empty" hint), not a routing signal: handling scans is the AI's job now.
The function never raises (corrupt/encrypted/invalid → ``extraction_ok=False``)
and never logs the extracted **text** (borrower PII) — only metadata.
"""

import asyncio
from dataclasses import dataclass

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

# A stripped text layer with at least this many characters is considered "has
# text". Below it (e.g. a scanned image with no embedded text) → has_text False.
# Informational only — not a routing threshold.
_MIN_MEANINGFUL_CHARS = 20

# Page texts are joined with a form feed so the developer can see page breaks.
_PAGE_SEPARATOR = "\f"


@dataclass(frozen=True)
class PdfTextExtractionResult:
    """The outcome of a deterministic PDF text-layer extraction.

    ``extraction_ok`` is False (with ``error_reason``) for a corrupt, encrypted,
    or invalid PDF. ``has_text`` indicates whether a meaningful text layer was
    found (informational — an empty layer suggests a scan).
    """

    text: str
    page_count: int
    has_text: bool
    extraction_ok: bool
    error_reason: str | None = None


def _extract_sync(content: bytes) -> PdfTextExtractionResult:
    """Blocking text-layer extraction; never raises (graceful on bad input)."""
    # PyMuPDF ships incomplete type hints, so open()/load_page()/close() read as
    # untyped calls under mypy strict — narrowly ignored here.
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception as exc:
        # Corrupt / not-a-PDF / unreadable → report, don't crash.
        return PdfTextExtractionResult("", 0, False, False, type(exc).__name__)

    try:
        page_count = int(doc.page_count)
        if doc.needs_pass:  # password-protected: we can't read the text layer
            return PdfTextExtractionResult("", page_count, False, False, "encrypted")
        parts = [
            str(doc.load_page(i).get_text())  # type: ignore[no-untyped-call]
            for i in range(page_count)
        ]
        text = _PAGE_SEPARATOR.join(parts)
        has_text = len(text.strip()) >= _MIN_MEANINGFUL_CHARS
        return PdfTextExtractionResult(text, page_count, has_text, True, None)
    except Exception as exc:
        return PdfTextExtractionResult("", 0, False, False, type(exc).__name__)
    finally:
        doc.close()  # type: ignore[no-untyped-call]


async def extract_text_from_pdf(content: bytes) -> PdfTextExtractionResult:
    """Extract a PDF's text layer from bytes (multi-page). Async; never raises.

    Wraps the blocking PyMuPDF call in a thread so it doesn't block the event
    loop. Logs **metadata only** — page count, the has_text/ok flags, and the
    byte size — and **never** the extracted text (PII).
    """
    result = await asyncio.to_thread(_extract_sync, content)
    logger.info(
        "pdf_text_layer_extracted",
        page_count=result.page_count,
        has_text=result.has_text,
        extraction_ok=result.extraction_ok,
        error_reason=result.error_reason,
        size_bytes=len(content),
    )  # NEVER log result.text
    return result
