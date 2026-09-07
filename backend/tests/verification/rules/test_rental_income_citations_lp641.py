"""LP-641 — the rental-income citations, after SEL-2026-08 split the topic they pointed at.

THIS MATERIAL HAS MOVED THREE TIMES IN A YEAR:

    B3-3.1-08  ->  B3-3.8-01  ->  B3-3.8-01 (general) + B3-3.8-02 (subject property)

which is the argument for a guard rather than a fourth manual sweep. The split is what makes it
worth pinning: a rule citing one topic for BOTH the 75% factor and the lease-in-effect evidence is
now half wrong, and a find-and-replace produces exactly that.

WHAT A TEST CAN AND CANNOT DO HERE. It cannot verify a citation is CORRECT — that needs the guide,
and the guide is not in the repo. It can verify no live citation names a topic we have established
is superseded, which is the failure that actually happened. That is a real but narrow guarantee, and
it is stated here so nobody reads a green run as "the citations are right".
"""

from __future__ import annotations

import re
from pathlib import Path

_APP = Path(__file__).resolve().parents[3] / "app"

#: Where each fact lives after SEL-2026-08 (both pages dated 09/02/2026), verified against the live
#: guide on 2026-09-05:
#:
#:   B3-3.8-01  General Rental Income Information      — the 12-month experience requirement,
#:                                                       the lease-in-effect evidence
#:   B3-3.8-02  Rental Income from the Subject Property — the 75% / ANRI factor,
#:                                                       the mandatory Form 1007 / 1025
#:   B3-3.8-03  ...: Short-Term Rental                  — a separate treatment (LP-642, unscoped)
_SUPERSEDED = "B3-3.1-08"

#: NO FILE-LEVEL EXEMPTION, and there was one until this was measured (LP-641 review).
#:
#: Two files were exempted by name — `registry.py` and `dti.py` — on the grounds that each carries a
#: deliberate historical mention. Measuring them says otherwise: `_live_citations` already returns
#: ZERO for both, because the skip pattern below matches the words those narrative lines are written
#: in. The exemption was doing nothing except reserving a hole in the two files most likely to
#: discuss citations, where a genuinely stale one could then be added and pass.
#:
#: A first attempt replaced the names with an allowance of 1 each. That was worse: an allowance of 1
#: against a real count of 0 hands out exactly the free slot it was meant to close, and a mutation —
#: adding a live B3-3.1-08 citation to `dti.py` — passed clean. Counting is only safe when the count
#: is MEASURED, and once measured the honest count is zero, which is no exemption at all.


def _live_citations(text: str) -> list[str]:
    """Lines naming the superseded topic, minus lines that are plainly about the move itself."""
    out = []
    for line in text.splitlines():
        if _SUPERSEDED not in line:
            continue
        # A line explaining the supersession names it in order to say it is stale. The words are the
        # signal; there is no structured way to tell narrative from citation in a comment.
        if re.search(r"stale|supersed|was cited|went stale|moved|LP-641|renumber", line, re.I):
            continue
        out.append(line.strip())
    return out


def test_no_live_citation_names_the_superseded_topic() -> None:
    """The failure this actually caught: `dti.py` and `rental_treatment.py` still cited B3-3.1-08,
    which SEL-2026-08 had superseded TWICE over — once into B3-3.8-01, then into the split."""
    offenders: dict[str, list[str]] = {}
    for path in sorted(_APP.rglob("*.py")) + sorted(_APP.rglob("*.yaml")):
        rel = str(path.relative_to(_APP))
        if lines := _live_citations(path.read_text(encoding="utf-8")):
            offenders[rel] = lines

    assert not offenders, (
        f"{_SUPERSEDED} is superseded — the 75% factor and the Form 1007/1025 requirement are at "
        "B3-3.8-02, the lease-in-effect evidence and the experience requirement at B3-3.8-01:\n  "
        + "\n  ".join(f"{f}: {ls}" for f, ls in offenders.items())
    )


def test_the_seventy_five_percent_factor_cites_the_topic_that_holds_it() -> None:
    """THE SPLIT IS THE POINT. B3-3.8-01 still exists and is still the right cite for general rental
    income — so "does any file mention B3-3.8-01" is the wrong question. The question is whether the
    file that owns the FACTOR cites the topic the factor moved to."""
    source = (_APP / "services/rental_treatment.py").read_text(encoding="utf-8")
    factor = source[source.index("QUALIFYING_FACTOR") - 2200 : source.index("QUALIFYING_FACTOR")]

    assert "B3-3.8-02" in factor, "the factor's citation must name the topic that carries it"
    assert "75%" in factor and "gross rent" in factor


def test_the_factor_records_that_it_does_not_apply_to_schedule_e() -> None:
    """The restriction that outlives this sweep. 75% applies to a gross rent documented by a lease
    (and to the gross a Form 1007 / 1025 supports); the Schedule E path is a cash-flow analysis —
    depreciation, interest, HOA dues, taxes and insurance added back. Nothing can reach the constant
    with a Schedule E figure TODAY, because `_subject_gross_rent` reads only the MISMO schedule. LP-642
    proposes widening exactly that lookup, and 75% on a Schedule E figure would be wrong arithmetic.

    Pinned so the restriction is written down BEFORE the lookup widens, not discovered after.
    """
    source = (_APP / "services/rental_treatment.py").read_text(encoding="utf-8")
    assert "Schedule E" in source, "the path restriction must survive an edit to this module"


def test_the_withdrawn_rationale_is_not_quoted_as_verbatim() -> None:
    """WHAT THE RE-VERIFICATION COST. The 10/08/2025 page explained the factor — the remaining 25%
    "absorbed by vacancy losses and ongoing maintenance expenses" — and that sentence is in NEITHER
    restructured topic (both checked, separately). The value 25 stands as arithmetic; quoting the
    explanation as guide text would assert something no longer in the guide.

    This is the half of a citation sweep that a renumber misses: a claim can stop being true without
    its topic number changing at all.
    """
    for rel in ("verification/rules/specs/IN-14.yaml", "verification/rules/activation_bars.yaml"):
        lines = (_APP / rel).read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "absorbed by vacancy" not in line.lower():
                continue
            # A WINDOW, not the line. These files wrap prose at ~100 columns, so the quotation and the
            # sentence withdrawing it land on different lines — a line-anchored check reads the quote
            # alone and fails on correct content. The disclaimer has to be NEAR the quote to be read
            # with it, which is what the window encodes; four lines is the wrap distance here.
            window = " ".join(lines[max(0, i - 4) : i + 5])
            assert re.search(r"neither|withdrawn|no longer|not.*claimed", window, re.I), (
                f"{rel} quotes the vacancy/maintenance rationale with nothing nearby marking it "
                f"withdrawn: {line.strip()}"
            )
