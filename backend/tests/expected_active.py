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
# LP-423 (+IN-12) → 31 → LP-428 (+IN-8, +IN-9) → 33 → LP-429 (+AS-6) → 34 → LP-430 (+IN-15) → 35 →
# LP-433 (+IN-16) → 36 → LP-447 (+IH-1, insurance adequacy — the dwelling settlement basis) → 37.
# LP-485 (+CL-1, +CR-13, +PR-6 — the date-compare family: rate lock vs closing, credit age, appraisal age;
# all deterministic, CR-13/PR-6's windows researched + cited to Fannie B1-1-03 / B4-1.2-04) → 40.
# LP-486 (+CR-12 — disputed accounts, closed-vocabulary abstain, ADR-376) → 41.
# LP-487 (+IH-2 — mortgagee clause, a normalised name compare that can only needs_review, never fire;
# +IH-7 — condo master policy presence + adequacy, bounds cited to Fannie B7-4-01 / B7-3-03) → 43.
# LP-488 (+MI-1 — conventional MI requirement; the PROGRAM axis's first use) -> 44.
# LP-488 (+MI-4 — FHA upfront MIP, the FHA side of the program axis) -> 45.
# LP-488 (+CO-1 — condo questionnaire presence) -> 46.
# LP-488 (+AU-3 — AUS recommendation, DU/LPA closed vocabulary) -> 47. ⚠️ RE-2 was in the LP-488 cohort
# and is DROPPED, not deferred: no REO/retained-property concept exists in MISMO or the data model.
# LP-490a (+CR-1, +CR-4, +CR-8 — activated on a SELF-CONSISTENCY rate with ratification as the safety
# substitute, ADR-378; NOT a measured accuracy) -> 55.
# LP-491 (+TI-1 — title commitment parties; a CATALOG EDIT to deterministic_only, so no model in its
# chain and no self-consistency rate needed) -> 55.
# LP-492 (+PR-2 — appraised value vs purchase price; deterministic, no model in its chain) -> 56.
# LP-492 (+PR-7 deterministic; +PR-3/PR-4/PR-5 ratify-pending. ⚠️ PR-8 DROPPED — no FEMA/disaster field
# exists in any of the 121 schema specs or MISMO, so its trigger is unstateable: CR-3's shape) -> 60.
# LP-493 (+PC-8 — personal property, surfaces only. ⚠️ PC-5 BUILT BUT HELD: its derivation returned a
# uniform abstain BEFORE LP-493a's context fixes; the re-derivation after them scored a MEASURED
# 0.5000 (2 cases, 1 disagreement), so PC-5 is held on a measured failure, not on an absent number. PC-1 DROPPED: duplicate
# matcher + a 0/5 field) -> 61.
# LP-494 +CO-3 +CO-4 (the condo lane; CO-5 built and held — no input resolves on any document) -> 63.
# LP-495a +RE-1 +DT-6 (the mortgage-statement ↔ stated-liability reconciliation — ONE matcher serves both,
# ADR-375; NEITHER can produce `fired`, and neither reads the still-orphaned property.is_retained_reo /
# property.retained_pitia) +LO-2 (LOE completeness). All three deterministic — no model in their chain, so
# no self-consistency rate and no ratification. ⚠️ LO-1 HELD: it needs the list of conditions that REQUIRE
# an LOE, which is lender- and AUS-driven and enumerated in no document; deriving it from this run's own
# findings would make it a META-RULE over other rules' output, which nothing in the architecture does. -> 66.
EXPECTED_ACTIVE_RULE_COUNT: int = 66

__all__ = ["EXPECTED_ACTIVE_RULE_COUNT"]
