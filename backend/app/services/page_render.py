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
import math
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

#: Types whose pages carry a text layer a quoted snippet can be located in.
#:
#: DELIBERATELY NOT `RENDERABLE_TYPES`, and the two must not be merged. They
#: answer different questions: that one is "will we serve a picture of this
#: page", this one is "can a snippet be found ON the page". An image renders
#: perfectly and contains no text at all, so `/boxes` returns an empty result for
#: one either way — the difference is that keying on this avoids reading the file
#: from storage to discover it.
#:
#: The pairing looks like an oversight next to the renderer's newly widened gate,
#: which is why it is named here rather than left as a bare `!= "application/pdf"`
#: three hundred lines away in the endpoint (LP-704 review).
TEXT_SEARCHABLE_TYPES: frozenset[str] = frozenset({"application/pdf"})


@dataclass(frozen=True)
class PageImage:
    """One rendered page, with the geometry needed to place a box on it."""

    #: The encoded page. PNG for a PDF, JPEG for a photograph — see `_encode`.
    content: bytes
    #: What `content` is, for the response's own `media_type`.
    media_type: str
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


def _bounded_zoom(zoom: float) -> float:
    """The zoom a caller may actually have, with meaningless input refused.

    `zoom` is a query parameter and pydantic accepts `nan`, `inf` and `1e400` as
    floats — all three reach here from a URL. What they cost is not theoretical:
    a NaN matrix renders a **0 x 0 pixmap** (a blank page, reported as a success),
    and an inf matrix asks MuPDF for an **844 TB allocation** and raises.

    `max(1.0, min(zoom, MAX_ZOOM))` already happened to stop both — NaN collapsing
    to 1.0 and inf to 4.0 — but only through Python's min/max returning the
    incumbent on an unordered comparison. That is a subtlety a reader should not
    have to know, no test asserted it, and it silently reversed if the two calls
    were ever reordered. A number that means nothing is treated as one that was
    not supplied.
    """
    if not math.isfinite(zoom):
        return DEFAULT_ZOOM
    return max(1.0, min(zoom, MAX_ZOOM))


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
    # SUBSTITUTE, THEN BUDGET. A first version of this guard RETURNED the default
    # instead, which broke the function's own postcondition on exactly the pages it
    # exists for: `fit_to_budget(nan, 4047, 4998)` gave 2.0, i.e. 9996 px on the
    # long edge — 3.3x over budget, the 69 MB render this whole change was written
    # to stop. Its test used a 612x792 page, where 2.0 is under budget anyway, so
    # it was green by construction and could not have failed.
    #
    # `zoom <= 0` is here for the same reason: a negative multiplier returned
    # unchanged is a negative render matrix.
    if not math.isfinite(zoom) or zoom <= 0:
        zoom = DEFAULT_ZOOM
    longest = max(width_points, height_points) * zoom
    # A degenerate page (0 x 0) lands here too — `0 <= MAX_RENDERED_EDGE` — so
    # there is no separate zero branch to divide by. There WAS one; it could not
    # execute, and its test passed through this branch asserting nothing.
    if longest <= MAX_RENDERED_EDGE:
        return zoom
    return zoom * (MAX_RENDERED_EDGE / longest)


#: How a rendered page is encoded, by what it came FROM.
#:
#: PNG IS THE WRONG CONTAINER FOR A PHOTOGRAPH, and this path exists to serve
#: photographs now. Measured on 2000x1500 of real sensor-like noise: the source
#: JPEG is 4.26 MB, re-encoded as PNG it is 4.72 MB — **larger than the file it is
#: previewing** — and as JPEG it is 1.82 MB. So a photographed pay stub, the exact
#: case LP-704 enabled, was made slower to display than the original it replaced,
#: by the change meant to stop shipping 69 MB.
#:
#: A PDF page stays PNG: it is text and line art, where PNG both compresses better
#: and stays lossless, and where JPEG's ringing lands on the small type a processor
#: is trying to read.
_ENCODING: dict[str, tuple[str, str]] = {
    "application/pdf": ("png", "image/png"),
    "image/jpeg": ("jpg", "image/jpeg"),
    "image/png": ("png", "image/png"),
}

#: Quality for the JPEG path. 85 is the usual "indistinguishable at a glance"
#: point; the page is evidence a processor reads, not an archive master.
_JPEG_QUALITY = 85


#: An image's native scale: MuPDF reads it at 96 DPI and reports its rect at 72,
#: so a rect point is 4/3 of a source pixel and zoom 4/3 reproduces the file's own
#: pixels exactly.
_IMAGE_NATIVE_ZOOM = 4 / 3


def _native_ceiling(mime_type: str) -> float:
    """The highest zoom that still carries information, for this source.

    A PDF is vector: rendering it larger genuinely resolves more, so there is no
    ceiling but the budget. A PHOTOGRAPH has a fixed number of pixels, and the
    default 2.0 renders one at 1.5x its own resolution — inventing half the pixels
    it then spends bytes encoding.

    That is why the preview stayed larger than the source even after the encoder
    was fixed: a 1200x900 JPEG of 1.54 MB came back as 2.36 MB, not because of the
    container but because it had been upscaled first. Capping at native makes the
    preview smaller than the file it previews, which is the property the ticket
    was reaching for.
    """
    return _IMAGE_NATIVE_ZOOM if mime_type.startswith("image/") else float("inf")


def _render_sync(
    content: bytes, page_number: int, zoom: float, filetype: str, mime_type: str
) -> PageImage | None:
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
        applied = fit_to_budget(
            min(zoom, _native_ceiling(mime_type)), float(rect.width), float(rect.height)
        )
        matrix = pymupdf.Matrix(applied, applied)  # type: ignore[no-untyped-call]
        pixmap = page.get_pixmap(matrix=matrix)
        encoder, media_type = _ENCODING.get(mime_type, ("png", "image/png"))
        encoded: bytes = (
            pixmap.tobytes(encoder, jpg_quality=_JPEG_QUALITY)  # type: ignore[no-untyped-call]
            if encoder == "jpg"
            else pixmap.tobytes(encoder)  # type: ignore[no-untyped-call]
        )
        return PageImage(
            content=encoded,
            media_type=media_type,
            width_points=float(rect.width),
            height_points=float(rect.height),
            # THE ZOOM THAT WAS APPLIED, not the one that was asked for, so the
            # header describes the PNG that is actually in the body.
            #
            # The reason first given here — that reporting the request would put
            # "every derived rectangle off by the reduction" — is not true of this
            # client, and inviting someone to build on a dependency that does not
            # exist is worse than saying nothing. Highlight boxes are normalised
            # 0..1 and positioned as percentages of the image's own box
            # (`box-overlay.tsx`), so no rectangle reads the zoom at all; the one
            # consumer multiplies width AND height by it, where it cancels out of
            # the aspect ratio. Reporting the applied value is still right — the
            # intrinsic size then matches the real pixels — for a smaller reason.
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
    # REQUIRED. A default of "application/pdf" reinstates exactly the assumption
    # this change removed: a caller that forgets it for an image document gets
    # None back and renders the no-page state, with no type error and no test
    # failure. There is one caller; making it required costs nothing.
    mime_type: str,
) -> PageImage | None:
    """Render one page to PNG. Async, never raises. See `_render_sync`.

    `mime_type` decides which reader MuPDF uses. A type it cannot open is an
    absent image, the same as unreadable bytes — the caller has one no-page state
    and does not need a second way to say the same thing.
    """
    filetype = RENDERABLE_TYPES.get(mime_type)
    if filetype is None:
        return None
    bounded = _bounded_zoom(float(zoom))
    return await asyncio.to_thread(_render_sync, content, page_number, bounded, filetype, mime_type)
