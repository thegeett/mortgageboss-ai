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
    """⚠️ THE HALF THAT IS EASY TO LOSE. Excluding a column always passes the exclusion test.

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
