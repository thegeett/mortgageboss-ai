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
