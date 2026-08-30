"""Render one PDF page to a PNG, deterministically (LP-UI-030).

The document reviewer needs a real page on screen. This renders it **server-side
with PyMuPDF**, which is already on the production path, rather than adding a PDF
engine to the browser.

That is not only a dependency argument. LP-UI-031 derives a field's highlight by
searching the page's text layer, and PyMuPDF returns those rectangles in the
page's own coordinate space. Rendering the image with the same library at a known
zoom means the box and the pixels come from **one** renderer — two engines would
be two coordinate spaces, and a highlight that lands a few points off is worse
than no highlight, because it points confidently at the wrong words.

The page geometry travels with the image so a caller never has to guess the
scale: `PageImage` carries the source page's width and height in points and the
zoom that was applied.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

#: Rendering zoom. 2x a 72dpi page is 144dpi — legible for reading a figure off a
#: pay stub without making a full-page PNG that costs more to ship than the PDF.
DEFAULT_ZOOM = 2.0

#: An upper bound on the zoom a caller may ask for. A page rendered at 8x is a
#: ~50MB PNG; the cap is what stops one query making the server do that.
MAX_ZOOM = 4.0


@dataclass(frozen=True)
class PageImage:
    """One rendered page, with the geometry needed to place a box on it."""

    png: bytes
    #: The page's own size in POINTS, before zoom — the space `search_for`
    #: rectangles are expressed in.
    width_points: float
    height_points: float
    zoom: float
    #: How many pages the document has. Carried with the page because the
    #: renderer has the document open anyway — counting it here costs nothing,
    #: and a second endpoint to ask "how many pages?" would open the same file
    #: again to answer a question this one already knows.
    page_count: int

    @property
    def pixel_width(self) -> int:
        return int(self.width_points * self.zoom)

    @property
    def pixel_height(self) -> int:
        return int(self.height_points * self.zoom)


def _render_sync(content: bytes, page_number: int, zoom: float) -> PageImage | None:
    """Render 1-indexed `page_number`. `None` for unreadable bytes or a bad page.

    Never raises: a corrupt or encrypted PDF, or a page a caller asked for that
    the document does not have, is an absent image rather than a 500. The reviewer
    has a designed no-page state and it is reachable often enough to matter — 12
    of 105 stored PDFs are scans, and a cited page is out of range on ~4% of
    fields (measured, LP-UI-030).
    """
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:
        return None
    try:
        index = page_number - 1
        if index < 0 or index >= doc.page_count:
            return None
        page = doc[index]
        rect = page.rect
        matrix = pymupdf.Matrix(zoom, zoom)  # type: ignore[no-untyped-call]
        pixmap = page.get_pixmap(matrix=matrix)
        png: bytes = pixmap.tobytes("png")  # type: ignore[no-untyped-call]
        return PageImage(
            png=png,
            width_points=float(rect.width),
            height_points=float(rect.height),
            zoom=zoom,
            page_count=doc.page_count,
        )
    except Exception:
        # Never logs page CONTENT — a rendered page is borrower PII.
        logger.warning("page_render_failed", page_number=page_number)
        return None
    finally:
        doc.close()  # type: ignore[no-untyped-call]


async def render_page(
    content: bytes, *, page_number: int, zoom: float = DEFAULT_ZOOM
) -> PageImage | None:
    """Render one page to PNG. Async, never raises. See `_render_sync`."""
    bounded = max(1.0, min(float(zoom), MAX_ZOOM))
    return await asyncio.to_thread(_render_sync, content, page_number, bounded)
