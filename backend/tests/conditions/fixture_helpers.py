"""Loading the synthetic condition sheets (LP-906, spec §7).

⚠️ THE FIXTURES ARE EXTRACTED FROM THE SPEC MECHANICALLY, NOT TRANSCRIBED. Each `.txt` in
`fixtures/` is a copy of the fenced block in `docs/phases/phase4.5-stage0-1-build-spec.md`, cut with
`sed` and verified with `diff`. That matters because the spec says "keep the spacing exactly as
below — the readers depend on columns": the UWM expiry table is matched by COLUMN POSITION, so a
single shifted space changes which date lands under which header, and the result would be a
plausible-looking wrong answer rather than an error.

THE ONE DIFFERENCE FROM THE SPEC, AND WHY IT IS NOT A HOOK EXCLUSION. The repo's
`trailing-whitespace` pre-commit hook stripped one line on its way in — the expiry header's padding
after `Rate Lock Exp` in round 1 — and it is left stripped. `normalise` rstrips every line, so no
reader can observe the difference, and only the COLUMN STARTS carry meaning here. Excluding these
files the way the `.eml` corpus is excluded would claim the bytes are significant when they are not;
there DKIM signs them, which is a real reason, and borrowing it would be an overclaim. Provenance is
still checkable, with trailing whitespace removed from both sides:

    diff <(sed -n '663,748p' SPEC | sed 's/[[:space:]]*$//') \
         <(sed 's/[[:space:]]*$//' uwm_round1_2026-08-28.txt)

This is the LP-910 lesson applied before the mistake instead of after. That ticket's review had to
diff 56 hand-copied rows against their source to find three slips; ~220 lines of column-aligned text
would have been far worse. Copying mechanically removes the failure mode rather than guarding it.

THE `{SHY}` PLACEHOLDER, AND WHY IT IS NOT A REAL SOFT HYPHEN IN THE FILE. UWM's PDFs render ordinary
hyphens as U+00AD, which is INVISIBLE in an editor and in a diff. A fixture containing real ones
could be corrupted by any tool that strips them and nobody would see the change. So the file carries
`{SHY}` and this loader substitutes — which also makes the count assertable, and it is:
6 in round 1, 3 in round 2, 6 in the page-break sheet.
"""

from __future__ import annotations

from pathlib import Path

from app.conditions.readers.lines import SOFT_HYPHEN, Line, lines_from_text

_FIXTURES = Path(__file__).with_name("fixtures")

#: The placeholder standing in for U+00AD in the committed text (spec §7).
SHY_PLACEHOLDER = "{SHY}"


def sheet_text(name: str) -> str:
    """One fixture's raw text, with `{SHY}` replaced by a real soft hyphen.

    Returned UNNORMALISED, deliberately. The soft hyphens are put back so the reader has to remove
    them itself — a fixture that arrived pre-normalised would let a broken normaliser pass every
    test, which is the shape of a guard that cannot fail.
    """
    path = _FIXTURES / name
    if not path.exists():
        available = ", ".join(sorted(p.name for p in _FIXTURES.glob("*.txt")))
        raise FileNotFoundError(f"no fixture {name!r} (have: {available})")
    return path.read_text(encoding="utf-8").replace(SHY_PLACEHOLDER, SOFT_HYPHEN)


def sheet_lines(name: str) -> tuple[Line, ...]:
    """One fixture as positioned lines — what a reader actually consumes."""
    return lines_from_text(sheet_text(name))


#: The span of `uwm_round2` a mouse drag over the portal's conditions list selects: one line BELOW
#: the `CONDITIONS` marker, stopping at `EXPIRATION DATES`.
_ROUND_2_CONDITIONS_BLOCK = slice(39, 55)


def portal_excerpt() -> str:
    """What a processor actually pastes: the headings and the rows, and nothing else (LP-907).

    ⚠️ NEITHER THE TITLE NOR THE `CONDITIONS` MARKER IS INCLUDED, which is the whole difficulty.
    `detect_format` keys on the first content line and `read_uwm` bounds its block with the marker,
    so a portal copy defeats both — it is recognised by its row shapes instead.

    Sliced out of the fixture rather than retyped, so it cannot drift from the sheet every other
    test reads, and the line range lives here rather than in each test that wants it.
    """
    return "\n".join(sheet_text(UWM_ROUND_2).splitlines()[_ROUND_2_CONDITIONS_BLOCK])


UWM_ROUND_1 = "uwm_round1_2026-08-28.txt"
UWM_ROUND_2 = "uwm_round2_2026-09-10.txt"
UWM_PAGEBREAK = "uwm_master_pagebreak.txt"
