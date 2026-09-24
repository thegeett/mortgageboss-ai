"""A lender code's status is raised, never lowered (LP-909 §2, review).

⚠️ THIS RULE HAD NO TEST, AND A FILE LOOKED AS THOUGH IT COVERED IT. Nothing under `tests/`
referenced `seed_lender_codes` at all, and `test_lender_code_loader.py` — which sounds like the code
map's test — covers the YAML parser only: ten tests, no database, no status, no upsert. A writer that
demoted `MAPPED` back to `SEEDED` would have passed the entire suite.

The rule mattered less while the seed script was the only writer of these rows. LP-909's import is
the second, and an invariant is only as good as its enumeration of who writes it — which is the
enrich finding one layer up, where `round_numbers` was derived correctly and simply did not know
about a second writer.
"""

from __future__ import annotations

import pytest
from app.conditions.lender_codes.status import may_replace, resolved_status
from app.models.lender_condition_code import LenderCodeStatus


def test_an_unmapped_code_takes_whatever_explains_it() -> None:
    """`OBSERVED_UNMAPPED` means "arrived on a sheet, nobody has looked yet", so anything that gives
    the code a meaning is an improvement — that is the case the rule exists to allow."""
    assert (
        resolved_status(LenderCodeStatus.OBSERVED_UNMAPPED, LenderCodeStatus.SEEDED)
        is LenderCodeStatus.SEEDED
    )
    assert (
        resolved_status(LenderCodeStatus.OBSERVED_UNMAPPED, LenderCodeStatus.MAPPED)
        is LenderCodeStatus.MAPPED
    )


def test_a_human_decision_outranks_shipped_data() -> None:
    """⚠️ THE CASE THE RULE EXISTS FOR. `MAPPED` is a person who reviewed the code and gave it a
    meaning. A seed re-run, or a sheet arriving with that code on it, must not overrule them."""
    assert (
        resolved_status(LenderCodeStatus.MAPPED, LenderCodeStatus.SEEDED) is LenderCodeStatus.MAPPED
    )
    assert (
        resolved_status(LenderCodeStatus.MAPPED, LenderCodeStatus.OBSERVED_UNMAPPED)
        is LenderCodeStatus.MAPPED
    )


def test_seeded_is_not_demoted_by_a_sheet_mentioning_the_code() -> None:
    """The import proposes `OBSERVED_UNMAPPED` for every code it sees. On a code the shipped map
    already explains, that proposal must change nothing — "bump the counters, never reset the
    meaning"."""
    assert (
        resolved_status(LenderCodeStatus.SEEDED, LenderCodeStatus.OBSERVED_UNMAPPED)
        is LenderCodeStatus.SEEDED
    )


def test_the_rule_is_not_an_ordering_and_that_is_the_trap() -> None:
    """⚠️ `LenderCodeStatus` DECLARES `SEEDED, OBSERVED_UNMAPPED, MAPPED` IN THAT ORDER.

    So a `>`-style implementation — the obvious way to write "raised, never lowered" — would treat
    SEEDED as the lowest rank and happily demote it to OBSERVED_UNMAPPED, while reading as correct
    to anyone skimming it. This pins the specific rule rather than an ordinal one: the declaration
    order says nothing about precedence.
    """
    order = list(LenderCodeStatus)
    assert order.index(LenderCodeStatus.SEEDED) < order.index(LenderCodeStatus.OBSERVED_UNMAPPED)

    # Declared first, and still not demotable by the status declared after it.
    assert (
        resolved_status(LenderCodeStatus.SEEDED, LenderCodeStatus.OBSERVED_UNMAPPED)
        is LenderCodeStatus.SEEDED
    )


@pytest.mark.parametrize("status", list(LenderCodeStatus))
def test_proposing_the_status_a_row_already_has_is_always_a_no_op(
    status: LenderCodeStatus,
) -> None:
    """Every status, so a member added later is covered without anyone remembering to add a case."""
    assert resolved_status(status, status) is status


@pytest.mark.parametrize("status", list(LenderCodeStatus))
def test_only_the_unmapped_status_is_replaceable(status: LenderCodeStatus) -> None:
    """`may_replace` and `resolved_status` must agree, or a caller logging the difference would
    report something other than what was applied."""
    replaceable = may_replace(status)

    assert replaceable is (status is LenderCodeStatus.OBSERVED_UNMAPPED)
    for proposed in LenderCodeStatus:
        result = resolved_status(status, proposed)
        assert result is (proposed if replaceable else status)
