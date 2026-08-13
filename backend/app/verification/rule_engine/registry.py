"""The rule registry + GENERIC dispatch (LP-324/325) — the orchestrator runs the rule SET.

Adding a rule is now a SPEC (+ its tags) and a line in ``ACTIVE_RULE_IDS`` — never new evaluation
Python. Each active rule is dispatched by WHICH EVALUATION BLOCK its spec carries: ``consistency`` →
the generic cross-source consistency evaluator; ``deterministic`` (calculative/structural) → the
generic deterministic evaluator; ``judgment`` (judgmental) → the generic judgment evaluator; none
(out_of_scope) → nothing evaluates (it resolves to ``not_applicable`` — §8 Tab 4, not a couldnt_check).
Dispatch is by block (not bare kind) because a STRUCTURAL rule may carry either a deterministic OR a
consistency body.
"""

from __future__ import annotations

from app.ai.rule_judgment import Reasoner
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.tag import Tag

# The rules wired for evaluation (each has a spec + its tags). A wave adds a rule_id here + a spec.
# ID-2/ID-4 (cross-source consistency) went LIVE at LP-326; LP-323-ID-B added ID-1 (name), ID-3 (DOB),
# ID-6 (1003 completeness); LP-329 adds ID-7 (marital/title, deterministic per_document) + ID-9 (POA
# acceptability, judgment per_document) — both DOCUMENT-TYPE scoped (GAP-C), so a non-matching document
# resolves to not_applicable, never a couldnt_check flood. All authored as DATA.
# The BASE set — the rules live before LP-389's first activation pass. A wave adds a rule_id + a spec.
_BASE_ACTIVE: tuple[str, ...] = (
    "AS-1",
    # OC-2 is live on an UNSCORED AI tag (occupancy.consistent_with_signals) — ACCEPTED, deliberately (LP-425,
    # ADR-336): safe because OC-2 is judgmental → it RATIFIES every verdict (a human signs each, LP-376-B), so an
    # unmeasured tag can never auto-ship. NOT an oversight — it predates the gate; the acceptance ends when the
    # tag is calibrated (OC-1 needs it too), after which OC-2 moves into the gate. The ratify-mode is the guard
    # (pinned: test_lp425_oc2_acceptance). DO NOT flip OC-2 to auto without calibrating the tag first.
    "OC-2",
    "ID-2",
    "ID-4",
    "ID-1",
    "ID-3",
    "ID-6",
    "ID-7",
    "ID-9",
    # LP-332 — ID-8 (citizenship/residency eligibility): its inputs (id.citizenship parsed under the
    # borrower subject, program.type parsed under loan) are deterministic passthroughs (no uncalibrated
    # AI), and its judgment is ratification-pending — genuinely live.
    "ID-8",
    # LP-333 — IN-2 (pay-stub recency): parsed-only (income.pay_date → the loan-level days-since-pay
    # derived tag), no AI, no calibration risk; verified to produce real verdicts end-to-end.
    "IN-2",
)

# LP-389 / LP-389-A — the FIRST activation pass (+ its follow-up). Three inert rules EARNED activation via the
# eligibility gate (activation_bars.is_eligible), fail-closed: a rule activates only when its AI-tag accuracy
# meets a Priya-VALIDATED bar, or its parsed input RESOLVES to real values AT THE SUBJECT THE RULE READS. An
# unmeasured tag, an unvalidated bar, or an unresolved input holds the rule — the inverse of the run-level fail-opens.
#   IN-1 — income.documented_monthly measured 100% (LP-379-D); bar 0.98 auto, validated by Priya (LP-380). This
#          SUPERSEDES the LP-333 deferral: documented_monthly is now calibrated (100%) and the derived producer
#          is fixed. Auto, fraud-adjacent — a real income discrepancy is a finding a human sees. (On LF-6T3N it
#          couldnt_checks — that fixture's MISMO carries no borrower STATED income — but the AI side is
#          calibrated and the chain is correct; it resolves on a file that states income. A DATA gap, not a defect.)
#   IN-5 — income.employer_normalized measured 100% (LP-379-D); bar 0.95 auto, validated (LP-380). Auto.
#          Resolves end-to-end on LF-6T3N: SATISFIED on both borrowers.
#   ID-5 — LP-389 HELD it: a producer/consumer SUBJECT MISMATCH (its inputs materialized on the DOCUMENT subject
#          but ID-5 read them at "loan"), so it couldnt_checked on every file. LP-389-A FIXED it — ID-5 is now
#          PER BORROWER, reading the borrower's belongs_to-attributed ID expiration (id.borrower_id_expiration,
#          derived) against the loan's one closing date (contract.loan_closing_date, derived). The input now
#          resolves at the subject the rule reads (input_resolves flipped true), so the gate lets it through.
#          Resolves end-to-end on LF-6T3N: SATISFIED for both borrowers (both DLs unexpired at closing).
_LP389_ACTIVATED: tuple[str, ...] = ("IN-1", "IN-5", "ID-5")

# LP-384 — the SECOND activation pass: three STUCK deterministic (no-AI) rules whose inputs LF-6T3N lacked
# now resolve, verified on the fixture, so the gate (input_resolves) admits them. Each proves a KNOWN answer.
#   AS-10 — stmt.min_account_months ALREADY resolves on the BASE LF-6T3N (its statements grew account identity
#           + period dates as the fixture matured; LP-381's "input absent" went stale). SATISFIED — every
#           account has >= 2 months. No fixture change needed.
#   AS-9  — stmt.page_count_declared/present. build_lf6t3n_plus adds a statement that declares 5 pages but has
#           4 present → AS-9 FIRES ("a page is missing"); a complete statement satisfies. Input resolves.
#   IN-4  — income.max_employment_gap_days. build_lf6t3n_plus adds two VOEs with a deliberate 77-day gap →
#           IN-4 FIRES (beyond the 30-day window); a no-gap variant satisfies. Input resolves.
# STILL HELD (fail-closed): AS-3 (no §3B cash-to-close calculator — its recipe is a stub, LP-383), and IN-3
# (its derived recipe reads income.documented_monthly (AI) — a transitive AI dependency like IN-1, an
# income-wave rule; its no-ai bar is a MISCLASSIFICATION reported in activation_bars.yaml).
_LP384_ACTIVATED: tuple[str, ...] = ("AS-9", "IN-4", "AS-10")

# LP-390-7 — the FIRST income-wave activation: two AI rules whose load-bearing tags Priya's labels finally
# measured (LP-390-5/5a). Both go live through the gate (validated:true + measured_accuracy >= the 0.90 bar).
#   AS-2  — Earnest-money sourcing (ships AUTO). apparent_category re-scored 100% concrete (n=17, LP-390-5a) +
#           has_identified_source 93.8% (n=16, LP-390-5); measured_accuracy 0.938. ⚠️ its trigger value
#           loan_proceeds is n=0 on LF-6T3N — the tag is measured broadly but that value is UNTESTED (a file
#           with a loan-proceeds deposit would strengthen it); it must not falsely fire (Phase-2 verified).
#   AS-12 — Borrowed-funds detection (judgmental -> ships RATIFY; surfaces to needs_review, never an auto
#           verdict). Reasons over apparent_category broadly, so the loan_proceeds n=0 caveat does not bind it.
# STILL HELD after LP-390-7: AS-5 (design question ADR-302 + gift n=0 — validated:false, the loader rejects a
# stray true on its null-threshold/not-calibratable state).
_LP390_ACTIVATED: tuple[str, ...] = ("AS-2", "AS-12")

# LP-390-9 — Priya signed off IN-3's bar (0.98 auto). IN-3 is an AI rule (LP-384 reclassification): its derived
# YTD-annualized shortfall reads income.documented_monthly (AI, income_amounts) — the SAME tag + evidence as
# IN-1, measured 100% (LP-379-D) >= the 0.98 bar. Because IN-3 DECLARES that tag as load-bearing, income_amounts
# folds into _required_ai_groups (already required via live IN-1), so IN-3's tag is PRODUCED, not just declared —
# it does not couldnt_check for a missing tag (an honest no-stated-income abstain is a different, correct thing).
_LP390_9_ACTIVATED: tuple[str, ...] = ("IN-3",)

# LP-393-6 — Priya signed off the four scenario-calibrated income/asset bars after their load-bearing tags
# scored on the LP-393-1 fixture (LP-393-4b): IN-7 same_line_of_work 100%, IN-10 is_declining 100%, IN-11
# has_2yr_history 100% (RE-SCORED after her B14 ruling — a terminated job's two years DOES count as history),
# AS-11 liquidation_terms 100%. She set the heights (0.90/0.95/0.90/0.90) and chose AUTO, KNOWINGLY overriding
# the ratify-only recommendation on a synthetic-only basis. Their AI groups (income_stability / asset_facts)
# fold into _required_ai_groups automatically because it derives from ACTIVE_RULE_IDS. ⚠️ IN-7 is JUDGMENTAL,
# so despite the AUTO sign-off it ships RATIFY (LP-376-B armor in judgment.py) — active, but surfaces to
# needs_review, never an auto verdict; truly-auto needs a kind reclassification (a separate ticket, ADR-316).
_LP393_ACTIVATED: tuple[str, ...] = ("IN-7", "IN-10", "IN-11", "AS-11")

# LP-406-2b — the FIRST Bucket 2 rule to go LIVE. AS-8 (statement chaining) reads the derived stmt.continuity
# tag (LP-410, which unblocked the LP-406-2/ADR-322 ordered-pairwise stop). NO AI dependency (derived from
# parsed statement balances) and NO Priya threshold (exact carryover) → it clears the no-ai-dependency gate
# (input_resolves: stmt.continuity == "chained" on LF-6T3N → AS-8 SATISFIED). Its "broken" finding path ships
# unexercised on real data (LF-6T3N chains cleanly) — the AS-2 one-sided-trigger caveat (activation_bars.yaml).
_LP406_ACTIVATED: tuple[str, ...] = ("AS-8",)

# LP-412 — Priya signed off both remaining Bucket 2 bars, so they clear the gate and go live (25 → 27):
#   IN-6 — employer coverage. She approved the 0.95 bar, "same as IN-5" (same tag income.employer_normalized,
#          same 100% measurement). calibratable-now + validated + 1.0 >= 0.95 → eligible. Its `uncovered` branch
#          ships needs_review (ADR-325); its transitive AI tag folds in via live IN-5 (income_employer required).
#   PC-7 — closing-date realism. She signed off the two-sided window (any past date fires; 90-day far-future
#          limit). The FIRST rule live via LP-411's no-ai-threshold-pending status: input_resolves ∧ validated.
_LP412_ACTIVATED: tuple[str, ...] = ("IN-6", "PC-7")

# LP-407-3 — the ONE surviving Bucket 2.5 wire-and-write rule (27 → 28). PC-2 (purchase price matches loan
# terms) compares two INDEPENDENT loan-level tags — the contract's sale price (contract.loan_sales_price,
# LP-407-2's promotion) and the 1003/MISMO purchase price (property.purchase_price) — and fires on a mismatch.
# NO AI dependency (both parsed/derived) and NO threshold (EXACT compare, rule_kinds threshold_needs_signoff=
# false) → it clears the no-ai-dependency gate (input_resolves: both are 365000 on LF-6T3N post-LP-414 → PC-2
# SATISFIED). Its sibling census rules were STOPPED: DT-5 vacuous (LP-407-2); DT-2 vacuous + no HOA-presence tag;
# DT-4 needs an unwired assessed-value producer + a Priya tax rate (LP-407-3 D1 — ADR-330).
_LP407_ACTIVATED: tuple[str, ...] = ("PC-2",)

# LP-417 — the first Bucket 3 rule live (28 → 29). IH-3 (insurance effective date <= closing) compares two
# loan-level DATE tags — ins.loan_effective_date (LP-417's promotion off the already-extracted homeowners_
# insurance binder) and contract.loan_closing_date — natively (the ID-5 date-vs-date shape). NO AI dependency
# and NO threshold (EXACT) → the no-ai-dependency gate; input_resolves on the binder scenario fixtures. LF-6T3N
# has no binder → IH-3 couldnt_checks there (an honest absence, not a bug — LP-414 A3).
_LP417_ACTIVATED: tuple[str, ...] = ("IH-3",)

# LP-407-4 — the LAST blocker-free rule (30). PC-3 (property address matches) branches on the derived
# property.address_normalized_match (a deterministic contract-vs-MISMO subject-address compare with the
# consistency normalizers). NO AI dependency and NO threshold → the no-ai-dependency gate; input resolves on
# the address scenarios. A mismatch routes to needs_review (ADR-325 — the deterministic normalizers cannot
# expand abbreviations, so a possible variant is surfaced for a human, never auto-fired). LF-6T3N has no MISMO
# subject address → PC-3 couldnt_checks there (an honest absence — LP-414).
_LP4074_ACTIVATED: tuple[str, ...] = ("PC-3",)

# LP-423 — IN-12 goes live (31). Its self-employment SCOPE gate (income.is_self_employed) became a DETERMINISTIC
# read of Schedule C presence (LP-422), resolving the LP-419 income.type-unscored blocker; income.type is dropped
# as load-bearing. The VERDICT tag has_2yr_history is measured 100% + Priya-validated at 0.9 via IN-11 (the IN-6
# inherit pattern), so the bar is calibratable-now / validated / 1.0 >= 0.9 -> eligible. ⚠️ ACCEPTED RISK (D3,
# ADR-335): the gate rests on the STARTER tax-return extractor (no golden files) — accepted because a missed
# Schedule C is a wrong SCOPE (not_applicable, visible) IN-11 still backstops, not a false verdict. IN-13 is NOT
# activated (D1: "other income continuance" is broader than rental — gating on rental would narrow it; and its
# verdict tag continuance_3yr is uncalibrated).
_LP423_ACTIVATED: tuple[str, ...] = ("IN-12",)

# LP-428 — IN-8 (VOE present) + IN-9 (offer letter present) go live (31 -> 33) on Priya's sign-off. LP-426 scored
# both verdict tags (income.voe_present, income.offer_letter_present) at 100% (12/12), TWO-SIDED (6 yes / 6 no), 0
# disagreements, on her blind labels over LP-418's fixture, and PROPOSED 0.95 AUTO bars. Priya APPROVED 0.95 for
# both, weighing the SYNTHETIC caveat (LP-418 scenario docs with hand-set document_type — the report given a
# correct classification, not real-VOE recognition; recorded in each bar for exactly this). Flipping validated:true
# clears each calibratable-now gate (1.0 >= 0.95). Both tags come from the income_docs group, which was PENDING-only
# (materialized on a throwaway snapshot for the blocked-rule check) and now folds into _required_ai_groups — so the
# tags are PRODUCED on the live snapshot when the rules run (no LP-384 missing-tag trap). IN-13 is NOT activated —
# the sibling stays HELD on two open blockers (the missing 'has other income' scope gate ADR-335; income.type still
# unscored — LP-423/LP-427). Structural presence checks → ships auto per their kind.
_LP428_ACTIVATED: tuple[str, ...] = ("IN-8", "IN-9")

# LP-429 — AS-6 (account ownership) goes live (33 -> 34) on Priya's sign-off. LP-404 turned it into the FIRST
# multi-tag rule (owner=no -> fired, owner=unknown / co_holder=yes -> needs_review, owner=yes -> satisfied; the
# middle rows COUNT). Its bar has been proposed since LP-397 (0.95 auto). Priya APPROVED 0.95, weighing four
# things: the height; ships AUTO (LP-397's ratify-only caveat is now MET — LP-398's six negatives, four firing in
# LP-404); WHAT THE BAR MEASURES — the ROUTING drivers owner_matches_borrower + non_borrower_co_holder (both
# 11/11), NOT the reason-only holder_name_variance (5/11), the first multi-tag precedent (ADR-338); and the
# N2/P2 variance taxonomy residual it ships with. Its three tags come from the stmt_facts group, which was
# PENDING-only and now folds into _required_ai_groups — so they are PRODUCED on the live snapshot when AS-6 runs
# (no LP-384 missing-tag trap). Structural -> ships auto (LP-424 kind cross-check passes).
_LP429_ACTIVATED: tuple[str, ...] = ("AS-6",)

# LP-430 — IN-15 (terminated-employment documentation) goes live (34 -> 35). Priya's B14 ruling (LP-393-6) spun
# off a SEPARATE documentation check from has_2yr_history: a terminated job's 2 years still count as history
# (IN-11), but whether the employment is documented as CURRENT is this check — any PAST VOE end date requires a
# subsequent pay stub. DETERMINISTIC (income.terminated_employment, derived per-borrower from income.employment_end
# + income.pay_date — two date facts) → no AI, no threshold (ADR-334 escape hatch, no calibration round). So the
# AS-8/IH-3 no-ai-dependency path — eligible on input_resolves alone (verified on build_terminated_employment_
# snapshot: fire / satisfy / future-n/a / no-VOE-n/a). Structural → ships auto. Does NOT change IN-11/IN-12.
_LP430_ACTIVATED: tuple[str, ...] = ("IN-15",)

# LP-433 — IN-16 (pay-stub-only documentation) goes live (35 -> 36). Priya's B12 ruling (LP-393-6), the sibling
# of IN-15's B14 check: a 2-year history cannot rest on pay stubs alone — a W-2 or 1099 is required. DETERMINISTIC
# (income.history_documentation, derived per-borrower from the DOCUMENT-TYPE PRESENCE of the borrower's attributed
# w2 / 1099 / pay_stub) → no AI, no threshold (ADR-334 escape hatch, no calibration round). So the AS-8/IH-3/IN-15
# no-ai-dependency path — eligible on input_resolves alone (verified on build_pay_stub_only_snapshot: fire / W-2
# satisfy / 1099 satisfy / VOE-only n/a). Structural → ships auto. Does NOT change IN-6/IN-11/IN-15. The LAST rule
# reachable without new document capability (LP-432).
_LP433_ACTIVATED: tuple[str, ...] = ("IN-16",)

# LP-447 — IH-1 (insurance adequacy) goes live (36 -> 37), unblocked by LP-446. The dwelling loss-settlement
# BASIS check Priya's ruling replaced the retired coverage-vs-loan arithmetic with (ADR-340, effective
# 2026-03-18): ins.dwelling_settlement_basis (derived normalisation of the LP-446 typed-core field) ==
# replacement_cost -> satisfied / actual_cash_value -> fired / unknown -> couldnt_check. NO AI, NO threshold
# (a boolean basis check) -> the AS-8/IH-3 no-ai-dependency path, eligible on input_resolves alone (resolves on
# the binder fixtures; proven on the 4 real policies). Structural -> ships auto. Fails closed on an unrecognised
# basis; per-document, so a file with no binder is not_applicable (DIFFERENT from IH-3's missing-binder couldnt_check).
_LP447_ACTIVATED: tuple[str, ...] = ("IH-1",)

# LP-485 — the date-compare family goes LIVE. All three are deterministic (no AI tag in any chain), so none
# is calibration-gated: CL-1 clears on input_resolves alone (no domain threshold — a date ordering), and
# CR-13 / PR-6 clear on input_resolves + validated, their windows RESEARCHED AND CITED to the publisher's
# live guide in each spec's reference_values (Fannie B1-1-03 04/02/2025 — four months; B4-1.2-04 06/04/2025
# — twelve months, update beyond four). That citation is our calibration and stands until Priya revises it;
# every value is listed in docs/domain/priya-open-questions.md for her review.
_LP485_ACTIVATED: tuple[str, ...] = ("CL-1", "CR-13", "PR-6")

# LP-486 / ADR-376 — CR-12 (disputed accounts). Deterministic detection over a CLOSED vocabulary that
# abstains on anything unrecognised: the same `is_disputed` field is clean Y/N on one bureau's reports and
# free text on another's, so a rule that classified open text would silently miss disputes.
_LP486_ACTIVATED: tuple[str, ...] = ("CR-12",)

# LP-487 — the insurance pair. IH-2 (mortgagee clause) carries a CATALOG EDIT with it: rule_kinds.csv
# moved it from `ai_fuzzy_match` to `deterministic_only`, because that kind predates typed extraction —
# the perception step is already spent by the extractor (mortgagee_name fills on 14/15 bench binders) and
# what remains is a normalised string compare. A MISMATCH IS needs_review, NEVER fired: a correspondent's
# creditor and the investor who will hold the loan legitimately differ, so a firing rule would be wrong on
# a correct file. IH-7 (condo master policy) is a presence + adequacy check whose two bounds are researched
# and cited (Fannie B7-4-01 08/05/2026 — $1M general liability per occurrence; B7-3-03 08/05/2026 — 100% of
# replacement cost); its fidelity/crime leg (B7-4-02) is deliberately unbuilt because the unit-count input
# never resolves.
_LP487_ACTIVATED: tuple[str, ...] = ("IH-2", "IH-7")

# LP-488 — MI-1, the FIRST use of the PROGRAM axis. `program.type` scopes it to conventional as an
# APPLICABILITY PREDICATE (not an outcome), so an FHA file is not_applicable and a file that states no
# program is couldnt_check rather than silently skipped. ⚠️ MI-1 never FIRES: it can prove MI is
# REQUIRED (LTV > 80) but cannot prove MI is PRESENT — no document type in the system carries an MI
# certificate — so the requirement routes to needs_review for confirmation.
# MI-4 is the FHA side of the same axis. Only the UPFRONT premium is evaluated — no document carries a
# monthly MIP figure, so the annual leg is deliberately unbuilt rather than built on an invented input.
# CO-1 is a document-type presence read, PRESENCE ONLY — warrantability (CO-3/CO-5) has no source field.
# AU-3 normalises the AUS decision across DU and LPA wording (ADR-376). ⚠️ n=1 corpus, and that one is an
# LPA reading "ACCEPT" — a term the DU-shaped catalog vocabulary does not contain, which is the concrete
# evidence that a field-equality rule would have been wrong.
# ⚠️ RE-2 IS NOT HERE AND WILL NOT BE: no REO/retained-property concept exists in MISMO or the data model,
# and nothing states that a borrower RETAINS a property. Dropped with a reason (LP-488), not deferred.
_LP488_ACTIVATED: tuple[str, ...] = ("MI-1", "MI-4", "CO-1", "AU-3")

# LP-490a / ADR-378 — activated on a SELF-CONSISTENCY rate, not a measured accuracy, with RATIFICATION as
# the safety substitute: every finding these produce carries ratification_pending=True (enforced in
# deterministic.py), so a wrong tag costs a processor's attention and can never auto-assert.
# ⚠️ Rates are model-produced and measure STABILITY, not correctness — a systematically wrong tag scores
# 1.0. CR-1/CR-4 share one matcher (1.0000, 13 cases); CR-8 is 0.9714 over 35 real tradelines.
# ⚠️ CR-6 and CR-10's rates cover NEGATIVE CASES ONLY — the corpus holds zero derogatory events and zero
# collection codes, so both derivations were answering "no" on all 35 tradelines. Their bars say so.
_LP490A_ACTIVATED: tuple[str, ...] = ("CR-1", "CR-4", "CR-8", "CR-6", "CR-10")

# LP-491 — TI-1 (title commitment parties). ⚠️ NOT ratify-pending: the LP-491 catalog edit moved it to
# `deterministic_only` (IH-2's precedent, the second time typed extraction turned out to have already
# spent the perception step), so it has no model in its chain and activates on input_resolves alone.
# A mismatch is needs_review, never fired — a vesting difference is frequently legitimate.
# TI-2 and TI-6 are ai_judgment and activate on `ratify-pending` (ADR-378) — a judgment rule ratifies
# every verdict, so an uncalibrated tag can never auto-assert. ⚠️ Their rates compare VERDICTS, which a
# judgment rule collapses to needs_review, so they show pipeline stability rather than judgment stability.
_LP491_ACTIVATED: tuple[str, ...] = ("TI-1", "TI-2", "TI-6")

# LP-492 — the appraisal lane. PR-2 is deterministic (no model in its chain), so it activates on
# input_resolves alone. ⚠️ PR-8 is DROPPED, not deferred: a disaster-area reinspection needs a FEMA
# declaration, and no field in any of the 121 schema specs — nor MISMO — states one. CR-3's shape.
# PR-7 joins PR-2 on the deterministic route (PC-3's precedent — a catalog ai_fuzzy_match row with a
# deterministic body; no edit needed). PR-3/PR-4/PR-5 activate on ratify-pending. ⚠️ Their rates are the
# WEAKEST in any cohort: n=2 with a SINGLE-VERDICT spread, so they show pipeline stability, not judgment.
_LP492_ACTIVATED: tuple[str, ...] = ("PR-2", "PR-7", "PR-3", "PR-4", "PR-5")

# LP-493 — the purchase-contract lane. ⚠️ ONLY PC-8 ACTIVATES.
# PC-5 is BUILT AND HELD: its derivation returned a uniform abstain ({unknown: 2}), and a rate over a
# single abstain value carries no information (the CR-8 shape) — recording it would activate a rule on
# nothing. PC-1 is DROPPED: its `title.parties_match` duplicates TI-1's live comparison (one matcher, one
# comparison — LP-483), and its other input `contract.arms_length` has only `parties_relationship_
# disclosed`, which is 0/5 on the real contracts (TI-3/4/5's shape).
_LP493_ACTIVATED: tuple[str, ...] = ("PC-8",)

# LP-494 — the condo lane. ⚠️ CO-3 AND CO-4 ACTIVATE; CO-5 IS BUILT AND HELD.
# CO-3 was DROPPED mid-ticket and un-dropped on evidence: it is the FIDELITY leg, which IH-7's own spec
# header excludes, so it duplicates nothing — and its two inputs fill 8/8, the lane's strongest.
# CO-4's reserve percentage reads from the HOA STATEMENT type, which is where HOA BUDGETS classify; the
# first search looked only at documents labelled condo_questionnaire and wrongly concluded no budget
# document type existed.
# ⚠️ CO-5 STAYS HELD, and it is the only one of the three whose blocker research could not remove: NOT ONE
# of its five inputs (delinquency, commercial share, unit count, single-entity units, litigation) resolves
# on any document of any type. hoa_certification declares every one of them and ZERO such documents exist
# (ADR-354 exactly: schema present, data absent). Activating it would produce couldnt_check on 100% of
# files forever with every test green — ADR-286/289, the pattern that has killed four live rules.
_LP494_ACTIVATED: tuple[str, ...] = ("CO-3", "CO-4")

# The gate is the source of truth: test_activation_gate_lp389 asserts ACTIVE_RULE_IDS - _BASE_ACTIVE ==
# eligible_rule_ids() — a rule CANNOT enter this set without meeting the eligibility gate (not a hand-list).
ACTIVE_RULE_IDS: tuple[str, ...] = (
    *_BASE_ACTIVE,
    *_LP389_ACTIVATED,
    *_LP384_ACTIVATED,
    *_LP390_ACTIVATED,
    *_LP390_9_ACTIVATED,
    *_LP393_ACTIVATED,
    *_LP406_ACTIVATED,
    *_LP412_ACTIVATED,
    *_LP407_ACTIVATED,
    *_LP417_ACTIVATED,
    *_LP4074_ACTIVATED,
    *_LP423_ACTIVATED,
    *_LP428_ACTIVATED,
    *_LP429_ACTIVATED,
    *_LP430_ACTIVATED,
    *_LP433_ACTIVATED,
    *_LP447_ACTIVATED,
    *_LP485_ACTIVATED,
    *_LP486_ACTIVATED,
    *_LP487_ACTIVATED,
    *_LP488_ACTIVATED,
    *_LP490A_ACTIVATED,
    *_LP491_ACTIVATED,
    *_LP492_ACTIVATED,
    *_LP493_ACTIVATED,
    *_LP494_ACTIVATED,
)


async def evaluate_rules(
    snapshot: Snapshot,
    *,
    judgment_reasoners: dict[str, Reasoner] | None = None,
    consistency_reasoners: dict[str, Reasoner] | None = None,
    confidence_floor: float | None = None,
    rule_ids: tuple[str, ...] = ACTIVE_RULE_IDS,
) -> tuple[list[RuleEvaluation], dict[str, dict[str, Tag]]]:
    """Evaluate every requested rule generically (by evaluation block, from its spec).

    Returns the evaluations + any ``rule_judgment`` tags produced, keyed ``{subject_id: {tag_id: Tag}}``
    (LP-327 — a judgment rule may produce a tag PER SUBJECT, so the tags are subject-scoped) for the
    caller to write back into the tags layer. ``judgment_reasoners`` / ``consistency_reasoners`` inject
    a keyless stub per rule (tests). Each rule GATES itself (LP-315/319): the dispatcher lets them all
    run and never skips one silently.
    """
    judge_reasoners = judgment_reasoners or {}
    con_reasoners = consistency_reasoners or {}
    results: list[RuleEvaluation] = []
    judgment_tags: dict[str, dict[str, Tag]] = {}

    for rule_id in rule_ids:
        spec = load_rule_spec(rule_id)
        if spec.consistency is not None:
            results.extend(
                await evaluate_consistency_rule(
                    spec,
                    snapshot,
                    reasoner=con_reasoners.get(rule_id),
                    confidence_floor=confidence_floor,
                )
            )
        elif spec.deterministic is not None:
            results.extend(
                evaluate_deterministic_rule(spec, snapshot, confidence_floor=confidence_floor)
            )
        elif spec.judgment is not None:
            output_tag = spec.judgment.output_tag
            for evaluation in await evaluate_judgment_rule(
                spec,
                snapshot,
                reasoner=judge_reasoners.get(rule_id),
                confidence_floor=confidence_floor,
            ):
                results.append(evaluation.evaluation)
                if evaluation.judgment_tag is not None:
                    # Key the produced verdict tag under ITS subject (LP-327); OC-2's loan subject
                    # lands under LOAN_SUBJECT exactly as before (equivalence).
                    subject = evaluation.evaluation.subject_id
                    judgment_tags.setdefault(subject, {})[output_tag] = evaluation.judgment_tag
        # No evaluation block (out_of_scope) → nothing evaluates (not_applicable; no finding).

    return results, judgment_tags


__all__ = ["ACTIVE_RULE_IDS", "evaluate_rules"]
