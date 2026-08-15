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
# LP-495a +OC-1 (occupancy consistency — the FIRST rule activated on a NON-VACUOUS self-consistency
# rate: 0.9474 over 19 cases with a REAL spread and one real disagreement, unlike PR-3/PR-4's n=2
# single-valued 1.0. ⚠️ Its tag occupancy.consistent_with_signals is NOT re-kinded — it is SHARED
# with live OC-2, so re-kinding is a behaviour change on shipped code. The LP-406-4 activation
# precondition is resolved by the STATUS: on ratify-pending BOTH rules route to a human) -> 67.
# LP-495a +RE-1 +DT-6 (the mortgage-statement ↔ stated-liability reconciliation — ONE matcher serves both,
# ADR-375; NEITHER can produce `fired`, and neither reads the still-orphaned property.is_retained_reo /
# property.retained_pitia) +LO-2 (LOE completeness). All three deterministic — no model in their chain, so
# no self-consistency rate and no ratification. ⚠️ LO-1 HELD: it needs the list of conditions that REQUIRE
# an LOE, which is lender- and AUS-driven and enumerated in no document; deriving it from this run's own
# findings would make it a META-RULE over other rules' output, which nothing in the architecture does. -> 66.
# LP-496a +PE-1 +PE-3 (program eligibility). PE-1 decides only at the two ends of the conforming
# limit and ABSTAINS in the band between the baseline and the high-cost ceiling, where only the
# property COUNTY resolves it — MISMO parses <CountyName> but the Property model has no column, so
# it is dropped before projection; clearing that band would pass the high-cost jumbo the rule exists
# to catch. PE-3 uses HUD's ADJUSTED VALUE (the lesser of price and property value), NOT the
# catalog's "3.5% of price", and abstains on a missing Minimum Decision Credit Score rather than
# assuming the 3.5% tier. PE-2 HELD: `program.fha_case_number` has NO source — no extractor field,
# no FHA document type among the catalog's 163, and 0 hits across 2,558 raw PDFs. PE-4 HELD: no
# producer, no cited MPR section, and ZERO appraisals in the corpus (LP-492's 0/2 is now 0/0). -> 72.
# LP-497 +AS-4 (reserves adequacy). It was blocked on a 0/5 measurement of stmt.is_reserve_eligible —
# a tag NOT in its chain (build_reserves_view sums DB assets and takes its PITI divisor from the DTI
# calculation). The 0/5 itself was a question mismatch, not a model failure. What it actually lacked
# was its threshold, now tier P from B3-4.1-01 (08/07/2024), which also closed a recorded false-green:
# the old occupancy-only map returned 0 for EVERY principal residence, so a 2-4 unit primary needing
# 6 months read as satisfied. AS-7 is BUILT AND HELD — its enum coerces an honest abstain to a
# degraded run (LP-495c unfixed), and 2,557 raw PDFs contain no real NSF event. -> 73.
# LP-495c +DT-7 (ATR documentation). Its hold was never about the rule: dti.atr_factors_documented
# was declared WITHOUT the abstain its own prompt sanctioned, so _build_tag coerced an honest
# 'unknown' to confidence=None — the exact marker _scan_tag_degradations matches — and a legitimate
# abstain read as a broken pipeline. Fixed upstream in docs/snapshot-fact-tags.xlsx (four tags, not
# one: +txn.is_nsf_or_overdraft, +liab.in_application which is LIVE via CR-1/CR-4, and
# +stmt.is_reserve_eligible) with fact_tags.csv regenerated. DT-7 activated on the rate LP-495b
# already measured — 1.0000 over 4 cases, ratify-pending, measured_accuracy null. -> 74.
# LP-498 +FR-3 (unusual seller credits / side agreements) — the ONLY rule in the six-rule fraud
# cohort whose evidence exists: seller_credit_amount / _purpose / other_concessions_amount /
# side_agreements_referenced are typed fields on the purchase-contract extractor. Its malformed
# declaration (`enum: yes | no + detail`, which parsed to the literal "no + detail") was fixed in
# the xlsx first. FR-1 held (its tag receives extracted values, never a rendering, and the only
# reshape duplicates LP-474); FR-2 held (no producer either side, 0 loaded title commitments);
# FR-4 held (a bank-transaction tag asked about a pay-stub deduction); FR-5 held (one transaction
# per context cannot show a pattern across statements); FR-6 held (would be the first
# list-producing tag, and open-ended discovery has no closed vocabulary to abstain against). -> 75.
# LP-509-D1 +IH-9 (hazard policy expired) — a MISSING rule rather than a refinement of an existing one.
# LF-WCHG's ACORD 27 ran 06/25/2024 to 06/25/2025 and was thirteen months lapsed while the file was being
# processed; none of its 162 findings said so. IH-3 was the only rule reading that binder's dates and it
# compares the EFFECTIVE date to the CLOSING date, so on a file with no closing date it abstained — a
# couldnt_check about closing swallowed a fact true regardless of closing. IH-9 is deliberately a separate
# rule, not an outcome added to IH-3, because an outcome there would sit behind that same closing-date gate.
# Activation is the IH-3 path exactly: a parsed binder date, an exact compare, no AI tag in the chain and no
# threshold, so it is eligible on `no-ai-dependency` alone. -> 76.
EXPECTED_ACTIVE_RULE_COUNT: int = 76

__all__ = ["EXPECTED_ACTIVE_RULE_COUNT"]
