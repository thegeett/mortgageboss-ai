Prerequisites (build first)
LP-201 — Per-field extraction confidence

Audit each existing document extractor to see what confidence signal (if any) the underlying model/parse already returns per field
Extend the extraction output schema to carry an optional per-field confidence (nullable) alongside each extracted value
Wire extractors to populate it where the model provides a usable signal; leave null (with confidence_source: "not_provided") where it genuinely doesn't — never fabricate a number
Persist confidence in the extracted-facts storage (schema/migration for wherever extracted facts live)
Backfill is not required; older extractions carry null
Tests: an extractor that emits confidence stores it; one that doesn't stores null; no fabricated defaults appear
Out of scope: changing extraction accuracy or adding new extractors — only threading confidence through

LP-202 — Document→borrower name field + link

Confirm (from LP-201's audit or fresh) which document types extract a borrower/employee name; add name extraction where a document clearly asserts one but it isn't captured today
Add a deterministic document→borrower matcher: match the document's asserted name against the loan file's borrower list (normalized/fuzzy), producing a link with confidence + method provenance
Add storage for the link: a document_borrower_links table (document_id, borrower_id, confidence, method), joint-document capable (a doc can link to >1 borrower)
Handle the no-match / no-name case explicitly (link absent, not errored)
Tests: single-borrower doc links correctly; joint doc links to both; a document with no name produces no link; a name that matches no borrower produces no link
Out of scope: AI-based matching (deterministic only); resolving conflicts between docs

Stage 1 core (build after prerequisites)
LP-203 — Field-shape primitives + PII handling

Define the Field shape: { value, confidence (nullable), source }, source ∈ {parsed, extracted}
Define the PiiField shape: { display (last-4 masked), match_hash, confidence, source } — raw full value never stored
Implement mask() (last-4 for SSN/account) and a per-loan-file-salted hash() for match_hash
Document the salt derivation (loan_file_id-based) so the same SSN across two files doesn't collide
Tests: masking formats correctly; same value + same file → same hash; same value + different file → different hash; no raw PII survives into the field
Out of scope: deciding which fields are PII (that's per-assembler) — this is just the primitives

LP-204 — Snapshot model (frozen, three sections)

Define the frozen Pydantic v2 models (frozen: True) for the snapshot
Three sections: mismo (dict of key→Field/PiiField), documents (list of {documentType, belongsTo (nullable), fields}), calculations ({dti, ltv, mi, reserves}, each {value, breakdown})
Top-level: loan_file_id, run_id, created_at, snapshot_version
Encode absent ≠ empty (a field no source supplied is omitted/marked absent, not blank/zero)
No linking/reconciliation fields — the model structurally can't correlate across sections
Tests: model is immutable (mutation raises); serializes to and round-trips from JSON; absent vs empty distinguishable
Out of scope: populating it — that's the assemblers

LP-205 — MISMO section assembler

Read the parsed MISMO data (LoanFile / Property / Borrower / StatedIncomeItem / StatedLiability / StatedAsset etc.) from the existing import output
Flatten into key → Field/PiiField pairs (e.g. borrower.1.income.base_monthly)
Apply PII treatment to SSN and account-number fields (mask + hash via LP-203)
All MISMO fields carry source: parsed; confidence typically null (deterministic parse)
Tests against LF-6T3N: expected borrower/income/liability/asset/transaction keys present; SSN/account masked with a hash and no raw value
Out of scope: any value the MISMO parse doesn't produce; no re-parsing

LP-206 — Documents section assembler

For each processed document on the loan file, emit {documentType, belongsTo, fields}
belongsTo = the resolved borrower (from LP-202's link) if present, else the raw asserted name, else null — (decide with the team: resolved link vs raw name; LP-202 makes the resolved link available)
Map each extracted field into the Field shape, carrying LP-201's confidence (nullable), source: extracted; PII fields masked+hashed
Tests against LF-6T3N: each document appears with its type; belongsTo populated where a name/link exists and null where not; extracted fields carry confidence (or null); PII masked
Out of scope: cross-document correlation; reconciling a document's values against MISMO

LP-207 — Calculations section assembler

Call the four existing calculators (build_dti_calculation, build_ltv_calculation, compute_loan_mi, build_reserves_view) — do not reimplement any math
Map each returned breakdown into the snapshot's calculations shape, preserving each line's existing source tag (stated/extracted/computed/manual)
Surface value + full breakdown per calculation
Tests against LF-6T3N: dti/ltv/mi/reserves present with values and breakdowns; per-line source tags preserved
Out of scope: cash-to-close (explicitly deferred); any new calculation; resolving disagreeing inputs

LP-208 — Snapshot builder / orchestrator

build_snapshot(loan_file_id, run_id) -> Snapshot: invoke the three assemblers, assemble the frozen model, return it
Stateless — rebuilt from scratch each call, no caching, no mutation
Handle a loan file missing a section gracefully (e.g. no documents yet → empty documents list, not an error)
Tests: full build against LF-6T3N produces a complete three-section snapshot; missing-section cases degrade cleanly
Out of scope: persistence (next ticket); triggering

LP-209 — Snapshot persistence (immutable, per run)

New table + Alembic migration: { run_id (unique), loan_file_id, created_at, snapshot_version, snapshot_json }
persist_snapshot(snapshot) write path — insert only, immutable, never UPDATE
Store the full snapshot as a single JSON blob
load_snapshot(run_id) read-back path
Tests against LF-6T3N: build → persist → load round-trips to an identical snapshot; a second run creates a new row without touching the first
Out of scope: the viewer; history/time-travel UI; dedup or diffing

LP-210 — End-to-end Stage 1 test + real-file validation

A script/test that runs the full chain for LF-6T3N: build_snapshot → persist → load → print JSON
Assertions: all three sections present; PII masked with hashes and no raw values; belongsTo null where no name; calculation breakdowns carry source tags; confidence null (not fabricated) where extractor gave none
Produce the actual LF-6T3N snapshot JSON for human eyeball review
Document assumptions/decisions in docs/tickets/LP-210.md
Out of scope: viewer, automated eval set, other loan files

Dependency map
LP-201 (confidence) ─┐
LP-202 (doc→borrower)─┤
├─► LP-206 (documents assembler)
LP-203 (primitives) ─┼─► LP-205 (mismo assembler)
│
LP-204 (model) ──────┼─► LP-205, LP-206, LP-207
│
LP-207 (calc) ───────┤
▼
LP-208 (builder) ─► LP-209 (persist) ─► LP-210 (e2e)
Buildable order: LP-201, LP-202 (prereqs, parallelizable) → LP-203, LP-204 (foundations, parallelizable) → LP-205, LP-206, LP-207 (assemblers, parallelizable once foundations land) → LP-208 → LP-209 → LP-210.



Stage 2 — Jira tickets (LP-3xx)
Foundation
LP-301 — Rule-kind classification: formalize + Priya-validate

Import stage2-rule-classification.xlsx into the repo as the canonical, version-controlled rule-kind reference
Encode as machine-readable data (checked-in file): rule_id → kind (calculative/structural/judgmental/out-of-scope), evaluation_path, numeric_check flag, exact_match flag (for structural)
Priya-validation pass: confirm kind tags; confirm which structural rules are exact-match (deterministic-only) vs fuzzy (AI)
Mark every calculative rule's threshold/window/limit as "needs Priya sign-off before ship"
ADR: the three-evaluation-path model + deterministic-bookend-for-calculative decision
Reference docs: architecture §3C, classification xlsx
Out of scope: any spec or evaluator code

LP-302 — Stage 2 codebase recon (read-only)

Locate the AI/Anthropic call layer (prompt construction, call, response parse) — the evaluator builds on it
Locate the finding model (states, identity, persistence) — confirm vs the four-state model needs
Locate the existing deterministic calculators (DTI/LTV/reserves/MI) — these become the numeric-bookend verifiers
Confirm snapshot load path (LP-208/209) — the evaluator's input
Report reusable-vs-build-new for: spec storage, evaluator, numeric bookend, finding output, eval harness
Reference docs: architecture §3C
Out of scope: any building

Phase A — Vertical slice (AS-1, calculative)
LP-303 — AS-1 rule spec + load_rule_spec interface

Write the AS-1 spec as a version-controlled file (discover the shape from this one real rule)
Fields: criteria, applicability (scope+trigger), required_inputs, kind=calculative, reference_values (large-deposit threshold = 50% of monthly qualifying income, Priya-validated), evidence_required, guideline_reference, subject enumeration (per-deposit), spec_version
Build the load_rule_spec(rule_id) interface (file-backed now; swappable to DB later)
ADR: spec-as-file + load-interface decision; note format is provisional until LP-308 generalizes
Reference docs: prompt-set md (spine's spec slots show what a spec must carry), architecture §3C
Out of scope: generalizing the format, other rules, DB table

LP-304 — Per-rule AI evaluator: spine + calculative body (AS-1)

Build the shared prompt spine (role, honesty rules, applicability three-valued logic, JSON output contract) — use the exact text from stage2-evaluator-prompts.md, verbatim
Build the calculative body (Variant 2) — verbatim from the prompt-set doc
Assemble prompt at runtime: spine + calculative body + injected AS-1 spec + snapshot
One AI call → applicability (yes/no/can't-tell) + verdict + operative_values + evidence + reasoning, parsed to the JSON contract
Honest can't-tell → couldn't-check; never fabricate verdict/applicability/value
Test against LF-6T3N: AS-1 surfaces deposits, evaluates each, surfaces operands X/Y
ADR: the evaluator output contract (becomes the contract for all rules)
Reference docs: prompt-set md (spine + Variant 2 — use verbatim), architecture §3C
Out of scope: numeric bookend (next), other variants, orchestration

LP-305 — Numeric-integrity bookend (AS-1 calculative)

Deterministic pre-compute: the AS-1 threshold (50% of qualifying income), fed into the prompt as precomputed_values
Deterministic re-verify: re-run the final deposit-vs-threshold comparison on the AI's surfaced operands
Disagreement handling: arithmetic slip → deterministic silently corrects; input-selection difference → surface to human, never auto-override the AI
Reuse existing calculator where one exists (per LP-302 recon)
Test: an AI arithmetic error is caught; an input-judgment difference is surfaced not overridden
ADR: bookend structure (pre-compute + verify) + two-kinds-of-disagreement rule
Reference docs: architecture §3C (bookend), prompt-set md (Variant 2)
Out of scope: non-calculative rules

LP-306 — Finding output + four-state shape (AS-1)

Evaluator result → durable finding: identity (rule_id, subject_key), four states (open/satisfied/no-longer-applies/couldn't-check)
subject_key for AS-1 = per-deposit (account + date + amount) — exercises subject enumeration
Route to the four surfaces (needs-attention / satisfied / not-applicable); no-longer-needed empty on single run
Reuse/extend existing finding model (per LP-302)
Test: AS-1 fires per-deposit on unsourced deposits; each a distinct finding with a stable subject_key
ADR: subject_key derivation for per-subject rules
Reference docs: architecture §8-9 (finding lifecycle)
Out of scope: cross-run reconciliation (Phase C)

LP-307 — Golden-file eval harness (AS-1)

Build the harness: labeled expected outcomes for AS-1 against real files (LF-6T3N + one where AS-1 fires + one satisfied/not-applicable)
Covers BOTH the finding verdict AND the applicability decision
Runs automatically; per-case pass/fail; flags regressions
Test: harness correctly scores the AS-1 evaluator against known labels
ADR: eval-harness design + labeling approach
Reference docs: architecture §3C (eval harness), §12 (probabilistic-reproducibility risk)
Out of scope: scaling the eval set to many rules

LP-308 — Generalize the spec format (from AS-1's learnings)

Generalize the minimal AS-1 spec into the real spec format (now informed by what the evaluator actually needed)
Formalize all fields; define the file format
Round-trip: AS-1 re-expressed in the general format evaluates identically
ADR: the finalized rule-spec format (contract for all 130 rules)
Reference docs: prompt-set md, architecture §3C
Out of scope: authoring other specs

Phase B — Prove the pattern across kinds (→ go/no-go)
LP-309 — Structural slice: fuzzy + exact (e.g. ID-5 + ID-2)

Express a structural rule in the general spec format (ID-5 ID-expiration — date compare)
Build the structural path: deterministic check; AI only for fuzzy (Variant 3, verbatim from prompt-set doc)
Add an exact-match rule (ID-2 SSN) proving the deterministic-only, no-AI path
Extend the eval harness with these cases
Test against LF-6T3N (ID-5 fires — Akash's DL is expired; concrete validation)
ADR: the structural path (deterministic-only vs AI-fuzzy split)
Reference docs: prompt-set md (Variant 3 + no-AI paths — verbatim), classification xlsx
Out of scope: judgmental rules, orchestration

LP-310 — Judgmental slice (e.g. OC-2 or DT-6) — GO/NO-GO

Express a judgmental rule in the spec format (OC-2 occupancy reasonableness, or DT-6 retained-property)
Build the pure-AI path (Variant 1, verbatim): no numeric check, human ratifies, reasoning + evidence exposed
Extend the eval harness
Test against LF-6T3N (retained-property signal is present — real judgmental case)
Milestone: all three kinds proven end-to-end with eval scores → decide whether to scale
ADR: the judgmental path
Reference docs: prompt-set md (Variant 1 — verbatim), classification xlsx
Out of scope: orchestration, scaling

Phase C — Orchestration, discovery, reconciliation (after go/no-go)
LP-311 — Rule orchestrator

Run all applicable rules over a snapshot; route each by kind (static-filter out-of-scope → exact-match deterministic → AI variants → bookend for calculative)
Assemble findings from all rules into the four surfaces
Cache-serve unchanged re-runs (input fingerprint)
Test: full run over LF-6T3N across the built rules produces the four-tab result
ADR: orchestration + routing + caching
Reference docs: architecture §3C, §4 (run trigger)

LP-312 — Cross-source discovery lane (FR-6)

Whole-file, no-fixed-scope AI pass, runs last
Matches an existing rule → feeds it as evidence; novel → "AI found — verify" finding; recurring → flag for graduation to a scoped rule
Test against LF-6T3N (should surface the retained-property / address class of discrepancy)
ADR: discovery-lane design + graduation loop
Reference docs: architecture §7 (cross-source lane)

LP-313 — Finding reconciliation across runs

Match findings across runs by identity; carry-forward / mint-new / retire
Four states with the no-longer-needed retirement; append-only event log; immortality guarantee
Persisted four-tab surface with jump-back (ties to LP-209 snapshot persistence)
Test: two runs with a changed file reconcile correctly; a removed subject retires
ADR: reconciliation + subject_key stability + retire/revive rules
Reference docs: architecture §8-9

Phase D — Scale
LP-314+ — Rule-family waves

Author remaining ~125 specs in category batches (identity → income → assets → credit → property → …)
Each wave: write specs, add eval-set labels, validate against the harness before the next wave
Priya sign-off on each wave's thresholds before ship
Reference docs: all three
One ticket per wave/family (LP-314 identity, LP-315 income, …)
