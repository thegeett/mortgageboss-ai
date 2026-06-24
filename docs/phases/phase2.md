Infrastructure & Tiering
LP-58 — Three-Tier Document Model: Foundation & Routing
The tier mechanism that everything else hangs on.

Introduce the tier concept (Tier 1 first-class / Tier 2 recognized / Tier 3 long-tail) as a property of a document type, on top of the existing EXTRACTORS registry and classification pipeline
A tier registry / type catalog: maps each known document type → its tier + category; the classifier and pipeline consult it to route (Tier 1 → extract via registry; Tier 2 → classify + summarize only; Tier 3 → generic analyzer)
Extend the pipeline routing (process_document): after classification, branch by tier (reuse the existing EXTRACTORS registry for Tier 1; new paths for Tier 2/3 in later tickets — stub cleanly here)
The document categories enum/structure (Assets, Income/Employment, Property, Credit, Disclosures, Borrower Info, Misc) — flexible, refine-with-Priya
Backend only; migrations if the document model needs a tier/category field; tenant-scoped; tests for the routing-by-tier
Produces docs/tickets/LP-58.md + ADRs

LP-59 — Comprehensive Classification (all ~80 types → type + category + confidence)
Expand the Haiku classifier from 3 types to the full taxonomy.

A comprehensive classification prompt knowing all ~80 document types and their distinguishing indicators, assigning each to a category and a tier
Confidence scoring; low-confidence classifications flagged for processor review (reuse the NEEDS_REVIEW pattern)
The ~80-type taxonomy as a maintainable catalog (starter list from industry-standard mortgage docs; refine with Priya — explicitly marked)
Returns type + category + tier + confidence; routes per LP-58
Backend only; uses the existing AI classify wrapper; tests against a spread of type examples; metadata-only logging
Produces docs/tickets/LP-59.md + ADRs


Tier 1 — First-Class Extraction (the ~18 types)
Each batch ticket applies the established pattern (typed core + catch-all + source location + registry entry + validation + tests against sample docs) to a cluster of related types. The 3 existing types (pay stub, W-2, bank statement) are already Tier 1.
LP-60 — Tier 1 Income/Employment Documents
The income-verification cluster.

Extractors for: 1099 (and subtypes), Verification of Employment (VOE), Profit & Loss statement, Letter of Explanation (income/employment variants)
Each: typed core (the fields Phase 3 income verification needs) + catch-all + source location + validation + EXTRACTORS-registry entry
Reuse the LP-39a shape exactly; tests against sample docs (real/redacted or synthetic) asserting extraction accuracy
Backend only; refine the field sets with Priya
Produces docs/tickets/LP-60.md + ADRs

LP-61 — Tier 1 Asset Documents
The asset/reserves cluster.

Extractors for: investment account statement, retirement account statement, gift letter (+ proof-of-funds where applicable)
Same pattern (typed core + catch-all + source + validation + registry); typed cores shaped for Phase 3 asset/reserves cross-checks
Bank statement already exists (Tier 1) — reference, don't rebuild
Tests against samples; backend only; refine with Priya
Produces docs/tickets/LP-61.md + ADRs

LP-62 — Tier 1 Property Documents
The property cluster.

Extractors for: purchase agreement, homeowner's insurance binder/declaration, mortgage statement (existing properties), property tax bill, HOA statement
Same pattern; typed cores shaped for Phase 3 property/LTV and existing-obligation cross-checks
Tests against samples; backend only; refine with Priya
Produces docs/tickets/LP-62.md + ADRs

LP-63 — Tier 1 Borrower-Info & Legal Documents
The identity/legal cluster.

Extractors for: driver's license / government ID (with the SSN/PII discipline — encrypted/masked where any sensitive identifiers are captured), divorce decree, generic Letter of Explanation (the general variant)
The divorce decree is notable: its typed core + findings feed the Phase 3 undisclosed-obligation cross-check (capture the obligations it states)
Same pattern; careful PII handling (ID documents); tests against samples; backend only; refine with Priya
Produces docs/tickets/LP-63.md + ADRs

LP-64 — Tier 1 Tax Returns (carved-out, complex)
The most complex extraction in the product — its own focused ticket.

Extractor for tax returns: Form 1040 + schedules (Schedule C, Schedule E, K-1, etc.) — multiple nested schedules, the hardest extraction
Typed core capturing the income-relevant figures Phase 3 needs (AGI, wages, business income, the schedule breakdowns); catch-all for the rest; source locations per figure
Handle the multi-schedule structure (a return is several sub-documents); validation; registry entry
Generous extraction budget; tests against sample returns (redacted/synthetic) — including a self-employed return with Schedule C
Backend only; refine the captured fields with Priya (which tax figures she actually uses)
Produces docs/tickets/LP-64.md + ADRs


Tier 2 & Tier 3
LP-65 — Tier 2: Recognized Documents (classify + categorize + summary)
The broad "recognize and file, don't deep-extract" layer.

For Tier 2 types: store the classification + category + metadata (filename, type, date if cheaply available) and a 1–2 sentence AI summary for processor reference — no deep field extraction
The pipeline routes Tier 2 → summarize-only (a light AI summary call, not the full extractor)
Tier 2 docs appear in the Documents tab + are package-eligible (groundwork)
Backend (the summary path) + the detail view shows the summary (ties to LP-69); tests; metadata-only logging
Produces docs/tickets/LP-65.md + ADRs

LP-66 — Tier 3: Generic Analyzer + Findings
The long-tail "understand anything" analyzer.

A single generic analyzer for documents not in the known taxonomy → structured-but-flexible output: document_type_guess, key_parties, key_dates, key_amounts (with context), key_findings, summary
Findings are visible (per the locked decision) in the detail view and recorded as structured data for Phase 3
Full text indexed for search (stored)
The pipeline routes Tier 3 → generic analyzer; tenant-scoped; tests against novel/unusual documents (graceful on anything)
Backend only (the display is LP-69); metadata-only logging
Produces docs/tickets/LP-66.md + ADRs

LP-67 — Implications Engine (surface findings → suggest needs)
Turning findings into actionable suggestions (surface, not act).

Parse Tier 3/Tier 1 findings for action triggers; surface + suggest (not auto-act): e.g. a court order's payment obligation → suggest a "payment history" need; a LOE mentioning an income gap → suggest a VOE need
Suggestions feed the needs list (LP-68) as proposed items the processor confirms — never silent financial changes (that's Phase 3)
Findings → suggested-needs mapping; recorded with reasoning (explainable)
Backend only; tests (a finding produces a suggested need with its rationale); refine with Priya
Produces docs/tickets/LP-67.md + ADRs


The Needs List (the differentiator) — AI-reasoned
LP-68 — Needs-List Engine: Models, States & Per-File Serialization
The deterministic backbone of the needs list (no AI yet — the mechanism).

The NeedsItem model + states (Pending / Received / Verified / Rejected / Waived), tenant-scoped via the file; satisfaction linkage (a document satisfies a need)
Auto-update mechanics: a document arrives → matching need Received → after extraction passes → Verified; a rejected/expired doc → Rejected; processor can Waive (with reason)
PER-FILE SERIALIZATION (the race-condition fix): needs updates queued via Celery, serialized per loan file (per-file lock or per-file task chain) so near-simultaneous document arrivals don't corrupt the shared needs state
A thin deterministic floor of near-certain needs (employment income → pay stubs/W-2; purchase → purchase agreement) as the reliable baseline
Backend only; migrations; tenant-isolation tests; a concurrency test (two docs arriving together don't race)
Produces docs/tickets/LP-68.md + ADRs

LP-69 — AI Needs Reasoning: Propose-with-Reasoning + Confirm + Improve
The AI brain of the needs list (the headline capability).

AI reasons over the full file context (stated MISMO data + documents present + findings) to propose what the file needs — case-by-case, like a processor
Explainability: every proposed need carries its reasoning ("Needs tax returns BECAUSE self-employment income from CHHOTALA REALTY LLC") — stored + displayed
Processor confirmation: AI proposes → processor reviews/adds/removes/waives (human-in-the-loop); proposals are never silently authoritative
Improves from corrections: processor adjustments recorded as signal to sharpen future proposals (the mechanism for learning; the loop, even if simple in V1)
Seeded by MISMO at file creation (smart-needs-from-MISMO, the deferred LP-58-concept now landing here) + re-proposed as documents/findings arrive (serialized per LP-68)
Backend (AI reasoning) + the proposals surface in the UI (LP-70); cost/latency/eval noted; tests (the reasoning produces explainable proposals; confirmation flow); refine with Priya + via use
Produces docs/tickets/LP-69.md + ADRs

LP-70 — Needs-List Frontend (the processor's dashboard)
Where the needs list becomes the processor's daily driver.

The needs-list UI on the file: outstanding vs. satisfied at a glance; each need's state, the AI reasoning ("why is this here"), and confirm/add/remove/waive controls
The "upload the file → a tailored checklist appears" payoff (from MISMO-seeded proposals); live updates as documents arrive (reflecting the serialized backend updates)
Confirmation UX (accept/adjust AI proposals); waive-with-reason; rejected-need visibility
Frontend (frontend-design skill); reuse LP-46/47 error/loading; tests; manual verification
Produces docs/tickets/LP-70.md + ADRs


Versioning, Staleness & Detail
  LP-71 — Document Versioning + AI Staleness Detection
Replace (Model C) + the staleness-warning capability.

Model C replace: new docs upload normally (multiples are normal — no replace assumption); explicit replace of a specific document (old → historical, new → current, both kept for audit, the need re-evaluates against current); gentle duplicate/replacement surfacing (informational); email-ingested → new + "possible duplicate" flag
AI staleness detection: flag stale documents using the extracted date + recency windows (pay stub ~30d, bank statement ~60d, ID not expired) + "a newer version exists" — warn the processor so stale docs don't reach the package; processor resolves (replace/waive/accept); auto-resolution → V2
Version-history UI ("v2 of 2"); staleness warnings in the document list/detail
Full-stack (versioning backend + staleness logic + UI); tenant-scoped; tests; refine recency windows with Priya
Produces docs/tickets/LP-71.md + ADRs

LP-72 — Document Detail Extensions + Standard Naming (package groundwork)
Tier-aware detail view + the lender-package groundwork.

Tier-aware detail view (extend the LP-43 drawer): Tier 1 → full extraction (fields, confidence, source, transactions); Tier 2 → classification + summary; Tier 3 → the generic analyzer output (parties/dates/amounts/findings/summary) + implications; version history; actions (re-extract, reclassify, edit, download)
Standard document naming (groundwork, applied in Phase 6): generate + store a meaningful name derived from extracted data — NO SPACES (hyphens/underscores): Bank-Statement_Bank-of-America_2026-03-to-2026-05.pdf, Pay-Stub_Employer_2026-05-15.pdf, W-2_Employer_2025.pdf
Package-qualification groundwork: a document's current/historical + qualified/included + needs-satisfaction status (the data Phase 6 assembles from)
Full-stack (the naming/qualification backend + the detail UI); frontend-design skill; tests; manual verification
Produces docs/tickets/LP-72.md + ADRs


Phase 2 Consolidation
LP-73 — Phase 2 Testing, Polish & Hardening
The Epic-6-style close (mirrors LP-45/LP-57).

Full-flow integration tests: upload various document types → correct tier routing → Tier 1 extracts / Tier 2 summarizes / Tier 3 analyzes → needs list updates (serialized) → versioning/staleness → detail view
Tenant-isolation pass across all new endpoints (needs list, findings, versioning, detail) → 404 cross-company
Hardening against a variety of real documents (re-supply real/redacted samples — the classification of ~80 types, Tier 1 accuracy, generic analyzer graceful on novel docs); honest about what was tested
Needs-list concurrency hardening (the serialization holds under real batch arrivals)
Polish (the document/needs/detail states, LP-46/47 patterns); seed-data update (varied documents + a needs list); Phase 2 docs + deferred items (auto-staleness-resolution → V2; package assembly → Phase 6; ongoing Priya refinement of taxonomy/Tier-1-fields/needs-reasoning)
Mixed; tests pass; closes Phase 2
Produces docs/tickets/LP-73.md + ADRs


Summary Table
TicketTitleCoreLP-58Three-Tier Model: Foundation & RoutingThe tier mechanism + category structure + routingLP-59Comprehensive ClassificationHaiku knows all ~80 types → type/category/tier/confidenceLP-60Tier 1: Income/Employment1099, VOE, P&L, LOE (income) extractorsLP-61Tier 1: AssetsInvestment, retirement, gift letter extractorsLP-62Tier 1: PropertyPurchase agreement, insurance, mortgage statement, tax bill, HOALP-63Tier 1: Borrower-Info & LegalDriver's license/ID, divorce decree, LOE (PII-careful)LP-64Tier 1: Tax Returns (carved-out)1040 + schedules — the complex oneLP-65Tier 2: RecognizedClassify + categorize + AI summary, no deep extractionLP-66Tier 3: Generic Analyzer + FindingsStructured-flexible analysis of anything; findings visible + recordedLP-67Implications EngineFindings → suggested needs (surface, not act)LP-68Needs-List EngineModels/states + per-file serialization + deterministic floorLP-69AI Needs ReasoningPropose-with-reasoning + confirm + improve; MISMO-seededLP-70Needs-List FrontendThe processor's self-maintaining checklist dashboardLP-71Versioning + AI StalenessModel C replace + staleness warningsLP-72Detail Extensions + Standard NamingTier-aware detail + no-space naming + package groundworkLP-73Phase 2 Testing & HardeningIntegration, isolation, real-doc hardening, polish — closes Phase 2
