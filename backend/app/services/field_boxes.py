"""Where a field's value sits on the page (LP-UI-031).

The extraction records the verbatim text a value was read from. This finds that
text in the page's own layer with `page.search_for()` and returns the rectangle,
**normalised** against the page box so a client can place it over an image
rendered at any zoom.

Same library that renders the page (`page_render`), so the box and the pixels come
from one coordinate space. Two engines would be two spaces, and a box a few points
off is worse than no box — it points confidently at the wrong words.

WHAT THE NUMBERS SAY, measured over 105 stored PDFs / 752 valued fields:

    548  (72.9%)  found on the cited page
     32  ( 4.3%)  cited a page THE DOCUMENT DOES NOT HAVE
     89  (11.8%)  snippet absent from the text layer entirely
     83  (11.0%)  document is a scan, no text layer at all

So a box is *absent* for roughly a quarter of fields, and the reviewer's no-box
state is ordinary rather than exceptional.

**The 32 are a fabricated citation, not a near miss.** Not one field cites a
wrong-but-existing page; every one of them names a page beyond the document's
length — "p.7" of a three-page letter. So there is no cited page to render, and
searching the rest of the document is the only way to show the processor anything
at all. This does that, and `cited_page_exists=False` travels with the result so
the screen can SAY the citation was wrong rather than quietly substituting a
better answer. Correcting the model silently is how a provenance trail stops
being one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

#: More matches than this and the snippet is not identifying anything — a bare
#: "Total" appears forty times on a bank statement. Better to show none and let
#: the processor read, than to paint the page and call it provenance.
MAX_MATCHES = 8


@dataclass(frozen=True)
class FieldBox:
    """One normalised rectangle, 0..1 relative to the page box.

    Normalised rather than absolute so a client can overlay it on an image
    rendered at any zoom without knowing which zoom that was.
    """

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class BoxLookup:
    """Where a snippet was found, and what that says about the citation."""

    boxes: tuple[FieldBox, ...]
    #: False when the extraction cited a page number the document does not have.
    #: The screen says so; it does not quietly show a better page.
    cited_page_exists: bool
    #: True when the boxes came from a page other than the cited one.
    found_elsewhere: bool


def _normalise(rect: pymupdf.Rect, page_rect: pymupdf.Rect, page_number: int) -> FieldBox:
    width = float(page_rect.width) or 1.0
    height = float(page_rect.height) or 1.0
    return FieldBox(
        page=page_number,
        x0=float(rect.x0) / width,
        y0=float(rect.y0) / height,
        x1=float(rect.x1) / width,
        y1=float(rect.y1) / height,
    )


def _search_page(doc: pymupdf.Document, index: int, snippet: str) -> tuple[FieldBox, ...]:
    page = doc[index]
    hits = page.search_for(snippet)
    if not hits or len(hits) > MAX_MATCHES:
        return ()
    return tuple(_normalise(rect, page.rect, index + 1) for rect in hits)


_EMPTY = BoxLookup(boxes=(), cited_page_exists=True, found_elsewhere=False)


def _lookup_in(doc: pymupdf.Document, snippet: str, cited_page: int) -> BoxLookup:
    if not snippet.strip():
        return _EMPTY
    try:
        index = cited_page - 1
        cited_exists = 0 <= index < doc.page_count
        if cited_exists:
            found = _search_page(doc, index, snippet)
            if found:
                return BoxLookup(boxes=found, cited_page_exists=True, found_elsewhere=False)
        # Either the citation names a page that does not exist, or the text is not
        # on the page it named. Both are worth showing the processor SOMETHING —
        # but flagged, never silently.
        for other in range(doc.page_count):
            if other == index:
                continue
            found = _search_page(doc, other, snippet)
            if found:
                return BoxLookup(boxes=found, cited_page_exists=cited_exists, found_elsewhere=True)
        return BoxLookup(boxes=(), cited_page_exists=cited_exists, found_elsewhere=False)
    except Exception:
        # Never logs the snippet — it is verbatim borrower text.
        logger.warning("field_box_lookup_failed", cited_page=cited_page)
        return _EMPTY


def _lookup_many_sync(content: bytes, requests: dict[str, tuple[str, int]]) -> dict[str, BoxLookup]:
    if not requests:
        return {}
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:
        return dict.fromkeys(requests, _EMPTY)
    try:
        return {
            key: _lookup_in(doc, snippet, cited_page)
            for key, (snippet, cited_page) in requests.items()
        }
    finally:
        doc.close()  # type: ignore[no-untyped-call]


async def find_all_field_boxes(
    content: bytes, requests: dict[str, tuple[str, int]]
) -> dict[str, BoxLookup]:
    """Locate every field's snippet, opening the document ONCE.

    A document carries tens of fields, and each lookup can scan every page. Opening
    and parsing the PDF per field multiplies that by the field count for no gain —
    the bytes are the same bytes. One open, one pass of searches, and the result is
    keyed by field so the caller can still treat each answer separately.

    Async, never raises: a document that will not open yields an empty lookup for
    every field rather than a 500 on a screen whose job is to show a page.
    """
    return await asyncio.to_thread(_lookup_many_sync, content, requests)


async def find_field_boxes(content: bytes, *, snippet: str, cited_page: int) -> BoxLookup:
    """Locate one field's `snippet`. See `find_all_field_boxes` for many at once."""
    found = await find_all_field_boxes(content, {"_": (snippet, cited_page)})
    return found.get("_", _EMPTY)
