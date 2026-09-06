"""Word positions for a page that has none (LP-708).

**This is not about reading the document.** Claude already reads scans, and reads
them well — measured on the stored corpus, scanned PDFs yield 9.0 extracted values
per document against 8.0 for typed ones. Extraction on a photocopy is not broken
and nothing here touches it.

What Claude never returns is a POSITION. It is shown a picture, not a coordinate
space. So a highlight box has always come from a second, separate source:
``page.get_text("words")`` on a typed page, and **nothing at all** on a scanned
one — 34 of 288 stored pages, 11.8%. That absence is the whole of this module.

WHICH LOWERS THE BAR A LONG WAY. The value displayed is Claude's and is
authoritative; OCR only has to produce words good enough for LP-706's matcher to
find that value among them. OCR reading ``15,OOO.OO`` for ``15,000.00`` is
tolerable — the match still lands, the box is still right, and the figure on screen
is still Claude's. That is a much weaker requirement than "transcribe this
document", and it is why a local engine is enough.

LOCAL, AND NOT FOR COST REASONS. Priced properly the hosted services are ~$0.0015
a page, which at this volume is roughly fifty cents a month — cost is not the
deciding factor and should not be quoted as if it were. The reason is what is in
the documents: SSNs, account numbers, borrower names. Sending them to a
third-party API is a data-residency decision nobody has been asked for, and a
module about drawing rectangles is not where that gets decided by default.

PyMuPDF's OWN OCR, not a new Python dependency. ``get_textpage_ocr`` drives
Tesseract through the same library that renders the page and supplies the native
word list, so the rectangles come back in the page's POINT space already — the
pixel-to-point conversion the design worried about is PyMuPDF's problem, not ours,
and there is no second coordinate space to get wrong.

IT DEGRADES, IT DOES NOT CRASH. The Tesseract binary is a system package and may
simply be absent — in a container that has not installed it, on a developer's
machine, anywhere. A page with no OCR available is a page with no words, which is
the state this module exists to improve and is already handled everywhere
downstream: no box, and the reviewer says so.
"""

from __future__ import annotations

from functools import cache

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

#: Pixels on the long edge of the raster Tesseract is given.
#:
#: MEASURED, both directions, because both fail. On a normal 612x1008 page the
#: raster size IS the quality: 2996px found 103 words and every anchor, 1400px
#: found ELEVEN and lost most of them. On an oversized 3331x5221 page — the same
#: survey-sized pages LP-704 found shipping 69 MB — a fixed 300 dpi rasters to
#: 21,754px and takes 7.5 s, while 3118px takes 1.5 s and finds the same words.
#:
#: So the target is a raster, not a dpi, for the same reason `MAX_RENDERED_EDGE`
#: is: a dpi is a multiplier, and the page it multiplies is unbounded.
TARGET_EDGE_PX = 3000

#: Tesseract refuses below ~70 and silently substitutes it ("Invalid resolution 43
#: dpi. Using 70 instead"), so the floor is its, not ours. The ceiling is where
#: more pixels stopped buying words on the corpus.
MIN_DPI = 70
MAX_DPI = 300

#: A page with fewer native words than this is treated as having no text layer.
#:
#: Not zero. A scanned page often carries a stamp, a footer, or a single
#: OCR-on-scan artefact, and one stray word does not make a page searchable. The
#: same threshold decides the split reported in LP-708 (34 of 288 pages).
NATIVE_WORD_THRESHOLD = 5


def dpi_for(page_rect: pymupdf.Rect) -> int:
    """The dpi that rasters this page to about `TARGET_EDGE_PX` on its long edge."""
    longest = max(float(page_rect.width), float(page_rect.height))
    if longest <= 0:
        return MIN_DPI
    return max(MIN_DPI, min(MAX_DPI, round(72.0 * TARGET_EDGE_PX / longest)))


@cache
def ocr_available() -> bool:
    """Whether Tesseract can be reached at all.

    Cached: the answer cannot change inside a process, and asking costs a
    filesystem probe that would otherwise run per scanned page.

    A FALSE HERE IS NOT AN ERROR. It means boxes on scanned pages are unavailable,
    which is exactly the state before this ticket, and every caller already treats
    a page with no words as ordinary.
    """
    try:
        pymupdf.get_tessdata()  # type: ignore[no-untyped-call]
    except Exception:
        logger.info("ocr_unavailable")
        return False
    return True


def has_native_words(page: pymupdf.Page) -> bool:
    """Whether this PAGE carries a usable text layer.

    PER PAGE, NEVER PER DOCUMENT, and that is the whole reason this is a function.
    Six of 101 stored documents are MIXED — some pages typed, some photocopied —
    so a document-level question gets them wrong in both directions: it OCRs pages
    that already have exact positions, and skips pages that have none.
    """
    return len(page.get_text("words")) >= NATIVE_WORD_THRESHOLD  # type: ignore[no-untyped-call]


def words_for(page: pymupdf.Page) -> list[tuple[float, float, float, float, str]]:
    """A page's words: its own where it has them, OCR'd where it does not.

    NATIVE WORDS ARE NEVER DISCARDED, and getting that wrong is what this
    docstring is for. The first version returned OCR whenever the native count was
    under the threshold — so a legitimate page holding three words was rasterised
    and re-read, throwing away three EXACT rectangles for however many estimates
    Tesseract produced. It broke a test immediately, which is the only reason it
    was not shipped.

    The threshold decides whether a page looks like a scan. It does not get to
    decide that a page's own text is worthless.

    SO OCR HAS TO CLEAR THE SAME BAR IT WAS CALLED IN TO FILL, not merely beat the
    native count. "More words wins" was the first rule and it is wrong in a way a
    test caught: on a genuine two-word page, OCR finding three would displace two
    EXACT rectangles with three estimates. Requiring `NATIVE_WORD_THRESHOLD` words
    of its own says the honest thing — if OCR cannot find a text layer either, the
    page has no text layer, and the few exact positions it does have are the best
    answer available.

    A page where Tesseract is unavailable, or returns nothing, therefore keeps
    whatever it had.
    """
    native = [
        (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
        for w in page.get_text("words")  # type: ignore[no-untyped-call]
    ]
    if len(native) >= NATIVE_WORD_THRESHOLD:
        return native
    recognised = ocr_words(page)
    if len(recognised) >= NATIVE_WORD_THRESHOLD and len(recognised) > len(native):
        return recognised
    return native


def ocr_words(page: pymupdf.Page) -> list[tuple[float, float, float, float, str]]:
    """`(x0, y0, x1, y1, word)` for a page with no text layer, in POINT space.

    The same shape ``page.get_text("words")`` returns, so a caller that already
    handles native words needs no second code path — which is the point, since the
    matcher above it must not know or care which kind of page it is looking at.

    Empty when Tesseract is unavailable or the page yields nothing. Never raises:
    a page that cannot be OCR'd is a page with no words, and no box is a state the
    reviewer is built to show.
    """
    if not ocr_available():
        return []
    try:
        textpage = page.get_textpage_ocr(  # type: ignore[no-untyped-call]
            flags=0, dpi=dpi_for(page.rect), full=True
        )
        words = page.get_text("words", textpage=textpage)  # type: ignore[no-untyped-call]
    except Exception:
        # Never logs the page CONTENT — a scanned page is borrower PII.
        logger.warning("ocr_failed", page_number=page.number)
        return []
    return [(float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4])) for w in words]
