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
