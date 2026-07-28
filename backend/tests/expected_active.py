"""The SINGLE source of truth for the EXPECTED live-rule COUNT (the test-side drift guard).

Many tests assert "N rules are live" as an incidental equivalence check. Before this, every activation
ticket had to bump that hardcoded count in ~8 places (LP-406 / LP-412 / LP-407-3 each churned the same
sites). This centralizes it: activating a rule updates registry.ACTIVE_RULE_IDS (the app) AND this constant
(the test's independent expectation) — two places, by design.

WHY a hardcoded int, not ``len(ACTIVE_RULE_IDS)``: the guard's whole value is being INDEPENDENT of the app
value, so an UNINTENDED change to ACTIVE_RULE_IDS is caught. Deriving it from ACTIVE_RULE_IDS would make
every ``len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT`` assertion circular (always true) — catching
nothing. Update this number when (and only when) a rule genuinely activates.

(The tests that assert the exact ORDERED ACTIVE_RULE_IDS *tuple* keep their own explicit tuple — that is a
stronger, deliberately-independent guard and a separate concern from this count.)
"""

from __future__ import annotations

# Bumped by each activation: … LP-407-3 (+PC-2) → 28 → LP-417 (+IH-3) → 29 → LP-407-4 (+PC-3) → 30 →
# LP-423 (+IN-12) → 31.
EXPECTED_ACTIVE_RULE_COUNT: int = 31

__all__ = ["EXPECTED_ACTIVE_RULE_COUNT"]
