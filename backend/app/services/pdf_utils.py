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


def _page_count_sync(content: bytes) -> int | None:
    """The PDF's page total, or None if it can't be read as a PDF. Never raises (blocking)."""
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:
        return None
    try:
        return int(doc.page_count)
    except Exception:
        return None
    finally:
        doc.close()  # type: ignore[no-untyped-call]


async def pdf_page_count(content: bytes) -> int | None:
    """The PDF's actual page total (DETERMINISTIC, from the file — never a model read), or None if the bytes
    are not a readable PDF. Async, never raises. LP-381: AS-9's ``stmt.page_count_present`` — the count of
    pages actually present, computed from the document, so a model miscount can never fabricate completeness."""
    return await asyncio.to_thread(_page_count_sync, content)


def _first_n_pages_sync(content: bytes, max_pages: int) -> bytes | None:
    """Return a PDF of the first ``max_pages`` pages, or None if the input isn't a slice-able PDF. Blocking.

    Used by classification (LP-462): the Anthropic/Bedrock document block caps at 100 pages / 32 MB, so a
    long package must be trimmed to the lead document before the call. Returns the ORIGINAL bytes untouched
    when the document already has ``<= max_pages`` pages (no re-encode, byte-identical) or when it can't be
    read as a PDF (the caller then sends it as-is and the existing error path handles any rejection). Never
    raises.
    """
    # A non-positive cap would disable trimming and re-expose the >100-page rejection this exists to
    # prevent — floor at one page so the cap can never silently become a no-op (LP-462 review).
    max_pages = max(1, max_pages)
    try:
        src = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:
        return None  # not a readable PDF → caller sends the original bytes unchanged
    try:
        if int(src.page_count) <= max_pages:
            return content  # already within the cap — byte-identical, no re-encode
        out = pymupdf.open()  # type: ignore[no-untyped-call]
        try:
            out.insert_pdf(src, from_page=0, to_page=max_pages - 1)  # type: ignore[no-untyped-call]
            return bytes(out.tobytes())  # type: ignore[no-untyped-call]
        finally:
            # release the new doc's native handle too (src is closed in the outer finally)
            out.close()  # type: ignore[no-untyped-call]
    except Exception:
        return None
    finally:
        src.close()  # type: ignore[no-untyped-call]


async def first_n_pages(content: bytes, max_pages: int) -> bytes | None:
    """The first ``max_pages`` pages of a PDF as new PDF bytes, or None if not a slice-able PDF (LP-462).

    Async wrapper (threaded) around :func:`_first_n_pages_sync`. Returns the original bytes unchanged when the
    document is already within the cap; None when the bytes aren't a readable PDF (the caller sends them
    as-is). Never raises; never logs content (PII)."""
    return await asyncio.to_thread(_first_n_pages_sync, content, max_pages)


_PDF_MEDIA_TYPE = "application/pdf"


async def cap_pdf_pages(content: bytes, media_type: str, max_pages: int) -> bytes:
    """The document payload for an AI call, trimmed to the first ``max_pages`` if it's an over-cap PDF.

    The boilerplate both classification (LP-462) and Tier-3 free extraction (LP-463) share around
    :func:`first_n_pages`: only ``application/pdf`` is trimmed; a PDF already within the cap comes back
    byte-identical; a non-PDF, or an unreadable PDF (``first_n_pages`` → None), is sent unchanged. Never raises.
    """
    if media_type.lower().strip() != _PDF_MEDIA_TYPE:
        return content
    capped = await first_n_pages(content, max_pages)
    return capped if capped is not None else content


#: The provider's document-block ceiling is 32 MB **on the encoded request**, and base64 inflates
#: bytes by 4/3. So the raw budget is ~24 MB before the prompt and JSON envelope are added.
#: Deliberately under it: the margin covers the system prompt, the instruction block and the
#: envelope, none of which are known here.
MAX_DOCUMENT_PAYLOAD_BYTES = 22 * 1024 * 1024


def encoded_payload_size(raw_bytes: int) -> int:
    """Bytes on the wire once base64-encoded — ``4 * ceil(n / 3)``.

    The limit that actually rejected LF-ZE9N's 23.8 MB contract applies to the ENCODED payload,
    which is a third larger than the file on disk. Anyone reasoning in raw megabytes is a third
    under the number the provider is checking.
    """
    return 4 * ((raw_bytes + 2) // 3)


async def fit_pdf_to_payload_budget(
    content: bytes,
    media_type: str,
    *,
    max_pages: int,
    max_bytes: int = MAX_DOCUMENT_PAYLOAD_BYTES,
) -> tuple[bytes, int | None]:
    """Trim a PDF to ``max_pages``, then keep dropping pages until it fits ``max_bytes``.

    Returns ``(payload, pages_dropped_for_size)`` — the second is ``None`` when size never bound
    (the common case), else the number of pages the SIZE cap removed beyond the page cap, so the
    caller can record that the document was truncated rather than read whole.

    LP-636 defect 4. There was a cap on PAGES and none on BYTES, and bytes are what rejected
    LF-ZE9N's 23.8 MB purchase contract: it was already inside the 15-page classification cap — a
    high-DPI scan — so the page cap was a no-op and the call failed with HTTP 400, producing no
    data at all.

    DROPPING PAGES IS NOT THE BEST ANSWER, ONLY THE SAFE ONE. Re-rendering the pages at a lower
    DPI would keep all of them, which matters for a contract whose signature is on the last page.
    That needs image resampling with its own quality/OCR trade-offs; this needs none, reuses the
    tested slicing path, and turns a hard rejection into a partial read. If a document is over
    budget on its FIRST page alone nothing here can save it, and it still fails honestly as
    ``oversized``.

    Never raises. A non-PDF, or bytes that will not parse, come back unchanged for the existing
    error path to handle.
    """
    if media_type.lower().strip() != _PDF_MEDIA_TYPE:
        return content, None

    payload = await cap_pdf_pages(content, media_type, max_pages)
    if encoded_payload_size(len(payload)) <= max_bytes:
        return payload, None

    total = await pdf_page_count(payload)
    if total is None or total <= 1:
        # Unreadable, or a single page already over budget — page-dropping cannot help.
        return payload, None

    # Halve until it fits. Linear descent would issue one re-encode per page on a 50-page scan;
    # this converges in a handful, and the exact page count is not worth more calls than that.
    pages = total
    while pages > 1:
        pages = max(1, pages // 2)
        candidate = await first_n_pages(payload, pages)
        if candidate is None:
            return payload, None
        if encoded_payload_size(len(candidate)) <= max_bytes:
            logger.warning(
                "pdf_truncated_to_fit_payload_budget",
                pages_kept=pages,
                pages_total=total,
                original_bytes=len(content),
                final_bytes=len(candidate),
            )
            return candidate, total - pages
    return payload, None


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
