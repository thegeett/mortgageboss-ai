"""The one rule about a lender code's `status` (LP-909 §2, review).

⚠️ AN INVARIANT IS ONLY AS GOOD AS ITS ENUMERATION OF WHO WRITES IT, and this enumeration is about to
double. Until now `LenderConditionCode` rows were written in exactly one place —
`scripts/seed_lender_codes.py` — so "raised, never lowered" could live there as a local promotion and
be correct. LP-909's import is the second writer, and two independently-shaped statements of one rule
is how they drift.

That is the enrich finding one layer up: there, `round_numbers` was derived correctly and was only as
good as its enumeration of who creates conditions — import was covered, enrich was not, and the
conditions enrich created got no chips at all. Here it would be the status, and the symptom would be
a human decision silently reset by a sheet arriving.

⚠️ AND THE RULE IS NOT AN ORDERING, WHICH IS THE TRAP. `LenderCodeStatus` declares
`SEEDED, OBSERVED_UNMAPPED, MAPPED` in that order, so any `>`-style comparison would be *wrong while
reading as correct*: it would call SEEDED the lowest and happily demote it to OBSERVED_UNMAPPED. The
rule is specific rather than ordinal:

* `OBSERVED_UNMAPPED` is the only status that may be replaced — it means "arrived on a sheet, nobody
  has looked yet", so anything that explains the code is an improvement.
* `MAPPED` is a person's decision and outranks everything. Shipped data does not overrule a human.
* `SEEDED` is shipped data and is not demoted by a sheet merely mentioning the code again.

⚠️ NOTHING TESTED THIS BEFORE, AND A FILE LOOKED AS THOUGH IT DID. `tests/` never referenced
`seed_lender_codes` at all, and `test_lender_code_loader.py` — which sounds like the code map's test
— covers the YAML parser only: ten tests, no database, no status, no upsert. A downgrade would have
passed everything.
"""

from __future__ import annotations

from app.models.lender_condition_code import LenderCodeStatus

#: The only status a writer may replace. Everything else stands.
_REPLACEABLE = LenderCodeStatus.OBSERVED_UNMAPPED


def resolved_status(current: LenderCodeStatus, proposed: LenderCodeStatus) -> LenderCodeStatus:
    """What a row's status becomes when a writer proposes `proposed`.

    Returns `current` unchanged whenever the proposal would demote a decision already made — so a
    caller can assign the result unconditionally and cannot get it wrong by forgetting the rule.

    The import path proposes `OBSERVED_UNMAPPED` for a code it has just seen: on an unknown code
    that is the row's starting state, and on a known one this returns the existing status untouched,
    which is exactly "bump the counters, never reset the meaning".
    """
    if current is _REPLACEABLE:
        return proposed
    return current


def may_replace(current: LenderCodeStatus) -> bool:
    """Whether a writer's proposed status would actually be taken — for a caller that wants to log
    the difference rather than apply it silently."""
    return current is _REPLACEABLE


__all__ = ["may_replace", "resolved_status"]
