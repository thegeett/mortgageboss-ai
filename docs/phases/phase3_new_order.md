NOW — Live rules that don't work
LP-371 — Wire OC-2's occupancy tags

Both load-bearing tags declared in the vocabulary, never in tag_production.yaml → OC-2 couldnt_checks on every file, structurally
property.occupancy exists in MISMO → occupancy.stated is a parsed declaration
occupancy.consistent_with_signals needs its AI group declared
A whole live category (occupancy fraud) silently unchecked

LP-372 — ID-4's filter gate: settle the design question

One unknown address candidate vetoes the entire per-borrower comparison
Bank statements reliably type unknown → any realistic file may poison ID-4 permanently
Decide: veto, or exclude the unknown candidate and compare the rest?
A live auto-shipping consistency rule on an identity-fraud signal that may never fire

LP-373 — The orphan guard

Third orphan found (housing.insurance_monthly, dti.qualifying_income_monthly, now OC-2's two)
The vocabulary declares producer=AI; nothing produces
A test that fails when a fact_tags.csv tag with a producer has no declaration and no code writing it
The analogue of LP-369's parsed guard, one seam over


NEXT — Make the surface honest
LP-374 — Wire the homeowners insurance producer

Extractor exists (annual_premium), nothing wires it → the DTI can never compute on any file
No binder → unknown with a reason. Never 0
Unblocks AS-4 and the DTI wave; stops the UI showing a fabricated $0.00

LP-375 — The read path

_build_status drops GREEN → Tab 2 (Satisfied) is unreachable from the API
Return rule findings with evaluation_outcome, subject_key, load_bearing_tags
Expose gated/gate_reason in the DTI view schema
Never sum the two systems' counts

LP-376 — The five tabs + provenance

Needs attention · Satisfied · No longer applies · Not applicable · Old Findings (quarantined)
The honesty contract in tests: couldnt_check in Tab 1, never Tab 2/4
Provenance rendered — each tag's value, confidence, reasoning
Subject as a human recognizes it

LP-377 — LP-365's three fail-open bugs

The status guard is a no-op (in-memory check across sessions)
Enqueue failure is swallowed → run reports COMPLETED with no rule engine
The cache is keyed on cross-source inputs → skips the rule engine on rule-relevant changes
All three are run-level false-greens


THEN — Before spending Priya's time
LP-378 — The dormant tag-layer smoke test

The income/asset AI groups have never executed on real data, once
_required_ai_groups only runs groups a live rule consumes
Run them once on a real file → do the producers produce?
Calibration is necessary but may not be sufficient — this de-risks Epic 1 before the labels

LP-379 — Priya's judgment labels + full calibration re-run

170 rows, then the first valid measurement of the shipped prompt
Tests F1, F2, and LP-335's fix on real driver's licenses
Only after LP-378 confirms the tags materialize
  
LP-380 — Priya's activation bars

THEN — Activation

LP-381/382/383 — extraction: page counts · employment dates · LE/CD
LP-384 — declared recipe dependencies
LP-385 — per-borrower document context
LP-386 — IN-3 per-borrower · LP-387/388 — PIN #2, PIN #3
LP-389 — the activation pass: how many of the 21 go live?

THEN — Deferred shapes

LP-390 multi-value gather · LP-391 IN-6 · LP-392 AS-8 · LP-393 borrower-set reconciliation

THEN — Waves 4-10

DTI · Title · Insurance · Condo · small families (~3 tickets each)
Blocker extractors (credit report, DU/AUS, appraisal) + golden-file evals → Credit · Property

===============================


1. The income wave — what's actually in it
   It's both coding and Priya, in a specific order. The coding comes first, then her, then more coding.
   The work, in sequence:

Coding — the ~14 income/asset rules mostly exist (they're inert). But calibration revealed gaps: IN-10/IN-11 read per-document but the producer is per-borrower (a spec fix); IN-3 is misclassified; some tags aren't wired to their consumers. That's engineering, no Priya.
The worksheet + Priya — she labels the income tags that feed those rules (has_2yr_history, is_declining, same_line_of_work, continuance_3yr, has_identified_source, the widened apparent_category). That's her session — the thing you did a slice of with the 122 labels. Yes, you fill the sheet with her.
Coding again — calibrate against her labels, set activation bars (she signs off), activate the rules that clear their bar.

So: ~40% coding, ~20% her time, ~40% coding. Her part is a few labeling sessions, not continuous. And it's gated on her availability — which is exactly why I'd run it as a background lane, not a blocker.
What it unlocks: ~14 rules (IN-3, IN-7, IN-10, IN-11, IN-12, IN-13, AS-2, AS-4, AS-5, AS-6, AS-7, AS-11, AS-12) — the judgment-heavy income and asset checks. High value, because these are the real underwriting rules (bonus continuance, reserve eligibility, gift sourcing).
2. The deterministic waves — what's in them, how many rules
   "Deterministic wave" = a category dominated by structural/calculative rules (presence, count, match, arithmetic) that need little or no AI calibration — so they activate fast, like the 5 you just cleared. No Priya labeling.
   Your remaining categories, roughly:
   wavemostlyest. rulesAI-heavy?DTIcalculative (ratios, limits)~8-10Low — mostly arithmetic on parsed fieldsTitlestructural (presence, warrantable-condo)~8-12Low — presence/match checksInsurance/Hazardstructural + calculative~6-8Low-mediumCondostructural (warrantable vs non-warrantable)~6-10Medium — some questionnaire readingCreditmixed~10-15Blocked — needs the credit-report extractorProperty/Appraisalmixed~10-15Blocked — needs the appraisal extractor
   DTI and Title are your fastest wins — mostly deterministic, no calibration, activate like the 5 you just did. Each wave is ~3 tickets and lights up 8-12 rules. DTI + Title alone ≈ 20 rules, mostly without Priya.
   Credit and Property are the hard ones — they need the blocker-document extractors (credit report, DU/AUS, appraisal are PDF-only, no structured feed) and golden-file evals, because there's no independent source-of-truth to cross-check. Those are later, and they're genuinely harder.
3. High-level plan to all 130
   Here's the whole arc, in the order that maximizes coverage-per-effort:
   Phase A — Finish the cheap deterministic wins (now)
   Two lanes in parallel:

Engineering lane: DTI wave → Title wave. ~6 tickets, ~20 rules, mostly no Priya. This is your momentum.
Priya lane (background): income-wave labeling whenever she's free → calibrate → activate. ~14 rules. Runs alongside, doesn't block engineering.

End of Phase A: ~17 → ~50 rules (~40%).
Phase B — The remaining structural waves

Insurance/Hazard, Condo. ~6 tickets, ~15 rules. Condo needs the warrantable-vs-non-warrantable logic (some AI). Still mostly deterministic.

End of Phase B: ~50 → ~65 rules (~50%).
Phase C — The blocker extractors (the hard infrastructure)
This is the big one, and it's what stands between you and the last ~40 rules:

Build the credit-report extractor (nested tradelines, scores, inquiries)
Build the DU/AUS findings extractor
Build the appraisal extractor (UAD 2.6 + 3.6 layouts)
Build LP-143 golden-file evals alongside each — because these have no independent source-of-truth, so silent misreads have nothing to catch them. This is where the eval infrastructure matters most.
Build the §3B cash-to-close calculator (unblocks AS-3 and DTI depth)

This phase is mostly extractor + eval engineering, not rules. It's the foundation the last waves stand on.
End of Phase C: infrastructure done, ~65 rules still.
Phase D — Credit + Property waves

With extractors live, write and activate the Credit and Property/Appraisal rules. ~25-30 rules.

End of Phase D: ~65 → ~130 (~100%).
The honest shape of it

Phases A-B (structural waves): the bulk of the rule count, moves fast, low risk. ~50% of rules, maybe ~30% of the effort.
Phase C (extractors + evals): the smallest rule count but the biggest, riskiest engineering — the blocker documents with no cross-check. ~10% of rules, ~40% of the effort.
Phase D (Credit/Property): rides on Phase C. Fast once the extractors exist.

The critical insight: the last ~40 rules (Credit, Property) are gated on infrastructure you haven't built (extractors + evals), not on writing rules. So the plan isn't linear — it's "harvest the cheap structural rules now, then build the hard extractor infrastructure, then harvest the rest."



===============================

EPIC: LP-390 — Income Wave: Calibrate & Activate the Income/Asset Judgment Rules
Goal: Take the ~14 inert income/asset judgment rules (IN-3, IN-7, IN-10, IN-11, IN-12, IN-13, AS-2, AS-4, AS-5, AS-6, AS-7, AS-11, AS-12) from inert → calibrated → live, without shipping an uncalibrated AI tag into a trusted verdict.
Definition of Done: Every income-wave rule is either (a) live with a Priya-validated bar, or (b) explicitly held with a documented blocker (unmeasured tag / missing producer / data gap).
Dependencies: LP-385 (per-borrower producer), LP-379 chain (worksheet + calibration harness), LP-380 (activation bars), LP-389 (eligibility gate).
Blocked by: Priya's labeling availability (Stories 3+).

STORY LP-390-1 — Fix IN-10/IN-11 per-borrower consumption
Type: Story · Points: 3 · Priority: High · Depends on: LP-385, LP-389-A
Description: IN-10 (is_declining) and IN-11 (has_2yr_history) read their tags per-document, but LP-385 moved the producer to per-borrower. They read a subject with no tag → silent couldnt_check. Re-scope both to per-borrower, reusing LP-389-A's _borrower_attributed_documents primitive.
Acceptance criteria:

IN-10, IN-11 enumerate per borrower, read the borrower's attributed income tags
No second per-borrower mechanism (reuse LP-389-A's)
Per-borrower isolation asserted (no cross-borrower feed)
Fail-closed: no attributable income doc → couldnt_check with a reason
The 17 live rules identical; full suite green

Not in scope: Activating them (still uncalibrated); a per-rule branch (→ report).

STORY LP-390-2 — Audit income-rule tag→consumer wiring
Type: Story · Points: 2 · Priority: High · Depends on: LP-390-1
Description: Before spending Priya's time, confirm every income-wave rule's load-bearing tag actually reaches it (the ID-5 subject-mismatch / structural-dead class — five instances this session). Read-only audit; each rule traced spec → tag → producer → subject.
Acceptance criteria:

Per-rule table: rule → tag → producer subject → rule's read subject → match?
Any subject mismatch flagged as its own fix (don't fix here)
Any tag with no producer flagged (the IN-14 / occupancy.rental_support class)
Report which income rules are genuinely calibration-ready vs blocked on wiring/producer

Not in scope: Fixing what it finds (each = its own subtask).

STORY LP-390-3 — Finalize the income calibration worksheet
Type: Story · Points: 3 · Priority: High · Depends on: LP-390-2
Description: Get the sheet perfect before Priya labels, so her hours aren't wasted. Fold in the deferred worksheet findings.
Subtasks:

LP-390-3a — Fix the 2 id.address_normalized data-entry errors (names in address column)
LP-390-3b — has_identified_source worksheet-clarity: make it read as a distinct question (Priya skipped all as "already evaluated")
LP-390-3c — Resolve the held apparent_category rows from LP-379-F (generic-memo + NEEDS-PRIYA)
LP-390-3d — Regenerate: every materializing income tag has a labelable row at the right (per-borrower) granularity; all filled labels preserved

Acceptance criteria:

Every income judgment tag that materializes has a labelable row
No row targets a non-producing tag; no data-entry errors
has_identified_source distinguishable from apparent_category  
All prior filled labels preserved (count asserted)


STORY LP-390-4 — Priya labeling session (income tags)
Type: Story · Points: 5 · Priority: High · Depends on: LP-390-3 · Assignee: Priya (+ you)
Description: Priya labels the income judgment tags against the finalized sheet. Human-gated — the sheet must be complete first.
Tags to label: has_2yr_history, is_declining, same_line_of_work, continuance_3yr, has_identified_source, the NEEDS-PRIYA apparent_category rows.
Acceptance criteria:

Each income tag has ≥ a minimum n of labels (report the n per tag)
Uncertain calls captured as unknown, not forced
Her underwriting notes preserved (the flag-worthy findings)

Note: This is her time — schedule around availability. Blocks Stories 5-6.

STORY LP-390-5 — Calibrate income tags against Priya's labels
Type: Story · Points: 3 · Priority: High · Depends on: LP-390-4
Description: Score each income tag against her labels (the LP-334/LP-379-D harness). Report accuracy + failing cases + reasoning per tag.
Acceptance criteria:

Per-tag accuracy, n, and failing cases with the model's reasoning
Any prompt-bug finding (systematic miscategorization) flagged as its own fix
Tags split: calibration-passed / needs-prompt-fix / insufficient-n
Unmeasurable tags (data gaps like the widened categories) reported, not scored

Not in scope: Setting bars (LP-390-6); fixing a prompt bug (its own ticket).

STORY LP-390-6 — Propose & validate activation bars (income rules)
Type: Story · Points: 2 · Priority: High · Depends on: LP-390-5 · Assignee: you + Priya
Description: For each income rule, propose a bar from its tag's measured accuracy + FP/FN cost; Priya confirms (like IN-1/IN-5). Bars start validated: false; her sign-off flips them.
Acceptance criteria:

A bar per calibratable income rule, with rationale + FP/FN cost
Ratify-only flagged where error cost is too high to auto-ship
Priya's confirmed values recorded, validated: true
not-calibratable-yet rules explicitly excluded (not given a bar)


STORY LP-390-7 — Activate the income rules that clear their bar
Type: Story · Points: 3 · Priority: High · Depends on: LP-390-6
Description: Activate each income rule whose tag accuracy meets its validated bar, via the eligibility gate. Report the real verdicts on the fixture.
Acceptance criteria:

Eligibility table: which income rules pass, which held + why
Activated rules reach real verdicts (satisfied/open/needs_review) — reported, not predicted
Below-bar rules → needs_review (ratify), not auto (LP-376-B reconciliation)
New ACTIVE_RULE_IDS count reported; the 17 prior rules identical
Full suite green


STORY LP-390-8 — Resolve income-wave blockers (spun-off tickets)
Type: Story · Points: TBD · Priority: Medium · Depends on: LP-390-2, LP-390-5
Description: Container for blockers the wave surfaces that aren't calibration:
Subtasks (created as found):

IN-14 — build occupancy.rental_support producer (no producer today)
IN-3 — bar reclassification (LP-384 found it mislabeled no-AI)
AS-2 / AS-5 — widened-category data gap (redacted memos can't exercise loan_proceeds/gift — LP-379-F)
Any prompt-bug fix from LP-390-5
Any subject-mismatch fix from LP-390-2



===========
STORY LP-393-1 — Build the standalone income-scenario snapshot builder

Type: Story · Points: 5 · Priority: High · Depends on: LP-385, LP-390-1

Description: Create build_income_calibration_snapshot() — a standalone fixture with ~11 synthetic borrowers, each carrying the minimum document set its scenario needs. No bank statements, DLs, or MISMO beyond borrower identity unless a scenario requires it.

Scenarios — clear-cut (expected answer known):

id	scenario	tag exercised	expected
B3	2024 $80k → 2025 $60k, same employer	is_declining	yes
B4	2024 $60k → 2025 $75k, same employer	is_declining	no
B5	One W-2 (2025 only)	has_2yr_history	no
B6	2023 + 2024 + 2025 W-2s, same employer	has_2yr_history	yes
B7	Nurse (Hospital A) → Nurse (Hospital B)	same_line_of_work	yes
B8	Warehouse picker → Office administrator	same_line_of_work	no

Scenarios — ambiguous (built, NOT pre-answered; Priya labels blind):

id	scenario	the open question
B9	2024 $70k → 2025 $68.5k (−2%)	is a small drop "declining"?
B10	18 months of history (mid-2024 start)	does a partial 2nd year count?
B11	Retail cashier → Retail supervisor	promotion = same line of work?
B12	Base declined, bonus rose, total flat	is income declining?
B13	2 years across 2 different employers	2yr history of income, or does employer continuity matter?

Asset scenarios (for AS-11 liquidation_terms): regular brokerage, 401(k) with vesting, Roth IRA.

Acceptance criteria:

build_income_calibration_snapshot() exists in its own module; never imported by the LF-6T3N builders (assert)
Own loan id / borrower ids / content ids — no collision with LF-6T3N (assert)
Each borrower carries the minimum documents its scenario needs (no unnecessary docs)
income_stability + asset_facts materialize on it; each target tag reaches n≥6
LF-6T3N fixtures byte-unchanged; ACTIVE_RULE_IDS unchanged (20); full suite green

Not in scope: generating PDFs (Level 1 only); labeling; calibrating; activating.

STORY LP-393-2 — Generate the scenario worksheet for Priya

Type: Story · Points: 2 · Priority: High · Depends on: LP-393-1

Description: Generate a labeling worksheet from the scenario snapshot, reusing the LP-390-3 generator (SOURCE-TRACE prompts, source_document, orphan rows excluded, predictions excluded / anti-anchoring).

Acceptance criteria:

Every scenario borrower has a labelable row per target tag, at per-borrower granularity
Predictions excluded — the ambiguous cases must be labeled blind (no anchoring)
The clear-cut scenarios' expected answers are recorded separately (not in the sheet) so they can be checked without anchoring Priya
Committable — synthetic data, no PII, lives in docs/calibration/
Row counts per tag reported (the session agenda)
STORY LP-393-3 — Priya labels the scenario worksheet

Type: Story · Points: 3 · Priority: High · Depends on: LP-393-2 · Assignee: Priya (+ you)

Description: Priya labels all ~11 borrowers × 4 income tags + 3 asset accounts. The ambiguous cases (B9–B13) are the point — her labels become the definition for "declining," "2-year history," "same line of work."

Acceptance criteria:

Every scenario row labeled, or unknown where she genuinely can't tell
Her reasoning captured in notes on the ambiguous cases (that's the domain knowledge being encoded)
The clear-cut cases match expectation, or a mismatch is investigated (either the scenario is wrong or our assumption was)
STORY LP-393-4 — Calibrate the income + asset tags against the scenario labels

Type: Story · Points: 3 · Priority: High · Depends on: LP-393-3

Description: Score is_declining, has_2yr_history, same_line_of_work, continuance_3yr, liquidation_terms against Priya's scenario labels. Report accuracy + n + every disagreement with the AI's reasoning.

Acceptance criteria:

Per-tag accuracy at the new n (≥6), with per-scenario breakdown
Clear-cut vs ambiguous scored separately — clear-cut failures = a real bug; ambiguous disagreements = the interesting signal
Any prompt bug flagged as its own ticket
Explicitly stated: these are synthetic-scenario results — they measure reasoning, not robustness to real-document messiness (LF-6T3N covers that)
STORY LP-393-5 — Propose bars & activate what clears

Type: Story · Points: 3 · Priority: High · Depends on: LP-393-4 · Assignee: you + Priya

Description: Propose bars for IN-7/10/11/12/13 and AS-11 from the scenario calibration; Priya signs off; activate via the eligibility gate.

Acceptance criteria:

A bar per rule with rationale + FP/FN cost + the synthetic-data caveat (reasoning validated, robustness not)
Priya's confirmed values recorded, validated: true
Rules clearing their bar activate via the gate; below-bar → needs_review
New ACTIVE_RULE_IDS count reported; the 20 prior rules identical
STORY LP-393-6 — (Optional) Extend the pattern for future waves

Type: Story · Points: TBD · Priority: Low · Depends on: LP-393-1

Description: The scenario-fixture pattern is reusable. Document it so DTI, Condo, Credit, etc. each get their own standalone scenario snapshot rather than polluting LF-6T3N.

Acceptance criteria:

A short pattern doc: how to build a scenario fixture (standalone, minimal docs, own ids, never merged)
Noted as the template for future waves
Board summary
ticket	type	pts	gated on	lane
LP-393-1	Story	5	—	Eng
LP-393-2	Story	2	393-1	Eng
LP-393-3	Story	3	393-2	Priya
LP-393-4	Story	3	393-3	Eng
LP-393-5	Story	3	393-4	Priya
LP-393-6	Story	TBD	393-1	Eng (low)

Critical path: 1 → 2 → [Priya] 3 → 4 → [Priya] 5. Two human gates.

What it unblocks: IN-7, IN-10, IN-11, IN-12, IN-13, AS-11 — six rules, all currently stuck purely on sample size.

Start: LP-393-1 — pure engineering, no gates, and it's the reusable pattern for every future wave.
