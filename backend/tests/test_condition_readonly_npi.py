"""The condition views expose no NPI (LP-904 done-when, ADR-405).

`tests/test_readonly_query.py` already enforces the general rule — every model column is exposed or
listed in `EXCLUDED`, and `NEVER_EXPOSED` asserts the highest-consequence columns against every view.
This file is the Phase 4.5 contract stated in its own terms, for two reasons:

1. **It names the columns by their meaning, not their table.** "The lender's words never reach the
   analytics path" is the decision ADR-405 records; `EXCLUDED` records it as a frozenset, which is
   correct and says nothing about why. A reader who breaks this test is told which decision they are
   breaking.
2. **It asserts the POSITIVE half too.** Excluding a column is easy; the harder question is whether
   what remains still answers anything. These views exist to keep "which reader ran, how much did it
   find, how much did it leave over, did this condition come back" answerable from staging — and a
   later rebuild that quietly dropped those derived scalars would pass every existing guard while
   making the views useless.

The view text is read the same way `test_readonly_query.py` reads it: from the migrations, as text,
upgrade-side only. There is no database here.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

_READONLY_TESTS = Path(__file__).resolve().parent / "test_readonly_query.py"


def _readonly_module() -> Any:
    """Load the readonly guard's helpers rather than re-implementing them.

    A second copy of `_view_bodies` / `_output_columns` would be a second answer to "what does this
    view return", and the two would drift — which is the failure mode that file's own docstrings are
    full of. This borrows the one implementation.
    """
    spec = importlib.util.spec_from_file_location("_readonly_guard", _READONLY_TESTS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The lender's words and everything derived from them, by table. These are the ADR-405 columns.
NPI_COLUMNS: dict[str, set[str]] = {
    "condition_rounds": {"raw_text", "header", "draft_rows", "parse_report"},
    "conditions": {"verbatim_text", "underwriter_notes"},
    "condition_events": {"detail"},
}

#: What must SURVIVE in each view, so the analytics path still answers something.
REQUIRED_OUTPUTS: dict[str, set[str]] = {
    "condition_rounds": {
        "reader",
        "reader_version",
        "ai_used",
        "duplicates_dropped",
        "warning_count",
        "unassigned_count",
        "sources",
        "expiry_dates",
    },
    # `text_fingerprint` is the load-bearing one: a sha256 is how "did this condition come back?"
    # stays answerable without reproducing a word of it.
    "conditions": {"text_fingerprint", "bucket_kind", "lender_code", "underwriter_note_count"},
    "condition_events": {"kind", "occurred_at", "round_id", "condition_id"},
}


@pytest.mark.parametrize("table", sorted(NPI_COLUMNS))
def test_the_condition_views_expose_no_npi_column(table: str) -> None:
    """Not one of the lender's words reaches `readonly.*`.

    Dropped rather than scrubbed, deliberately: `readonly.scrub()` matches identifier SHAPES, and a
    condition quoting an employer, a street or a person is not digit-shaped — it would cross a
    scrubbed view intact. That is the whole argument in ADR-405, and this is where it is enforced.
    """
    module = _readonly_module()
    bodies = module._view_bodies()
    assert table in bodies, f"no readonly view found for {table} — the migration did not create one"

    exposed = module._output_columns(bodies[table])
    leaked = sorted(NPI_COLUMNS[table] & exposed)

    assert not leaked, (
        f"readonly.{table} exposes NPI: {leaked}. ADR-405 requires these dropped, not scrubbed — a "
        "scrub matches identifier shapes and the lender's prose is not digit-shaped."
    )


@pytest.mark.parametrize("table", sorted(REQUIRED_OUTPUTS))
def test_the_condition_views_still_answer_something(table: str) -> None:
    """THE HALF THAT IS EASY TO LOSE. Excluding a column always passes the exclusion test.

    A view rebuilt later could drop every derived scalar, keep the NPI out, and satisfy every guard
    in `test_readonly_query.py` while making the view answer nothing at all. These are the outputs
    the exclusions were justified by, so they are asserted rather than assumed.
    """
    module = _readonly_module()
    exposed = module._output_columns(module._view_bodies()[table])
    missing = sorted(REQUIRED_OUTPUTS[table] - exposed)

    assert not missing, (
        f"readonly.{table} no longer exposes {missing}. The NPI columns were excluded on the "
        "argument that these derived answers replace them; without them the view keeps the "
        "privacy property and loses the point."
    )


#: What may follow a mention of the `verdict` column: one of its two provenance keys, and nothing else.
_PERMITTED_VERDICT_USE = re.compile(r"\s*->>\s*'(source_kind|source_date)'")


def _verdict_references(body: str) -> tuple[int, list[str]]:
    """``(how many times the view names `verdict`, the mentions that reach for anything else)``.

    EVERY MENTION, CASE-INSENSITIVELY, EACH CHECKED WHERE IT STANDS (LP-912 review). The first version
    split the select list at commas and checked only how each piece BEGAN, case-sensitively, so
    `verdict ->> 'source_kind' || (verdict ->> 'note')` passed on its first mention and
    `VERDICT ->> 'note'` was never found at all. SQL identifiers are case-insensitive, and one
    expression can name a column twice.

    `\bverdict\b` does not match the ALIASES `verdict_source_kind` / `verdict_source_date`, because
    `_` is a word character — so only real column references are counted.
    """
    select_list = body.split("FROM")[0]
    mentions = list(re.finditer(r"\bverdict\b", select_list, flags=re.IGNORECASE))
    offenders = [
        select_list[m.start() : m.end() + 30].strip()
        for m in mentions
        if not _PERMITTED_VERDICT_USE.match(select_list, m.end())
    ]
    return len(mentions), offenders


@pytest.mark.parametrize(
    ("select_list", "allowed"),
    [
        (
            "(verdict ->> 'source_kind') AS verdict_source_kind, (verdict->>'source_date') AS d",
            True,
        ),
        ("(verdict ->> 'source_kind' || (verdict ->> 'note')) AS x", False),
        ("(VERDICT ->> 'note') AS x", False),
        ("verdict AS whole_thing", False),
        ("(verdict -> 'note') AS x", False),
        ("(c.verdict ->> 'note') AS x", False),
    ],
)
def test_the_verdict_reference_check_reads_every_mention(select_list: str, allowed: bool) -> None:
    """The guard above, shown to catch the shapes its first version let through."""
    mentions, offenders = _verdict_references(f"SELECT {select_list} FROM public.conditions")
    assert mentions
    assert (not offenders) is allowed, offenders


def test_the_conditions_view_touches_verdict_only_for_its_provenance() -> None:
    """`verdict ->> 'note'` IS NPI AND NO OTHER GUARD IN THIS SUITE WOULD STOP IT (LP-912).

    THE HOLE THIS CLOSES, precisely. `verdict` is a JSONB column with a `note` key the processor
    typed — the same class as `prep_note` — and three keys an analyst legitimately asks about:
    `source_kind`, `source_date` and the status. The view therefore MUST name the column in order to
    project the provenance that makes "cleared on the 12th" checkable at all. That rules out the
    strong guard: `NEVER_EXPOSED` is a `\\bverdict\\b` search of the select list, so listing it there
    would fail against the very projection ADR-408 requires. `prep_note` can have that protection and
    does; `verdict` cannot.

    So what is asserted instead is the SHAPE of every reference: each mention of `verdict` in the
    view is followed by `->> 'source_kind'` or `->> 'source_date'` and nothing else. A later migration
    adding `verdict ->> 'note'` — or exposing the column whole — passes `EXCLUDED`,
    `test_no_model_column_drifts` and `NEVER_EXPOSED` alike, and fails here.

    READ FROM THE VIEW'S TEXT, NOT FROM `_output_columns`. The output names are
    `verdict_source_kind` / `verdict_source_date`, which say nothing about which keys produced them —
    the whole question is what the expression reaches into.
    """
    module = _readonly_module()
    body = module._view_bodies()["conditions"]

    references, offenders = _verdict_references(body)
    assert references, (
        "readonly.conditions does not mention `verdict` at all. Either the provenance projection was "
        "dropped — and `verdict_source_kind` / `verdict_source_date` are what make a recorded verdict "
        "auditable from staging — or this guard is reading the wrong view and is checking nothing."
    )

    assert not offenders, (
        "readonly.conditions reaches into `verdict` for something other than its provenance: "
        f"{offenders}. Only `source_kind` and `source_date` may be exposed — `note` is what a "
        "processor typed about one borrower's file (ADR-405, spec §6 rule 7), and the column cannot be "
        "protected by NEVER_EXPOSED because the view has to name it to project the two that are "
        "allowed."
    )


def test_the_fingerprint_is_exposed_and_the_text_is_not() -> None:
    """The pair that makes ADR-405 work, asserted together.

    Stated as one test because the two facts are only meaningful side by side: the text is absent
    AND the sha256 of it is present, which is what lets a staging query count recurrences without
    reading a condition. Splitting them would let a change that dropped both still pass one half.
    """
    module = _readonly_module()
    exposed = module._output_columns(module._view_bodies()["conditions"])

    assert "text_fingerprint" in exposed
    assert "verbatim_text" not in exposed
