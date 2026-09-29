"""Condition-type ids and verification-rule ids look alike, and five already coincide (LP-918 review).

`types.yaml`'s header says the two vocabularies "never meet", and that is true of what reads them:
a condition type id lives in `lender_condition_codes.canonical_type_id` and
`conditions.canonical_type_id`, a rule id lives in the verification engine, and nothing joins the two.
But the ids are the same SHAPE, and five strings are already in both vocabularies meaning entirely
different things — `AS-10` is "Statement recency completeness" to the engine and "Short funds to close
or reserves" to the library. Zero padding hides the rest: the library writes `AS-01` where the engine
writes `AS-1`, so only ids from 10 up can collide, and both vocabularies are still growing.

WHAT THIS PINS, AND WHAT IT DOES NOT. It does not forbid a collision — it makes one deliberate. The
five below are recorded as known; a sixth fails this test, so whoever adds it either renames the type
or adds it here having decided the overlap is harmless. Without that, the next one arrives silently
and the first person to notice is someone reading `AS-14` in a ticket and opening the wrong document.
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.conditions.library.loader import load_library

_RULE_KINDS = (
    Path(__file__).resolve().parents[2] / "app" / "verification" / "rules" / "rule_kinds.csv"
)

#: Ids that are BOTH a condition type and a verification rule today, with the two meanings.
#: Each was assigned by spec §6 LP-910 or in its shape (LP-918 decision 1), not chosen here.
_KNOWN_SHARED: frozenset[str] = frozenset(
    {
        "AS-10",  # rule: statement recency completeness / type: short funds to close or reserves
        "AS-11",  # rule: retirement or stock liquidation terms / type: departing residence being sold
        "CR-11",  # rule: judgments and liens resolution / type: contingent liability paid by others
        "CR-12",  # rule: disputed accounts / type: residence history or mortgage verification
        "CR-13",  # rule: credit report validity at closing / type: mortgage statement, other property
    }
)


def _rule_ids() -> set[str]:
    with _RULE_KINDS.open(encoding="utf-8", newline="") as handle:
        return {row["rule_id"].strip() for row in csv.DictReader(handle)}


def test_both_vocabularies_were_actually_read() -> None:
    """The positive control, without which the test below passes on two empty sets.

    It also pins that every id called "shared" really is in both, so a rename on either side that
    removes one shows up here rather than quietly making the list below fiction.
    """
    library_ids = set(load_library().types)
    rule_ids = _rule_ids()

    assert len(library_ids) >= 40, library_ids
    assert len(rule_ids) >= 100, len(rule_ids)
    assert library_ids >= _KNOWN_SHARED, sorted(_KNOWN_SHARED - library_ids)
    assert rule_ids >= _KNOWN_SHARED, sorted(_KNOWN_SHARED - rule_ids)


def test_no_new_condition_type_id_collides_with_a_verification_rule_id() -> None:
    """A sixth shared id is a decision, so it fails here until someone records it.

    The assertion is equality rather than a subset both ways round: a collision that GOES AWAY (a type
    renamed, a rule retired) leaves a stale entry above, and a stale "known problem" is how a list like
    this stops describing anything.
    """
    shared = set(load_library().types) & _rule_ids()

    assert shared == set(_KNOWN_SHARED), (
        "the condition library and the verification engine share these ids: "
        f"{sorted(shared)}; recorded: {sorted(_KNOWN_SHARED)}. A NEW one means a condition type and a "
        "rule now answer to the same string in tickets, logs and conversation. Rename the type, or add "
        "it above with both meanings if the overlap is genuinely harmless. A MISSING one means the list "
        "is stale: drop it."
    )
