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

#: How many pages one request may OCR before it stops trying.
#:
#: OCR RUNS INSIDE THE REQUEST and the client gives up at 30 s
#: (`frontend/lib/api/client.ts`). Measured here at ~0.74 s for a dense letter
#: page and ~0.98 s on the reviewer's own machine, so a 30-page scanned bank
#: statement is 22-30 s of one thread — the processor sees no boxes at all, and
#: nothing is cached across requests, so the next viewer pays it again.
#:
#: 12 is chosen from the corpus rather than picked: the most pages any stored
#: document needs OCR'd is 9, the 95th percentile is 1, and the median is 0. So
#: the cap costs nothing on anything here while bounding the worst case at about
#: nine seconds. A document past it keeps boxes for the pages that were read and
#: loses them for the rest, which is the same partial state a scan already
#: produces — never an error, and never a wrong box.
MAX_OCR_PAGES_PER_REQUEST = 12


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


def words_for(
    page: pymupdf.Page, budget: list[int] | None = None
) -> list[tuple[float, float, float, float, str]]:
    """A page's words: its own where it has them, OCR'd where it does not.

    A REAL TEXT LAYER IS NEVER DISCARDED — and that is narrower than "native words
    are never discarded", which is what this said and is not what it can do. A
    page carrying one or two stray words is a SCAN with a stamp on it, and giving
    up two exact rectangles to read the other four hundred is the right trade; a
    page carrying `NATIVE_WORD_THRESHOLD` or more has a text layer, and no amount
    of OCR gets to replace it. The threshold decides which of those a page is, and
    the honest statement of the rule is about the layer rather than the words.

    The first version returned OCR whenever the native count was under the
    threshold, without asking whether OCR had found anything — so a legitimate
    sparse page was rasterised and re-read for however many estimates Tesseract
    produced. It broke a test immediately, which is the only reason it did not
    ship.

    BELOW THE THRESHOLD, OCR ONLY HAS TO BEAT WHAT WAS THERE. Requiring it to
    reach `NATIVE_WORD_THRESHOLD` as well looked symmetrical and refused its output
    in the case the ticket exists for: a page with NO text layer where Tesseract
    read three words returned nothing at all, on the reasoning that three
    estimates should not displace exact rectangles — of which there were none.

    A page where Tesseract is unavailable, or returns nothing, therefore keeps
    whatever it had.
    """
    native = [
        (float(w[0]), float(w[1]), float(w[2]), float(w[3]), str(w[4]))
        for w in page.get_text("words")  # type: ignore[no-untyped-call]
    ]
    # THROUGH `has_native_words`, not a second copy of its condition. Inlined, the
    # rule existed twice — and the tests assert against the function, so a change
    # made here would have left them green while the behaviour moved.
    if has_native_words(page):
        return native
    # THE BUDGET IS SPENT HERE, where the raster is about to happen — not counted
    # per page visited, since a page with a text layer costs nothing. A mutable
    # one-element list rather than a counter object: the caller owns it for the
    # length of one request and there is nothing else to carry.
    if budget is not None:
        if budget[0] <= 0:
            return native
        budget[0] -= 1
    recognised = ocr_words(page)
    # NOTHING TO PROTECT, so nothing to weigh. A page with no words of its own has
    # no exact rectangles at stake, and requiring OCR to clear the threshold there
    # refused its output in the case this ticket exists for — zero native and three
    # recognised returned NOTHING, guarding geometry that did not exist. The guard
    # was scoped by the symptom (a word count) rather than by what it guards.
    if not native:
        return recognised
    # There ARE exact rectangles here. Give them up only for something that looks
    # like a text layer rather than a slightly luckier reading of the same page.
    if len(recognised) >= NATIVE_WORD_THRESHOLD:
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
