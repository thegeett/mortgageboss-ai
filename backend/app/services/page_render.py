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

#: An upper bound on the zoom a caller may ask for.
#:
#: IT BOUNDS A MULTIPLIER, NOT A RESULT, and that distinction is the whole of
#: LP-704. A cap on the ratio says nothing about the output when the page it
#: multiplies is unbounded — see ``MAX_RENDERED_EDGE``.
MAX_ZOOM = 4.0

#: The longest side, in pixels, that a rendered page may have.
#:
#: WHY A CAP EXISTS AT ALL, measured on a stored document rather than reasoned:
#: one 25 MB survey is a single page of 4047 x 4998 POINTS — 56 by 69 inches. At
#: the default 2x that is 8094 x 9996 px, and the endpoint returned **69.3 MB in
#: 4.9 s**. At 1x it still returned 23.4 MB. `MAX_ZOOM` did not apply: 2.0 is
#: already under it.
#:
#: (The old comment here claimed a page at 8x was "a ~50MB PNG" and that the zoom
#: cap was what prevented it. Both halves were wrong. A US Letter page at 8x
#: measures 1.37 MB, because PNG compresses a mostly-white page to almost
#: nothing; and 50 MB arrives at 2x on a page nobody thought about.)
#:
#: WHY 3000: the reviewer displays a page in a column of at most 46rem (736 px)
#: and zooms to at most 2.0 in CSS (`zoom.ts`), so 1472 CSS px, or 2944 device px
#: on a 2x screen. Pixels past that are shipped, decoded, and never seen. A US
#: Letter page at the default 2x is 1224 x 1584 and is not touched by this.
MAX_RENDERED_EDGE = 3000


#: What this renderer can open, mapped to MuPDF's own reader name.
#:
#: THE IMAGE TYPES ARE HERE BECAUSE UPLOADS ALREADY ACCEPT THEM.
#: `ALLOWED_CONTENT_TYPES` has taken image/jpeg and image/png since LP-36, and
#: the page endpoint refused everything that was not a PDF — so a photographed
#: pay stub uploaded successfully and then showed the reviewer's no-page state
#: for ever. A missing capability wearing a loading problem's clothes (LP-704).
#:
#: MuPDF opens an image as a one-page document, so the geometry, the page count
#: and the zoom all mean what they already mean and nothing downstream needs a
#: second path. Its page rect is the image's pixels x 0.75 — MuPDF reads an image
#: at 96 DPI and reports 72-dpi points — which matters only to a caller reading
#: `width_points` as "pixels"; a normalised box uses the ratio and is unaffected.
#:
#: THE KEY IS THE GATE; the value is only a hint. MuPDF sniffs the bytes and
#: ignores `filetype` — PDF bytes open under "png" and even "xps" — so this table
#: decides what the endpoint is WILLING to serve, not which parser runs.
RENDERABLE_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


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


def fit_to_budget(zoom: float, width_points: float, height_points: float) -> float:
    """Reduce `zoom` until the rendered page fits `MAX_RENDERED_EDGE`.

    Returns `zoom` unchanged for any page already inside the budget, which is
    every ordinary one — a US Letter page at 2x is 1224 x 1584.

    THE RESULT MAY BE BELOW 1.0, and it has to be. The caller's floor of 1.0 is
    about a caller asking for something silly; this is about a page that is
    genuinely 56 inches wide, where even 1x is 4047 px and 23 MB. A floor applied
    after this would put the budget back out of reach for the only pages that
    need it.
    """
    longest = max(width_points, height_points) * zoom
    if longest <= MAX_RENDERED_EDGE or longest <= 0:
        return zoom
    return zoom * (MAX_RENDERED_EDGE / longest)


def _render_sync(content: bytes, page_number: int, zoom: float, filetype: str) -> PageImage | None:
    """Render 1-indexed `page_number`. `None` for unreadable bytes or a bad page.

    Never raises: a corrupt or encrypted PDF, or a page a caller asked for that
    the document does not have, is an absent image rather than a 500. The reviewer
    has a designed no-page state and it is reachable often enough to matter — 12
    of 105 stored PDFs are scans, and a cited page is out of range on ~4% of
    fields (measured, LP-UI-030).
    """
    try:
        doc = pymupdf.open(stream=content, filetype=filetype)  # type: ignore[no-untyped-call]
    except Exception:
        return None
    try:
        index = page_number - 1
        if index < 0 or index >= doc.page_count:
            return None
        page = doc[index]
        rect = page.rect
        applied = fit_to_budget(zoom, float(rect.width), float(rect.height))
        matrix = pymupdf.Matrix(applied, applied)  # type: ignore[no-untyped-call]
        pixmap = page.get_pixmap(matrix=matrix)
        png: bytes = pixmap.tobytes("png")  # type: ignore[no-untyped-call]
        return PageImage(
            png=png,
            width_points=float(rect.width),
            height_points=float(rect.height),
            # THE ZOOM THAT WAS APPLIED, not the one that was asked for. The
            # client reads this to know the image's scale, and reporting the
            # request would put every derived rectangle off by the reduction.
            zoom=applied,
            page_count=doc.page_count,
        )
    except Exception:
        # Never logs page CONTENT — a rendered page is borrower PII.
        logger.warning("page_render_failed", page_number=page_number)
        return None
    finally:
        doc.close()  # type: ignore[no-untyped-call]


async def render_page(
    content: bytes,
    *,
    page_number: int,
    zoom: float = DEFAULT_ZOOM,
    mime_type: str = "application/pdf",
) -> PageImage | None:
    """Render one page to PNG. Async, never raises. See `_render_sync`.

    `mime_type` decides which reader MuPDF uses. A type it cannot open is an
    absent image, the same as unreadable bytes — the caller has one no-page state
    and does not need a second way to say the same thing.
    """
    filetype = RENDERABLE_TYPES.get(mime_type)
    if filetype is None:
        return None
    bounded = max(1.0, min(float(zoom), MAX_ZOOM))
    return await asyncio.to_thread(_render_sync, content, page_number, bounded, filetype)
