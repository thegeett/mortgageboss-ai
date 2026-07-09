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
