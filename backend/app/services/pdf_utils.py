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


#: The provider's document ceiling is **32 MB on the REQUEST** — i.e. on the base64-encoded
#: payload, which is 4/3 the size of the file on disk. Anyone reasoning in raw megabytes is a third
#: under the number actually being checked, which is how LF-ZE9N's 23.8 MB contract, comfortably
#: "under 32 MB", was rejected.
#:
#: 32 MB encoded / (4/3) = 24 MB raw exactly. The 1 MB held back covers the system prompt and the
#: JSON envelope, neither of which is known at this layer; a classification system prompt is
#: single-digit KB, so this is margin, not a guess.
MAX_DOCUMENT_PAYLOAD_BYTES = 23 * 1024 * 1024

#: The page half of the same ceiling. SIZED FOR A 200K-CONTEXT MODEL: the provider allows 600
#: pages, dropping to 100 for 200K-context models, and every model in this pipeline is
#: ``claude-haiku-4-5`` (200K). If any of these paths ever move to a 1M-context model, 100 becomes
#: needlessly tight — and without this note nobody would know why it was chosen.
PROVIDER_MAX_PAGES_200K_CONTEXT = 100


@dataclass(frozen=True)
class PayloadFit:
    """The result of fitting a document to the provider's limits.

    Three states, kept distinct because two of them used to look identical to a caller:
    nothing needed doing, pages were dropped to fit, or trimming could not get under the limit at
    all. The last one matters — a document that could NOT be trimmed is about to be rejected, and
    recording it as "no trimming needed" would hide that.
    """

    payload: bytes
    #: Pages removed by the SIZE cap, beyond whatever the page cap already took. 0 when size never
    #: bound.
    pages_dropped: int = 0
    #: True when the document is still over budget after trimming — a single page too large, or an
    #: unreadable PDF. The call will fail as ``oversized``, honestly.
    still_over_budget: bool = False


def encoded_payload_size(raw_bytes: int) -> int:
    """Bytes on the wire once base64-encoded — ``4 * ceil(n / 3)``.

    The limit that rejected LF-ZE9N's contract applies to the ENCODED payload, which is a third
    larger than the file on disk.
    """
    return 4 * ((raw_bytes + 2) // 3)


async def fit_pdf_to_payload_budget(
    content: bytes,
    media_type: str,
    *,
    max_pages: int,
    max_bytes: int = MAX_DOCUMENT_PAYLOAD_BYTES,
) -> PayloadFit:
    """Trim a PDF to ``max_pages``, then to the LARGEST page count that fits ``max_bytes``.

    LP-636 defect 4. There was a cap on PAGES and none on BYTES, and bytes are what rejected
    LF-ZE9N's 23.8 MB purchase contract: it was already inside the 15-page classification cap — a
    high-DPI scan — so the page cap was a no-op and the call failed with HTTP 400, producing no
    data at all.

    KEEPS AS MANY PAGES AS FIT, deliberately. It halves to find some fitting count, then binary
    searches back UP for the largest one. Halving alone would return 8 pages for a 16-page document
    that fits at 15 — seven pages discarded to save four local slices. The asymmetry runs the other
    way: a slice is PyMuPDF and milliseconds, while a dropped page is content the model never sees.
    Since the whole point here is turning a hard rejection into a partial read, HOW partial is the
    entire quality of the outcome — and the case this exists for is a contract whose signature sits
    on the last page.

    DROPPING PAGES IS NOT THE BEST ANSWER, ONLY THE SAFE ONE. Re-rendering at a lower DPI would
    keep every page; that needs image resampling with its own quality and OCR trade-offs. This
    reuses the tested slicing path and needs none.

    Never raises. A non-PDF, or bytes that will not parse, come back unchanged for the existing
    error path to handle.
    """
    if media_type.lower().strip() != _PDF_MEDIA_TYPE:
        return PayloadFit(content)

    payload = await cap_pdf_pages(content, media_type, max_pages)
    if encoded_payload_size(len(payload)) <= max_bytes:
        return PayloadFit(payload)

    total = await pdf_page_count(payload)
    if total is None or total <= 1:
        # Unreadable, or one page already over budget — trimming cannot help. Say so rather than
        # returning a shrug the caller reads as "fine".
        logger.warning(
            "pdf_cannot_be_trimmed_under_payload_budget",
            pages=total,
            encoded_bytes=encoded_payload_size(len(payload)),
            max_bytes=max_bytes,
        )
        return PayloadFit(payload, still_over_budget=True)

    async def _fits(pages: int) -> bytes | None:
        candidate = await first_n_pages(payload, pages)
        if candidate is None:
            return None
        return candidate if encoded_payload_size(len(candidate)) <= max_bytes else None

    # Phase 1 — halve until something fits, remembering the smallest count known NOT to fit.
    too_big = total
    best_pages, best = 0, b""
    probe = total
    while probe > 1:
        probe = max(1, probe // 2)
        candidate = await _fits(probe)
        if candidate is not None:
            best_pages, best = probe, candidate
            break
        too_big = probe

    if best_pages == 0:
        logger.warning(
            "pdf_cannot_be_trimmed_under_payload_budget",
            pages=total,
            encoded_bytes=encoded_payload_size(len(payload)),
            max_bytes=max_bytes,
        )
        return PayloadFit(payload, still_over_budget=True)

    # Phase 2 — binary search UP for the largest count that still fits. A handful more slices, and
    # it recovers most of what phase 1 gave away.
    while best_pages + 1 < too_big:
        mid = (best_pages + too_big) // 2
        candidate = await _fits(mid)
        if candidate is None:
            too_big = mid
        else:
            best_pages, best = mid, candidate

    logger.warning(
        "pdf_truncated_to_fit_payload_budget",
        pages_kept=best_pages,
        pages_total=total,
        original_bytes=len(content),
        final_bytes=len(best),
    )
    return PayloadFit(best, pages_dropped=total - best_pages)


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
