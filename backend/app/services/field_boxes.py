"""Where a field's value sits on the page (LP-UI-031, LP-706, LP-709).

The extraction records the verbatim text a value was read from. This finds that
text in the page's own layer and returns the rectangle, **normalised** against the
page box so a client can place it over an image rendered at any zoom.

Same library that renders the page (`page_render`), so the box and the pixels come
from one coordinate space. Two engines would be two spaces, and a box a few points
off is worse than no box — it points confidently at the wrong words.

WHAT THE NUMBERS SAID before LP-706, over 105 stored PDFs / 752 valued fields:

    548  (72.9%)  found on the cited page
     32  ( 4.3%)  cited a page THE DOCUMENT DOES NOT HAVE
     89  (11.8%)  snippet absent from the text layer entirely
     83  (11.0%)  document is a scan, no text layer at all

**The 32 are a fabricated citation, not a near miss.** Not one field cites a
wrong-but-existing page; every one names a page beyond the document's length —
"p.7" of a three-page letter. So there is no cited page to render, and searching
the rest of the document is the only way to show the processor anything at all.
`cited_page_exists=False` travels with the result so the screen can SAY the
citation was wrong rather than quietly substituting a better answer. Correcting the
model silently is how a provenance trail stops being one.

LP-706 — AND WHAT MEASURING IT ACTUALLY SHOWED, which was not what the ticket
predicted. Re-measured over the 76 stored documents that are REAL (excluding four
seeded placeholders whose whole text layer is "DEMO <filename>", and ten with no
usable text), across 608 valued fields:

    515  (84.7%)  found by the exact tier — the behaviour that already existed
    525  (86.3%)  found after this ticket
     +10 (+1.6pt) gained, ALL of them from the value tier
      0            gained by folding the snippet

**Folding the snippet contributed nothing on this corpus, and the reason is that
`search_for` was already better than the ticket assumed.** It tolerates doubled
spaces, tolerates case, and spans separate text runs — so whitespace, which the
ticket named first, was never a cause. What it genuinely cannot do is match a
figure written in another notation (`15000.00` against a page's `15,000.00`,
`$15,000.00`, `15 000,00`) or an accented word spelled without its accent. Those
are real and folding fixes them; they simply do not occur in this corpus.

The folded tier is kept for that reason and labelled honestly rather than claimed
as a win: it costs a page index only when the exact tier has already failed, and
it closes failure modes demonstrated in the tests even though it fired zero times
against real data.

WHAT IS ACTUALLY LEFT, of the 83 real fields still unplaced: 54 number-ish, 25
text, and only 4 ISO dates — so date normalisation, the gap folding does NOT
close, is not the prize either. The commonest keys are `ytd_gross`, `hours`,
`pay_frequency` and `total_deductions_current`, and their snippets are things like
"Total Taxes $3,663.31 + Total Pre-Tax $1,410.00 + Total Post-Tax $335.00" and
"Pay period 12/01/2025 to 12/31/2025 spans full month". **Those are values the
model DERIVED, not text it read.** No matching strategy can locate a number that
was never printed, and a meaningful share of the remaining gap is that.

LP-709 — AND WHY LOOSER MATCHING NEEDS A GUARD SHIPPED WITH IT. An exact search
either finds the text or does not, so a wrong box was close to impossible. Folding
buys coverage by giving that up: `1500` can be found inside `21,500.00`, and a
value matched without its quoted context can land on a different occurrence of the
same figure. So every match is boundary-checked, the loosest tier is refused when
it is ambiguous, and :class:`MatchKind` travels with the result — a box found by
its quoted text and a box found by its bare value are different claims and the
screen is entitled to say which it has.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

#: More matches than this and the snippet is not identifying anything — a bare
#: "Total" appears forty times on a bank statement. Better to show none and let
#: the processor read, than to paint the page and call it provenance.
MAX_MATCHES = 8

#: A folded needle shorter than this is not allowed to locate anything.
#:
#: Folding removes separators, so a two-character needle is a substring of a large
#: share of any page. The exact tier has no such floor — a two-character *verbatim*
#: match is the model's own quoted text and was already trusted before LP-706.
MIN_FOLDED_LENGTH = 4


class MatchKind(StrEnum):
    """How a box was found — a claim about how much the box is worth.

    Carried out to the caller because the three are not interchangeable, and a
    screen that shows them identically is overstating the last one.
    """

    #: The model's quoted text, found character-for-character. What LP-UI-031 did,
    #: and still the first thing tried, so no box that is correct today can move.
    EXACT = "exact"
    #: The quoted text, found after folding formatting away on both sides.
    NORMALISED = "normalised"
    #: The quoted text was not on the page in any form; the VALUE itself was. The
    #: weakest of the three — the model's claim about what it read could not be
    #: confirmed, only its answer located.
    VALUE = "value"


@dataclass(frozen=True)
class BoxRequest:
    """What is known about one field, for locating it.

    ``value`` is carried for LP-709: it is both the last-resort needle and the
    thing a box is checked against.
    """

    snippet: str
    value: str
    cited_page: int


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
    """Where a field was found, and what that says about the citation."""

    boxes: tuple[FieldBox, ...]
    #: False when the extraction cited a page number the document does not have.
    #: The screen says so; it does not quietly show a better page.
    cited_page_exists: bool
    #: True when the boxes came from a page other than the cited one.
    found_elsewhere: bool
    #: How the boxes were found, or None when there are none (LP-709).
    match_kind: MatchKind | None = None


# --- Folding (LP-706) ------------------------------------------------------- #

#: Characters folded away entirely before comparing.
#:
#: Everything here is FORMATTING, not content: currency marks, thousands and
#: decimal separators, spacing, and the punctuation a table or a line break can
#: insert between two halves of one figure. Removing them is what lets
#: ``15,000.00`` match ``15 000,00`` and a value split across two table cells match
#: at all.
_FOLD_AWAY = re.compile("[\\s,. $\\u00a3\\u20ac%()\\[\\]\\-\\u2013\\u2014/:;'\"`*_\\u00a0]+")


def fold(text: str) -> str:
    """A comparable form of ``text``: lowercase, unaccented, formatting removed.

    NFKD FIRST, and it does more work than it looks. It decomposes the ligatures a
    PDF text layer really contains — ``ﬁ`` becomes ``fi``, ``ﬂ`` becomes ``fl`` —
    which is one of the ways a model's retyped snippet fails to match text that is
    plainly there on the page. It also splits accents off their letters so the
    combining marks can be dropped.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _FOLD_AWAY.sub("", without_marks).casefold()


@dataclass(frozen=True)
class _PageIndex:
    """A page's words, folded into one string that can be searched as a substring.

    ONE STRING, NOT A LIST OF WORDS, and that is the point. A figure split across
    two table cells is two words in the layer and one value on the page; searching
    word by word cannot rejoin them, and searching the concatenation can. ``starts``
    maps each character back to the word it came from, so a match still resolves to
    rectangles.
    """

    text: str
    #: For each character of `text`, the index of the word it belongs to.
    owner: tuple[int, ...]
    #: The character offset at which each word starts, for boundary checks.
    word_start: frozenset[int]
    #: The character offset one past each word's end.
    word_end: frozenset[int]
    rects: tuple[pymupdf.Rect, ...]


def _index_page(page: pymupdf.Page) -> _PageIndex:
    """Fold a page's word list into a searchable index. Empty for a page with no text."""
    text_parts: list[str] = []
    owner: list[int] = []
    starts: set[int] = set()
    ends: set[int] = set()
    rects: list[pymupdf.Rect] = []
    cursor = 0
    for word in page.get_text("words"):  # type: ignore[no-untyped-call]
        x0, y0, x1, y1, raw = word[0], word[1], word[2], word[3], word[4]
        folded = fold(str(raw))
        if not folded:
            # A word that folds to nothing is pure punctuation. It has a rectangle
            # and no content, so it must not own any character or a match could be
            # attributed to it.
            continue
        index = len(rects)
        rects.append(pymupdf.Rect(x0, y0, x1, y1))  # type: ignore[no-untyped-call]
        text_parts.append(folded)
        owner.extend([index] * len(folded))
        starts.add(cursor)
        cursor += len(folded)
        ends.add(cursor)
    return _PageIndex(
        text="".join(text_parts),
        owner=tuple(owner),
        word_start=frozenset(starts),
        word_end=frozenset(ends),
        rects=tuple(rects),
    )


def _runs(index: _PageIndex, needle: str) -> list[tuple[int, int]]:
    """Word-index ranges where `needle` occurs, as ``[start, end)`` pairs.

    ALIGNED TO WORD BOUNDARIES at both ends, which is the whole of LP-709's guard
    on this tier. Folding removes separators, so an unaligned substring search finds
    ``1500`` inside ``21,500.00`` — a box drawn confidently over the wrong figure.
    Requiring the match to begin where a word begins and end where a word ends
    makes that impossible without rejecting any real match: a value the page
    contains is always some whole run of the page's own words.
    """
    if len(needle) < MIN_FOLDED_LENGTH or not index.text:
        return []
    found: list[tuple[int, int]] = []
    at = index.text.find(needle)
    while at != -1 and len(found) <= MAX_MATCHES:
        end = at + len(needle)
        if at in index.word_start and end in index.word_end:
            found.append((index.owner[at], index.owner[end - 1] + 1))
        at = index.text.find(needle, at + 1)
    return found


def _union(rects: tuple[pymupdf.Rect, ...]) -> pymupdf.Rect:
    """The smallest rectangle enclosing all of `rects` — the box for a multi-word match."""
    box = pymupdf.Rect(rects[0])  # type: ignore[no-untyped-call]
    for rect in rects[1:]:
        box |= rect
    return box


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


# --- The three tiers -------------------------------------------------------- #


def _exact(page: pymupdf.Page, snippet: str, page_number: int) -> tuple[FieldBox, ...]:
    """Tier 1 — the model's quoted text, character-for-character.

    KEPT FIRST so LP-706 can only add boxes, never move one. Every box that was
    correct before this ticket is found here, by the same call, in the same order,
    and never reaches the folding below.
    """
    hits = page.search_for(snippet)
    if not hits or len(hits) > MAX_MATCHES:
        return ()
    return tuple(_normalise(rect, page.rect, page_number) for rect in hits)


def _folded(
    index: _PageIndex, page: pymupdf.Page, needle: str, page_number: int
) -> tuple[FieldBox, ...]:
    """Tiers 2 and 3 — a folded needle against the page's folded word stream."""
    runs = _runs(index, needle)
    if not runs or len(runs) > MAX_MATCHES:
        return ()
    return tuple(
        _normalise(_union(index.rects[start:end]), page.rect, page_number) for start, end in runs
    )


_EMPTY = BoxLookup(boxes=(), cited_page_exists=True, found_elsewhere=False)


def _search_page(
    doc: pymupdf.Document, page_index: int, request: BoxRequest
) -> tuple[tuple[FieldBox, ...], MatchKind | None]:
    """Locate one field on one page, best tier first."""
    page = doc[page_index]
    page_number = page_index + 1

    found = _exact(page, request.snippet, page_number)
    if found:
        return found, MatchKind.EXACT

    index = _index_page(page)
    folded_snippet = fold(request.snippet)
    found = _folded(index, page, folded_snippet, page_number)
    if found:
        return found, MatchKind.NORMALISED

    # TIER 3, AND IT IS HELD TO A STRICTER RULE (LP-709). The quoted text could not
    # be confirmed anywhere on this page, so all we have is the answer. A figure
    # that appears twice — the same amount as a subtotal and a total — gives no way
    # to tell which one the model read, and drawing both invites a processor to
    # verify against whichever they look at first. One occurrence, or none.
    folded_value = fold(request.value)
    if not folded_value or folded_value == folded_snippet:
        return (), None
    by_value = _folded(index, page, folded_value, page_number)
    if len(by_value) == 1:
        return by_value, MatchKind.VALUE
    return (), None


def _lookup_in(doc: pymupdf.Document, request: BoxRequest) -> BoxLookup:
    if not request.snippet.strip() and not request.value.strip():
        return _EMPTY
    try:
        index = request.cited_page - 1
        cited_exists = 0 <= index < doc.page_count
        if cited_exists:
            found, kind = _search_page(doc, index, request)
            if found:
                return BoxLookup(
                    boxes=found,
                    cited_page_exists=True,
                    found_elsewhere=False,
                    match_kind=kind,
                )
        # Either the citation names a page that does not exist, or the text is not
        # on the page it named. Both are worth showing the processor SOMETHING —
        # but flagged, never silently.
        for other in range(doc.page_count):
            if other == index:
                continue
            found, kind = _search_page(doc, other, request)
            if found:
                return BoxLookup(
                    boxes=found,
                    cited_page_exists=cited_exists,
                    found_elsewhere=True,
                    match_kind=kind,
                )
        return BoxLookup(boxes=(), cited_page_exists=cited_exists, found_elsewhere=False)
    except Exception:
        # Never logs the snippet or the value — both are verbatim borrower text.
        logger.warning("field_box_lookup_failed", cited_page=request.cited_page)
        return _EMPTY


def _lookup_many_sync(content: bytes, requests: dict[str, BoxRequest]) -> dict[str, BoxLookup]:
    if not requests:
        return {}
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")  # type: ignore[no-untyped-call]
    except Exception:
        return dict.fromkeys(requests, _EMPTY)
    try:
        return {key: _lookup_in(doc, request) for key, request in requests.items()}
    finally:
        doc.close()  # type: ignore[no-untyped-call]


async def find_all_field_boxes(
    content: bytes, requests: dict[str, BoxRequest]
) -> dict[str, BoxLookup]:
    """Locate every field, opening the document ONCE.

    A document carries tens of fields, and each lookup can scan every page. Opening
    and parsing the PDF per field multiplies that by the field count for no gain —
    the bytes are the same bytes. One open, one pass of searches, and the result is
    keyed by field so the caller can still treat each answer separately.

    Async, never raises: a document that will not open yields an empty lookup for
    every field rather than a 500 on a screen whose job is to show a page.
    """
    return await asyncio.to_thread(_lookup_many_sync, content, requests)


async def find_field_boxes(
    content: bytes, *, snippet: str, value: str = "", cited_page: int
) -> BoxLookup:
    """Locate one field. See `find_all_field_boxes` for many at once."""
    request = BoxRequest(snippet=snippet, value=value, cited_page=cited_page)
    found = await find_all_field_boxes(content, {"_": request})
    return found.get("_", _EMPTY)
