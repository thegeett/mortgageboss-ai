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

Stage 2 (rebuilt around the fact-tag architecture)
The old "130 AI evaluators" plan is replaced. New spine: build the tag storage + a thin slice (produce tags → thin deterministic rule → finding) end-to-end for AS-1, with the fail-closed armor, then scale.
Foundation
LP-310 — Recon + reconcile current state with the tag architecture

Report current state of load_rule_spec, rule_kinds.csv, the AS-1 spec (is the direction=="credit" filter still there?)
Report the post-LP-302a snapshot model shape (raw layer, transactions)
Confirm the real names/signatures of the 6 calculators
Report the finding model's current state (what LP-306 would need to build)
Flag anything that contradicts the tag-architecture design
Output: recon doc, no code

LP-311 — Rule + tag storage: files → DB projection

Define version-controlled file format for: rule specs (rule_id, kind, required_tags, applicability, reference_values, confidence_floor) and the tag vocabulary (tag_id, entity, type, allowed_values, depends_on, tag_role)
Build DB tables: rules, tags, rule_tags, tag_dependencies (+ Alembic migration)
Build the loader: reads files → upserts tables (the sync); DB is a projection, never hand-edited
Consistency checks: every tag a rule requires exists in the vocabulary; depends_on forms a valid DAG (no cycles)
Port LP-301's classification + LP-303's AS-1 spec into the new file+DB format
ADR: files-as-source-of-truth + DB-projection; the table schema

The tag layer (the new core)
LP-312 — The tag object model + snapshot two-layer shape

Define the frozen tag object: {value, confidence, reasoning, source_facts, produced_by, tag_role, tag_version, stage}
Extend the snapshot to two layers: raw (existing) + tags; tags cite raw facts by stable content-id, never array position
unknown in every tag's value domain; absent≠unknown distinction preserved
Snapshot_version bump; round-trip lossless; frozen (tags produced once, never re-derived on load); record model + vocab version
ADR: the two-layer snapshot, the tag object contract

LP-313 — Tag production: Stage A (per-entity atomic tags) for transactions

The tag-production prompt (shared "honest structuring" spine + Stage A body) — reuse the AI-call machinery (complete(), truncation guard, honest-parse, Reasoner test seam)
Produce transaction atomic tags: txn.is_money_in, txn.amount, txn.apparent_category — no direction== filter anywhere (the AI resolves label variance into is_money_in)
Bounded batches (≤15-20 items/call); unknown mandated; each tag carries provenance
Keyless tests via stub reasoner; produce tags for LF-6T3N transactions
ADR: the structuring prompt, batching bound

LP-314 — Tag production: Stage B (cross-entity correlation) + candidate-then-judge

Deterministic candidate-search (matching amount/date across accounts) → AI judges the small candidate set
Produce txn.has_identified_source for LF-6T3N deposits (the AS-1-critical correlation tag)
Tag dependency DAG: Stage B runs after Stage A; confidence propagates along the DAG (a tag no more confident than its shakiest input)
Contradiction audit (deterministic): statement balance reconciles to transaction sum
ADR: candidate-then-judge pattern, DAG ordering, confidence propagation

The rule engine + fail-closed
LP-315 — Thin deterministic rule engine + fail-closed gate (AS-1)

AS-1 becomes a thin deterministic rule: query is_money_in + amount + has_identified_source + threshold (from spec) → verdict. No AI in the rule itself.
The fail-closed gate: required-tag absent → couldn't-check; load-bearing tag unknown → couldn't-check; below confidence floor → needs-review; contradiction → needs-review; only present+high-confidence+non-contradictory → satisfied/fired
verdict_confidence = min(load-bearing tag confidence)
Test the AS-1 fraud case: the $40k "transfer" (no source) fires; a sourced deposit doesn't; a low-confidence source → needs-review
ADR: the rule engine, the fail-closed gate

LP-316 — Finding output: four states + provenance propagation + subject_key

Finding carries its load-bearing tags inline (reasoning + confidence) — provenance tag→finding
Four states (open/satisfied/no-longer-applies/couldn't-check); subject_key from stable tag values (per-deposit for AS-1)
Extend/build the finding model (per LP-310 recon)
Test: AS-1 fires per-deposit; each finding shows the tags it rests on
ADR: finding shape, subject_key stability

LP-317 — Golden eval harness: tag-level AND finding-level

Golden labels on tags (is_money_in, has_identified_source) — catch a systematically-wrong tag upstream
Golden labels on findings (AS-1 verdict) — end-to-end
Measure calibration: unknown rate + accuracy-when-concrete (over/under-abstention)
Regression cases: the transfer-labeled $40k deposit (the original bug); a gift-letter-resolved deposit
ADR: eval design, calibration metrics

Prove across kinds + the unbounded world
LP-318 — Calculators as structured tags (all 6)

Each calculator → {value, breakdown[]} where each line carries source + from_tag
Confidence propagates through the calc; a line tracing to an unknown tag → calc gated → couldn't-check
Use the real 6 calculators (from LP-310 recon)

LP-319 — AI-at-rule-time rules (the judgment slice, e.g. OC-2)

Pure-AI rules reason over tags (not raw docs); mandatory human ratification; confidence-gated
One judgment rule end-to-end (occupancy reasonableness) — proves the ~36 judgment rules' safety pattern

LP-320 — Observation channel + graduation

Structured observation envelope (about/type/value/structured/relates_to/confidence/needs_tag) for documents/facts not in the vocabulary
Fails closed to human review when related to a finding
Graduation log (frequency tally of recurring observation types)
Test: a gift letter (not yet a formal tag) → observation → surfaces to human; a known doc → tags

Orchestration + scale
LP-321 — Orchestrator + partial-snapshot semantics

Run: raw snapshot → Stage A tags → Stage B tags → calculators → contradiction audit → rules → findings
Partial-snapshot: a failed tag-production call → those tags absent-with-reason → dependent rules couldn't-check → other rules still run (graceful degradation)
Cache: unchanged raw facts → reuse tags (content-id fingerprint)

LP-322 — Finding reconciliation across runs

Match findings by stable subject_key across runs; open→satisfied when a resolving tag flips (the gift-letter loop); retire → no-longer-needed
Ties to snapshot persistence + the four-tab surface

LP-323+ — Tag + rule waves by category

Author remaining tags + thin rules in category batches (identity → income → assets → credit → property…), each wave validated against the eval harness, thresholds Priya-signed before ship


Dependency spine: LP-310 (recon) → 311 (storage) → 312 (tag model) → 313 (Stage A) → 314 (Stage B) → 315 (rule engine + fail-closed) → 316 (findings) → 317 (eval) → go/no-go → 318 (calculators), 319 (judgment rules), 320 (observations) → 321 (orchestrator), 322 (reconciliation) → 323+ (waves).
The go/no-go is after LP-317 — at that point you have AS-1 fully working the new way (tags produced → thin rule → finding → eval'd, with the fail-closed armor) on LF-6T3N, and you know whether the tag architecture delivers before scaling.

So to answer your question directly: from Claude Code I need the LP-310 recon (current state of the spec/rule_kinds/snapshot/finding models + the real 6 calculator names) before writing the detailed build prompts — because the tickets should target real interfaces, not my memory of them from before your vacation. The ticket plan above is solid without it; the per-ticket Claude Code prompts want the recon first.
Want me to write the LP-310 recon prompt now (so you can run it and confirm the current state), or start drafting the detailed build prompts for the early tickets from what we already know?give me claude code prompt for your questions.Here's the Claude Code prompt for LP-310 — the recon that confirms current state before we write the tag-architecture build tickets. It's read-only, so it's safe to run with auto-approval; the deliverable is a report.Implement LP-310 — Recon: reconcile current branch state with the fact-tag architecture.
READ-ONLY. This surveys what's actually on the branch now (after LP-301, LP-302a, LP-303)
so the upcoming tag-architecture tickets build on reality, not stale assumptions. Write NO
code and make NO changes — the ONLY deliverable is docs/tickets/LP-310.md.

READ-ONLY: no writing, editing, refactoring, deleting, migrations, or DB mutations. Use only
read commands (git log/show, ls, cat, grep, find, pytest --collect-only). The one file you
create is the report.

## CONTEXT (why this recon)
The project is pivoting Stage 2 from "130 AI rule-evaluators" to a FACT-TAG architecture:
AI structures raw facts into clean tags in the snapshot; deterministic code queries the tags
+ does arithmetic. Before writing the tag-layer tickets I need an accurate picture of what
  LP-301/302a/303 left on the branch and what the tag layer must build on. Reference (if
  present in the repo): /docs/verification-architecture-v2.docx §3D (the fact-tag architecture)
  and /docs/snapshot-fact-tags.* (the tag vocabulary).

## WHAT TO INVESTIGATE — report each with file:line, and reuse/extend/build-new verdict.

### 1. Rule spec + kinds infrastructure (LP-301, LP-303)
- load_rule_spec: signature, what a RuleSpec object contains, where specs live on disk.
- rule_kinds.csv + its loader (kinds.py): schema, the fields per rule (kind, numeric_check,
  exact_match,
