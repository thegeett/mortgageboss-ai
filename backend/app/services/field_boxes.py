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
its quoted text and a box found by its bare value are different claims.

NOTHING READS `MatchKind` YET, and the sentence that used to end this paragraph
said the screen was "entitled to say which it has". It is not, today:
`FieldBoxPublic` has no such field, the boxes response does not carry it, and the
frontend never mentions it, so a bare-value guess and a verbatim match render
identically to a processor. The distinction is computed and correct and it stops
at the service boundary. Surfacing it is a UI change with its own decision to make
about how a weaker box should look, and it is recorded on LP-706 rather than left
as a promise the code does not keep (LP-706/709 review).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

import pymupdf
import structlog

from app.services.page_ocr import MAX_OCR_PAGES_PER_REQUEST, words_for

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

    Carried out to the caller because the four are not interchangeable, and a
    screen that shows them identically is overstating the last one.
    """

    #: The model's quoted text, found character-for-character. What LP-UI-031 did,
    #: and still the first thing tried, so no box that is correct today can move.
    EXACT = "exact"
    #: The quoted text, found after folding formatting away on both sides.
    NORMALISED = "normalised"
    #: PART of the quoted text: the longest run of it the page actually has, around
    #: the extracted value and carrying MORE than it (LP-707).
    #:
    #: The snippet is often a SYNTHESIS rather than a quotation — "Total Taxes
    #: $3,663.31 + Total Pre-Tax $1,410.00 + Total Post-Tax $335.00" is three
    #: figures from three places on the page joined by a person's arithmetic, and
    #: it is nowhere on the page as one run. Measured on the typed corpus: of 72
    #: fields the first two tiers cannot place, every one has its snippet's words
    #: on the page somewhere, and none has the whole snippet anywhere.
    #:
    #: RANKED ABOVE `VALUE` ONLY BECAUSE IT CARRIES CONTEXT, so a run that turns
    #: out to be the value and nothing else is not this tier — see `_partial`,
    #: where dropping that rule was measured to hand 38 ambiguous figures a box.
    #: It fires TWICE on the stored corpus, both on scanned pages, and never on a
    #: typed one — measured across all 79 documents, not the 69 typed ones the
    #: review's first pass looked at. So it is nearly but not entirely inert, and
    #: is kept on the same footing as `NORMALISED`: a failure mode the tests
    #: demonstrate and real documents almost never present.
    PARTIAL = "partial"
    #: The quoted text was not on the page in any form; the VALUE itself was. The
    #: weakest of the four — the model's claim about what it read could not be
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


#: A run of digits with the separators a number may carry inside it.
_NUMERIC_RUN = re.compile(r"\d[\d.,\s\u00a0]*\d|\d")

#: The decimal separator: the LAST `.` or `,` with one or two digits after it.
#: Three digits after a separator is a thousands group, not a fraction.
_DECIMAL_TAIL = re.compile(r"[.,](\d{1,2})$")

#: Stands in for a decimal point while the rest of the fold runs. A NUL cannot
#: occur in a PDF text layer, so it survives `_FOLD_AWAY` colliding with nothing.
_DECIMAL_MARK = "\x00"


def _canonical_number(run: str) -> str:
    """A number in a form that compares by MAGNITUDE rather than by formatting.

    THE FOLD DELETED EVERY SEPARATOR, which made it blind to magnitude:
    `fold("1,500.00") == fold("150,000") == "150000"`, so a field worth 1,500.00
    drew a confident NORMALISED box over a page's $150,000 — a figure a hundred
    times larger, and the word-boundary rule cannot catch it because both sides are
    whole words. Separators are CONTENT in a number, and formatting only between
    equivalent renderings of the same number.

    What tells those apart is positional rather than per-character: the decimal
    separator is the last `.` or `,` with one or two digits after it, and every
    other `.`, `,` or space is grouping. That reads `15,000.00`, `15 000,00` and
    `15000.00` as one number while keeping `150,000` distinct from `1,500.00`.

    Trailing fraction zeros go, so `1500.0`, `1500.00` and `1500` still agree —
    the same figure to different precision is the difference the fold is for.
    """
    compact = re.sub(r"[\s\u00a0]", "", run)
    tail = _DECIMAL_TAIL.search(compact)
    whole = compact[: tail.start()] if tail else compact
    fraction = tail.group(1).rstrip("0") if tail else ""
    return re.sub(r"[.,]", "", whole) + (_DECIMAL_MARK + fraction if fraction else "")


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
    # Numbers are canonicalised BEFORE the blanket removal, or their separators go
    # the way of the punctuation and the magnitude goes with them.
    numbers_kept = _NUMERIC_RUN.sub(lambda m: _canonical_number(m.group(0)), without_marks)
    return _FOLD_AWAY.sub("", numbers_kept).casefold()


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


def _page_words(
    page: pymupdf.Page, budget: list[int] | None = None
) -> list[tuple[float, float, float, float, str]]:
    """This page's words with their rectangles — native if it has any, OCR if not.

    THE ONE PLACE THE THREE DOCUMENT KINDS DIFFER (LP-708). A typed page carries
    its own word list, exact and free. A scanned page carries nothing and is OCR'd.
    AN IMAGE DOCUMENT NEVER GETS HERE, though this said it "is a scan by another
    name and takes the same path". The boxes endpoint gates on
    `TEXT_SEARCHABLE_TYPES`, which is `{"application/pdf"}` — so a photographed
    pay stub, which LP-704 taught the reviewer to DISPLAY, returns an empty boxes
    response and never reaches this module. It is the case a reader of this comment
    would most reasonably assume is covered, and it is the one that is not
    (LP-708 review).

    Everything above this line — folding, matching, the boundary guard, the union
    rectangle — is identical for a typed and a scanned page and does not know which
    it is looking at.

    NATIVE TEXT IS AUTHORITATIVE and is never re-derived: positions encoded in a
    PDF are the source of record, while OCR estimates them. The check is per PAGE,
    because six of 101 stored documents are mixed.
    """
    return words_for(page, budget)


def _index_page(page: pymupdf.Page, budget: list[int] | None = None) -> _PageIndex:
    """Fold a page's word list into a searchable index. Empty for a page with no text."""
    text_parts: list[str] = []
    owner: list[int] = []
    starts: set[int] = set()
    ends: set[int] = set()
    rects: list[pymupdf.Rect] = []
    cursor = 0
    for word in _page_words(page, budget):
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
            run = (index.owner[at], index.owner[end - 1] + 1)
            if _visually_contiguous(index, run):
                found.append(run)
        at = index.text.find(needle, at + 1)
    return found


#: How far apart two words on one line may sit, as a multiple of their line
#: height, and still read as one run. A single space measures ~0.2 on this
#: corpus's fonts; a table's column gap ~2.4. Set between them, clear of both.
MAX_WORD_GAP_RATIO = 1.0

#: How far DOWN the next word may be and still be a wrapped continuation.
MAX_LINE_DROP_RATIO = 2.0


def _visually_contiguous(index: _PageIndex, run: tuple[int, int]) -> bool:
    """Whether the words in `run` sit together on the page, or only in the fold.

    THE CHECK THE FOLD DESTROYED. `index.text` is the page's words concatenated
    with NOTHING between them, so a needle can span two words the page kept far
    apart and still begin and end on word boundaries. A pay stub showing ``40`` and
    ``00`` in adjacent table CELLS matched a needle of ``4000`` — a figure not on
    the page at all, boxed across two unrelated cells and reported unambiguous
    because the spurious run was the only occurrence.

    The word-boundary rule is necessary and not sufficient: a real match is always
    a whole run of the page's words, and a whole run of the page's words is not
    always something the page says.

    A wrap HAS A SHAPE — next line, back towards the margin — so it is allowed and
    bounded, rather than waved through. An earlier version of this guard simply
    skipped every pair that did not share a line, which left a run crossing any
    line with no distance bound at all: two words at opposite corners joined into
    one box spanning most of the page.
    """
    first, last = run
    for left, right in zip(
        index.rects[first : last - 1], index.rects[first + 1 : last], strict=True
    ):
        height = max(float(left.y1 - left.y0), 1.0)
        if min(left.y1, right.y1) - max(left.y0, right.y0) > 0:
            # Same line: about a space apart, and in reading order — a negative gap
            # means the pair is not left-to-right and is not a run.
            if not 0 <= float(right.x0 - left.x1) <= height * MAX_WORD_GAP_RATIO:
                return False
            continue
        drop = float(right.y0 - left.y0)
        if not 0 < drop <= height * MAX_LINE_DROP_RATIO:
            return False
        if float(right.x0) > float(left.x1):
            return False
    return True


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


# --- The four tiers --------------------------------------------------------- #


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
    """Tiers 2 and 4 — a folded needle against the page's folded word stream."""
    runs = _runs(index, needle)
    if not runs or len(runs) > MAX_MATCHES:
        return ()
    return tuple(
        _normalise(_union(index.rects[start:end]), page.rect, page_number) for start, end in runs
    )


def _partial(
    index: _PageIndex, page: pymupdf.Page, request: BoxRequest, page_number: int
) -> tuple[FieldBox, ...]:
    """The longest run of the snippet's words the page HAS, around the value's own words.

    WHY THIS TIER EXISTS. The snippet is often a SYNTHESIS rather than a
    quotation — "Total Taxes $3,663.31 + Total Pre-Tax $1,410.00 + Total Post-Tax
    $335.00" is three figures from three places joined by the model's arithmetic,
    and it is nowhere on the page as one run. Of the 72 fields the earlier tiers
    cannot place on typed documents, every one has its snippet's words on the page
    somewhere and none has the whole snippet anywhere, so demanding one contiguous
    run of all of it is what loses them.

    IT MUST ADD SOMETHING TO THE BARE VALUE, and that rule is what this tier is,
    not a refinement of it. Without it the winning run is simply the value: MEASURED
    over the stored corpus, 45 of 45 fields this tier placed were placed on a run
    whose fold IS the value's, and for 44 of them no run carrying any context exists
    on the page at all. That is not "part of the quoted text"; it is the VALUE tier,
    promoted one tier earlier, with LP-709's document-wide ambiguity rule removed —
    and 30 of the 45 were figures the document repeats, which that rule exists to
    refuse. A run that adds nothing therefore falls through to the value tier, where
    it is counted across the document and labelled for what it is.

    THE ANCHOR IS CHECKED ON THE PAGE, AT WORD BOUNDARIES. Asking whether the
    model's own snippet text contains the value is an unaligned substring test, and
    this module exists partly because `1500` is a substring of `21,500.00` and
    `Smith` of `Blacksmith`: both pass that test and neither page text contains the
    value. `_runs` already resolves the value to whole-word runs, so requiring the
    boxed run to CONTAIN one is the same guarantee the rest of the module keeps,
    and it makes the claim above this line true rather than intended.

    Finding those runs FIRST also bounds the cost. The search below is quadratic in
    the snippet's words — a forty-word snippet is 820 candidates, each folded and
    searched, per page, per field, measured at 8 ms per page per field — and it ran
    in full on every page, including the great majority that do not hold the value
    at all. A page that cannot anchor anything now costs one search.

    Longest first, so the most context that can be confirmed is what gets boxed.
    """
    folded_value = fold(request.value)
    if len(folded_value) < MIN_FOLDED_LENGTH:
        return ()
    words = request.snippet.split()
    if not words:
        return ()
    value_runs = _runs(index, folded_value)
    if not value_runs:
        return ()
    for length in range(len(words), 0, -1):
        for start in range(len(words) - length + 1):
            needle = fold(" ".join(words[start : start + length]))
            # STRICTLY MORE THAN THE VALUE. Equal length plus containment means the
            # run IS the value, which the value tier below already answers — and
            # answers under a rule this tier does not have.
            if len(needle) <= len(folded_value) or folded_value not in needle:
                continue
            anchored = [
                run
                for run in _runs(index, needle)
                if any(run[0] <= v0 and v1 <= run[1] for v0, v1 in value_runs)
            ]
            if not anchored or len(anchored) > MAX_MATCHES:
                continue
            return tuple(
                _normalise(_union(index.rects[s:e]), page.rect, page_number) for s, e in anchored
            )
    return ()


_EMPTY = BoxLookup(boxes=(), cited_page_exists=True, found_elsewhere=False)


def _tier_on_page(
    doc: pymupdf.Document,
    page_index: int,
    request: BoxRequest,
    tier: MatchKind,
    indexes: dict[int, _PageIndex],
    budget: list[int] | None = None,
) -> tuple[FieldBox, ...]:
    """Locate one field on one page using ONE tier.

    Split per tier so the document walk can be tier-major — see `_lookup_in`.
    `indexes` caches the folded page index for the whole document: it was rebuilt
    per (field, page), so a twelve-page document with thirty fields that miss the
    exact tier extracted and folded the same twelve pages 360 times, in the
    request path. The single `open()` above is justified on exactly this argument.
    """
    page = doc[page_index]
    page_number = page_index + 1

    if tier is MatchKind.EXACT:
        return _exact(page, request.snippet, page_number)

    if page_index not in indexes:
        indexes[page_index] = _index_page(page, budget)
    index = indexes[page_index]

    if tier is MatchKind.NORMALISED:
        return _folded(index, page, fold(request.snippet), page_number)

    if tier is MatchKind.PARTIAL:
        return _partial(index, page, request, page_number)

    # TIER 4, HELD TO A STRICTER RULE (LP-709). The quoted text could not be
    # confirmed anywhere, so all we have is the answer. A figure appearing twice —
    # the same amount as a subtotal and a total — gives no way to tell which the
    # model read. The count is applied by the caller, across the whole document.
    folded_value = fold(request.value)
    if not folded_value or folded_value == fold(request.snippet):
        return ()
    return _folded(index, page, folded_value, page_number)


def _lookup_in(
    doc: pymupdf.Document,
    request: BoxRequest,
    indexes: dict[int, _PageIndex],
    budget: list[int] | None = None,
) -> BoxLookup:
    """Locate one field across the document, STRONGEST TIER FIRST.

    TIER-MAJOR, NOT PAGE-MAJOR, and the difference decides correctness. Trying all
    four tiers on the cited page and then all four on each other page lets a bare
    VALUE guess on page 1 beat a verbatim EXACT match on page 3 — which MOVES a box
    that was correct before this change, against the guarantee that running the
    exact tier first means none can. That guarantee only ever held within a page.

    Within a tier the cited page is tried first, so a citation that holds still
    beats an identical match elsewhere.
    """
    if not request.snippet.strip() and not request.value.strip():
        return _EMPTY
    try:
        cited = request.cited_page - 1
        cited_exists = 0 <= cited < doc.page_count
        order = ([cited] if cited_exists else []) + [n for n in range(doc.page_count) if n != cited]

        for tier in (
            MatchKind.EXACT,
            MatchKind.NORMALISED,
            MatchKind.PARTIAL,
            MatchKind.VALUE,
        ):
            if tier is MatchKind.VALUE:
                # THE AMBIGUITY RULE IS DOCUMENT-WIDE, because the search is. Held
                # per page it could not see the case it exists for: the same figure
                # once on page 1 and once on page 2 is exactly as unresolvable as
                # twice on one page, and page-local counting called it unambiguous.
                # It bites hardest on the ~4% of fields citing a page that does not
                # exist, which always fall through to the whole-document walk.
                hits = [
                    (n, boxes)
                    for n in order
                    if (boxes := _tier_on_page(doc, n, request, tier, indexes, budget))
                ]
                if sum(len(boxes) for _, boxes in hits) != 1:
                    continue
                page_index, boxes = hits[0]
                return BoxLookup(
                    boxes=boxes,
                    cited_page_exists=cited_exists,
                    found_elsewhere=page_index != cited,
                    match_kind=tier,
                )

            for n in order:
                found = _tier_on_page(doc, n, request, tier, indexes, budget)
                if found:
                    return BoxLookup(
                        boxes=found,
                        cited_page_exists=cited_exists,
                        found_elsewhere=n != cited,
                        match_kind=tier,
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
        # ONE INDEX PER PAGE for the whole document, not per (field, page).
        indexes: dict[int, _PageIndex] = {}
        # ONE BUDGET FOR THE WHOLE REQUEST, alongside the one index per page. OCR
        # runs in the request path and the client gives up at 30s.
        budget = [MAX_OCR_PAGES_PER_REQUEST]
        return {key: _lookup_in(doc, request, indexes, budget) for key, request in requests.items()}
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
