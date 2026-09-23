"""Positioned lines — the one input every reader consumes (LP-906).

A reader never sees a PDF or a paste. It sees :class:`Line` objects carrying a page, a vertical
position and the tokens with their horizontal starts, and that is deliberate: the Champions centre
rule and the UWM expiry table are both POSITIONAL, and a reader written against raw text cannot ask
where a column begins. Building the same structure from a PDF and from plain text is what lets one
reader serve an uploaded letter and a pasted one.

THE TWO COORDINATE SYSTEMS ARE DIFFERENT UNITS AND THAT IS FINE. From a PDF, `y` is points from the
top and `x0` is points from the left. From text, `y` is the line index and `x0` the character offset.
Nothing compares the two, and every rule that uses them is relative — "nearest column", "the line
above", "2 * number.y - bottom" — so both work unchanged. It is why the spec's Champions layout
sample parses as text at all.

NORMALISATION HAPPENS ONCE, HERE, AND IS DELIBERATELY TINY. Soft hyphen → `-`, non-breaking space →
space, trailing whitespace stripped. Nothing else. Spec §9.1 is the rule the whole ticket turns on:
the lender's words are stored verbatim, so a normaliser that "tidied" anything would put a
paraphrase into `verbatim_text` and there would be no way back to what was printed.

⚠️ WHY THE SOFT HYPHEN MATTERS MORE THAN IT LOOKS. UWM's PDFs render ordinary hyphens as U+00AD:
`non{SHY}ownership`, `K{SHY}1`, `(555) 010{SHY}0175`, and the bucket heading
`UW {SHY} Prior To Final Approval (PTD)`. Left alone, the heading regex fails to match, the condition
text carries an invisible character, and two texts that a person would call identical produce
different fingerprints — so the same condition would look new on every round.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

from app.services.page_ocr import words_for

# ⚠️ BOTH CONSTANTS ARE `chr()` CALLS, NOT LITERALS, AND NOT `"\\u00ad"` ESCAPES EITHER. Written as
# a literal, each is INVISIBLE in an editor, in a review and in a diff - a soft hyphen renders as
# nothing and a non-breaking space as an ordinary space. Written as a `\\u` escape they are legible,
# but an escape can be normalised back into the character by a tool that rewrites the file, which is
# exactly what happened here: `od -c` showed `302 240` sitting in the source where `\\u00a0` had been
# typed, and ruff's RUF001 caught it.
#
# `chr(0x00AD)` survives any such rewrite, names its codepoint without needing a comment to do it,
# and cannot be mistaken for whitespace by a reader or a linter.

#: U+00AD. Rendered by UWM's PDF pipeline where a real hyphen was typed.
SOFT_HYPHEN = chr(0x00AD)
#: U+00A0. Arrives from HTML-to-PDF conversion in place of a plain space.
NON_BREAKING_SPACE = chr(0x00A0)

_TOKEN = re.compile(r"\S+")

#: Two words whose vertical centres differ by less than this are on the same line. In points, and
#: generous: a 9pt line is ~11pt tall, and the risk of merging two real lines is far smaller than the
#: risk of splitting one — a split line breaks a row's text in half, which no later rule recovers.
_SAME_LINE_TOLERANCE_POINTS = 3.0


def normalise(text: str) -> str:
    """The only transformation applied to a lender's words (spec §9.1).

    Three substitutions and nothing else. `rstrip` only — leading spaces are LOAD-BEARING, because
    indentation is what distinguishes a bucket heading (≤ 3 spaces) from a continuation line (≥ 20),
    and a reader that stripped them would lose the column structure it exists to read.
    """
    return text.replace(SOFT_HYPHEN, "-").replace(NON_BREAKING_SPACE, " ").rstrip()


@dataclass(frozen=True)
class Token:
    """One word and where it starts. `x0` is PDF points, or a character offset for text input."""

    text: str
    x0: float


@dataclass(frozen=True)
class Line:
    """One line of a sheet, with its position and its tokens.

    `text` keeps the ORIGINAL SPACING for text input — the readers measure indentation off it — and
    is the tokens joined for PDF input, where spacing is a property of the boxes rather than of the
    string.
    """

    page: int
    y: float
    text: str
    tokens: tuple[Token, ...]

    @property
    def is_blank(self) -> bool:
        return not self.text.strip()

    @property
    def indent(self) -> int:
        """Leading spaces. The UWM reader's heading-vs-continuation test."""
        return len(self.text) - len(self.text.lstrip(" "))


def lines_from_text(raw: str) -> tuple[Line, ...]:
    """Build lines from plain text — a paste, or a fixture.

    `y` is the line index and `x0` the character offset, so every positional rule in the readers
    works on text exactly as it does on a PDF. Blank lines are KEPT rather than filtered: the
    Champions segmenter reasons about the line above a row's top, and a reader that never saw the
    blanks would compute a different one.
    """
    return tuple(
        Line(
            page=1,
            y=float(index),
            text=(line := normalise(raw_line)),
            tokens=tuple(Token(m.group(), float(m.start())) for m in _TOKEN.finditer(line)),
        )
        for index, raw_line in enumerate(raw.splitlines())
    )


def lines_from_pdf(content: bytes) -> tuple[Line, ...]:
    """Build lines from a PDF's word boxes, one page at a time.

    ⚠️ THROUGH `page_ocr.words_for`, NOT `page.get_text("words")` DIRECTLY. That function already
    answers "where are this page's words" for both a text layer and a scan, returning the same
    `(x0, y0, x1, y1, word)` shape either way and deciding per PAGE rather than per document — six of
    the corpus's documents are mixed. Calling the raw API here would be a second answer to one
    question, and it would silently return nothing for a scanned sheet.

    Words are grouped into lines by their vertical centre rather than by pymupdf's own block/line
    indices: a two-column header puts the left and right labels in different blocks at the SAME
    height, and UWM's header is exactly that — `Contact Name:` on the left, `Senior UW:` on the
    right, one visual line.
    """
    out: list[Line] = []
    # `type: ignore[no-untyped-call]` follows `pdf_utils.py` and `page_render.py`, which carry the
    # same comment on the same call: pymupdf ships `py.typed` but no stubs, so mypy strict sees its
    # constructor as untyped. Copied rather than invented, so there is one spelling of this.
    with pymupdf.open(stream=content, filetype="pdf") as document:  # type: ignore[no-untyped-call]
        for page_number, page in enumerate(document, start=1):
            rows: dict[float, list[tuple[float, float, str]]] = {}
            for x0, y0, _x1, y1, word in words_for(page):
                centre = (y0 + y1) / 2.0
                key = next(
                    (k for k in rows if abs(k - centre) < _SAME_LINE_TOLERANCE_POINTS),
                    centre,
                )
                rows.setdefault(key, []).append((x0, centre, normalise(word)))

            for centre in sorted(rows):
                words = sorted(rows[centre], key=lambda w: w[0])
                tokens = tuple(Token(text, x0) for x0, _, text in words if text)
                if not tokens:
                    continue
                out.append(
                    Line(
                        page=page_number,
                        y=centre,
                        text=" ".join(token.text for token in tokens),
                        tokens=tokens,
                    )
                )
    return tuple(out)
