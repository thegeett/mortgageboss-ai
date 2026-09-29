"""The product owner's library review table, rendered from `types.yaml` (LP-938).

`docs/phases/phase4.5-library-review.md` says it is generated from the library, and until LP-938 it was
not: it was written once by hand in LP-918, and it went stale when the Stage 3A acceptance gave DI-01's
disclosure two performers. It still said "LO". Now the file is this module's output, and
`tests/conditions/test_library_review_table.py` fails when the two differ.

Regenerate after editing the library:

    uv run python -m app.conditions.library.review_table

THE TOP 20 ARE A CHOICE, NOT A COMPUTATION. LP-918 picked and ordered the types most often seen on the
sheets it had. That choice is kept here as `TOP_20`; everything in each row comes from the library and
the lender code maps.
"""

from __future__ import annotations

from pathlib import Path

from app.conditions.lender_codes.loader import load_seed
from app.conditions.library.loader import ConditionType, Library, LibraryItem, load_library
from app.models.condition_vocabulary import Performer, PlanOption

#: LP-918's selection and order.
TOP_20: tuple[str, ...] = (
    "AS-01",
    "AS-04",
    "AS-10",
    "AS-05",
    "AS-06",
    "AS-11",
    "CR-02",
    "CR-05",
    "IE-01",
    "IE-03",
    "IE-05",
    "IN-01",
    "IN-02",
    "PA-03",
    "PA-08",
    "ID-05",
    "TI-01",
    "TI-03",
    "DI-01",
    "IV-01",
)

#: The lenders whose code maps give the "Seen as" column, and how the table names them.
LENDERS: tuple[tuple[str, str], ...] = (("uwm", "UWM"), ("champions", "Champions"))

PERFORMER_LABEL: dict[Performer, str] = {
    Performer.BORROWER: "Borrower",
    Performer.LO: "LO",
    Performer.PROCESSOR: "You",
    Performer.LENDER: "Lender",
    Performer.TITLE: "Title / escrow",
    Performer.ATTORNEY: "Attorney",
    Performer.INSURANCE: "Insurance agent",
    Performer.HOA: "HOA",
    Performer.EMPLOYER: "Employer",
    Performer.APPRAISER: "Appraiser",
    Performer.OTHER_PARTY: "Another party",
}

OPTION_LABEL: dict[PlanOption, str] = {
    PlanOption.ASK_BORROWER: "Ask the borrower",
    PlanOption.ASK_THIRD_PARTY: "Ask a third party",
    PlanOption.I_WILL_DO_IT: "I'll do it",
    PlanOption.ALREADY_IN_FILE: "Already in the file",
    PlanOption.ASK_UNDERWRITER: "Ask the underwriter",
    PlanOption.PUSH_BACK: "Push back",
    PlanOption.LENDER_DOING_IT: "Lender is doing it",
    PlanOption.INFORMATION_ONLY: "Information only",
}

REVIEW_TABLE = (
    Path(__file__).resolve().parents[4] / "docs" / "phases" / "phase4.5-library-review.md"
)

_HEADER = """# Condition library v1: the top 20 types, for the product owner's review (LP-918)

**What this is.** The Stage 3 plan's library ticket (LP-918) asks the product owner to review and sign off
the 20 condition types that come up most. This table is **generated from the library itself**
(`backend/app/conditions/library/types.yaml`, by `app/conditions/library/review_table.py`), so what you
mark up is exactly what the app uses; a test fails if the two ever differ (LP-938). Mark each row in the
last column: **OK**, or what to change.

**Status: waiting for the product owner's sign-off** (tracked as an open item in
`docs/phases/phase4.5-progress.md`; later Stage 3 tickets use the library as it stands).

**How to read a row.** *Items* are the separate things a condition of this type usually asks for, each
with **who** provides it and the **option** the app proposes (you can change it on every file).
*Documents* are the app's document types that satisfy it. *Checks* are what code verifies when evidence
arrives (never the AI). *Rule* is the agency section behind it; "Lender requirement" means the lender's
own condition, with no agency section claimed. Only sections the Stage 3 plan cites are used.

| # | Type | Seen as | Items → who (option) | Documents | Checks | Rule | Your mark |
|---|---|---|---|---|---|---|---|
"""


def _seen_as() -> dict[str, list[str]]:
    """`{type id: ["UWM 6637", "Champions 71"]}`, UWM first, codes in number order."""
    out: dict[str, list[str]] = {}
    for key, name in LENDERS:
        for row in sorted(load_seed(key), key=lambda r: (len(r.code), r.code)):
            if row.canonical_type_id:
                out.setdefault(row.canonical_type_id, []).append(f"{name} {row.code}")
    return out


def _item(item: LibraryItem) -> str:
    who = " + ".join(PERFORMER_LABEL[p] for p in item.all_performers)
    return f"{item.name} → {who} ({OPTION_LABEL[item.option]})"


def _row(number: int, kind: ConditionType, seen: list[str]) -> str:
    documents = sorted({d for item in kind.items for d in item.documents})
    checks = sorted({str(c) for item in kind.items for c in item.checks})
    cells = [
        str(number),
        f"**{kind.label}**<br>{kind.playbook}",
        ", ".join(seen) if seen else "not on a mapped sheet yet",
        "<br>".join(_item(item) for item in kind.items),
        "<br>".join(documents) if documents else "—",
        "<br>".join(checks) if checks else "—",
        kind.rule.label,
    ]
    return "| " + " | ".join(cells) + " | |"  # the last column is hers to fill


def render(library: Library | None = None) -> str:
    """The whole file, as it must be committed."""
    library = library or load_library()
    seen = _seen_as()
    rows = [_row(n, library.types[t], seen.get(t, [])) for n, t in enumerate(TOP_20, start=1)]
    others = len(library.types) - len(TOP_20)
    footer = (
        f"\nThe other {others} types are in `types.yaml`; every UWM and Champions code on the Stage 1 "
        f"code maps\nresolves to one of the {len(library.types)}.\n"
    )
    return _HEADER + "\n".join(rows) + "\n" + footer


if __name__ == "__main__":
    REVIEW_TABLE.write_text(render(), encoding="utf-8")
    print(f"wrote {REVIEW_TABLE}")
