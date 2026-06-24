# The three-tier document model

How mortgageboss-ai scales document handling from a handful of types to ~80-100
without giving every type full extraction. Introduced in **LP-58** (Phase 2);
see **ADR-167**.

## The problem

Phase 1 handled three document types — `pay_stub`, `w2`, `bank_statement` — each
with full structured extraction (a typed schema + a prompt + tests) via the
`EXTRACTORS` registry. A real loan file draws on **~80-100** document types.
Building a first-class extractor for every one is infeasible and wasteful: most
types are low-value or rarely seen, yet the long-tail still has to be *recognized
and handled*, not dropped.

## The three tiers (level of investment)

A document **type** is assigned a **tier** — how much extraction effort it earns:

| Tier | Name | Handling | Count | Built in |
| ---- | ---- | -------- | ----- | -------- |
| **Tier 1** | First-class | Full structured extraction (typed core + catch-all) via the `EXTRACTORS` registry | ~18 | the 3 existing + LP-60..64 |
| **Tier 2** | Recognized | Classified + categorized + a short AI summary; **no** deep extraction | ~60-80 | LP-65 (summary) |
| **Tier 3** | Long-tail | Didn't match a known type → a generic analyzer produces a structured summary | open-ended | LP-66 (analyzer) |

Tier 1 is reserved for documents whose **exact data drives Phase 3 verification**
(income, assets, the note). Tier 2 still recognizes and files a document for the
processor. Tier 3 catches everything else so nothing is silently lost.

The 3 Phase-1 types **are** Tier 1, and the `EXTRACTORS` registry **is** the
Tier-1 mechanism — Phase 2 generalizes around it rather than replacing it.

## The catalog — the single source of truth

`backend/app/documents/catalog.py` maps each known `document_type` to its
`(tier, category)`:

```python
CATALOG: dict[str, tuple[Tier, DocumentCategory]] = {
    "pay_stub": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "w2": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "bank_statement": (Tier.TIER_1, DocumentCategory.ASSETS),
    # … planned Tier-1 types (extractors arrive in LP-60..64) …
    # … a starter Tier-2 set per category (LP-59 fills out all ~80) …
}
```

Helpers: `get_tier(document_type)`, `get_category(document_type)`,
`get_tier_and_category(document_type)`, `is_cataloged(document_type)`. Anything
**not** in the catalog defaults to `(Tier 3, Misc)`.

Why a catalog (not a DB table, not scattered `if/elif`):

- **Maintainable** — adding/retiring a type is a one-line edit. No migration:
  tier and category are app-layer knowledge (ADR-053/ADR-167); only the *tier a
  document was handled as* is persisted (the `documents.tier` column), never the
  type→tier *mapping*.
- **One source of truth** — both the tier (for routing) and the category (for
  filing / needs-matching) come from the same entry, so they never drift. The
  catalog replaces the Phase-1 provisional `_TYPE_TO_CATEGORY` map.

As of **LP-59** the catalog spans the **full ~80-type taxonomy** (88 types: 18
Tier 1, 70 Tier 2, across all seven categories) — an **industry-standard
starter** for a US residential mortgage file. It is **not** yet validated against
the domain expert's (Priya's) real library; expect it to **refine with Priya**
and per-type accuracy to be confirmed against real labeled documents over time.

## Comprehensive classification (LP-59)

The Haiku classifier recognizes all ~80 types. Two pieces, kept in sync by
construction:

- **The catalog** is the structural source of truth (type → tier + category).
- **`DOCUMENT_TYPE_INDICATORS`** (`app/ai/classification_prompt.py`) holds each
  type's *distinguishing indicators* — the cues that tell it from a look-alike
  (a W-2 vs a pay stub, a Loan Estimate vs a Closing Disclosure).

`render_classification_prompt()` builds the system prompt by **iterating the
catalog** (grouped by category) and injecting each type + its indicator into a
template (`prompts/classification/document_classifier.txt`, which holds the
framing + output rules). So the prompt's type list **is** the catalog's — they
cannot drift. A test asserts the indicator set exactly equals the catalog set, so
adding a type without describing it fails CI.

The classifier reads the document directly (PDF/image content block — no OCR) and
returns `document_type` + `category` + `confidence`. The returned **category is
advisory** (kept for observability); the authoritative category persisted on the
document is the **catalog's** `get_category` — one source of truth.

### Confidence handling

Routing branches on **confidence**, not on the `unknown` slug alone (threshold
`0.5`):

- **High confidence + a known type** → route to that type's tier.
- **Low confidence** (the model is unsure *which* known type — it could be one) →
  `NEEDS_REVIEW`; a human confirms/corrects via the LP-44 override.
- **High-confidence `unknown`** (the model is sure it is *none* of the known
  types) → **Tier 3** (the generic analyzer — that is its purpose).
- The graceful **error fallback** returns `unknown` at **zero** confidence, so AI
  failures land in `NEEDS_REVIEW` (low confidence), not Tier 3.

### Accuracy — honestly scoped

The taxonomy + indicators are an industry-standard **starter**. Tests verify the
**mechanism** (catalog/prompt sync, routing by tier, the confidence gates) and a
**representative spread** of types — **not** exhaustive per-type accuracy, which
needs real labeled documents (not available for all ~80) and is validated over
time and **refined with Priya**.

### Categories

`DocumentCategory` (a DB-enforced enum, VARCHAR + CHECK): `assets`,
`borrower_info`, `credit`, `disclosures`, `income_employment`, `property`,
`misc`, `custom`. The catalog default category for the long-tail is `misc`.

## Tier-aware routing

`process_document` (`backend/app/tasks/document_processing.py`) consults the
catalog **after** classification:

```
read bytes → classify (Haiku) → set tier + category from the catalog →
  confidence < 0.5 ? → NEEDS_REVIEW            (unsure which type — a human confirms)
  else route by tier:
    Tier 1 → EXTRACTORS registry          (extractor built → extract;
                                            not built yet → classified-only)
    Tier 2 → _tier2_summarize             (LP-65 — one shared summary path; terminal)
    Tier 3 → _tier3_analyze_stub          (LP-66 — terminal; a confident
                                            "unknown" lands here)
```

(LP-59 made the gate **confidence-based**: a high-confidence `unknown` is *not*
sent to review — it routes to Tier 3.)

**Every document takes exactly one path and reaches a terminal status**
(`COMPLETED` / `NEEDS_REVIEW` / `FAILED`) — never left stuck. Two notes:

- **A Tier-1 type whose extractor isn't built yet** is handled as **classified-only
  → `COMPLETED`** (no crash), exactly as Phase 1 handled a type with no registered
  extractor. (Tier 1 is now complete — LP-60..64 — so this only applies to a future
  type cataloged before its extractor.)
- All three tier paths are now **real** (Tier 1 extract / Tier 2 summarize / Tier 3
  analyze) — the three-tier handling is complete.

## Tier 2 — the shared summary path (LP-65)

Every Tier 2 (recognized) document goes through **one shared path**
(`_tier2_summarize`) — **no per-type logic**. This is the efficiency of the tier
model: ~18 extractors + **1** Tier-2 summary path + 1 Tier-3 analyzer, not ~80
extractors. The document arrives already classified + categorized (LP-59); the path:

1. generates a single lightweight **summary** — a 1-2 sentence human-readable gist
   ("what is this document, briefly?" — `app/ai/summarization.py`, a cheap
   **Haiku** call, capped at 256 tokens), stored on `documents.summary`;
2. reaches a terminal status (`COMPLETED`).

Key properties:

- **A gist, not extraction.** The summary answers "what is this?" for human
  reference (e.g. *"Flood zone determination for 60 North Street — Zone X, minimal
  risk."*). The contrast with Tier 1: Tier 1 extracts precise values that drive
  decisions; Tier 2 summarizes for reference. **Low-stakes and forgiving** — a
  slightly-off gist is fine.
- **Graceful.** `summarize_document` never raises and returns `None` on failure; a
  failed summary still finalizes the document (recognized + categorized, `summary`
  null). The summary text is **never logged** (it can quote PII) — only a length /
  presence flag.
- **Normal, package-eligible documents.** A Tier 2 doc is a first-class file
  document — it appears in the Documents tab under its category with its summary
  (a subtle list line + a "Summary" block in the drawer). The full tier-aware
  detail view (Tier 1 fields / Tier 2 summary / Tier 3 findings) is **LP-72**.

## Tier 3 — the generic analyzer (LP-66)

Every Tier 3 (long-tail / unrecognized) document goes through **one shared path**
(`_tier3_analyze`) — **no per-type logic**. A document no predefined schema
anticipates (a court order, a trust, an unusual asset statement, a personal-loan
agreement, a handwritten letter) is made *legible* by a single flexible analysis
(`app/ai/generic_analyzer.py`, **Sonnet**, generous budget) into **generic slots**
that work for any document:

- `document_type_guess`, `key_parties` (name + role), `key_dates`, `key_amounts`,
  `key_findings` (things that may affect the loan), `summary`, and `full_text`.
- The analysis + the `full_text` are stored on the document; the full text gets a
  **GIN full-text index** (Tier 3 docs can't be found by type, so search matters
  most for them — the data + index now; the search UI is future).
- **Graceful** (like the other AI helpers): `analyze_document` returns `None` on
  failure; the document still finalizes (analysis null, no findings).
- **Moderate-stakes** — the analysis surfaces things for a human to assess
  (human-in-the-loop), not calculation-grade extraction.

## Findings (LP-66) — the LP-67 + Phase 3 feedstock

A **`DocumentFinding`** is a single-document **observation** that may affect the
loan (an obligation, a property interest, an income item, a discrepancy candidate).
It is recorded **as data** (not just text) and is **uniform across tiers**: the
Tier 3 analyzer's `key_findings` AND the Tier 1 **divorce-decree** obligations
(LP-63) are recorded via the **same** mechanism (`create_document_finding`), so the
implications engine (LP-67) and Phase 3's cross-source verification consume them
identically regardless of which tier surfaced them. LP-63's "capture now, wire
findings later" deferral is **closed** here.

- **Shape:** `finding_type` + `description` + common typed fields (`amount`,
  `frequency`) + a flexible `details` JSON catch-all (findings vary) + `status`.
- **Tenant-scoped** transitively via `document → loan_file → company` (no own
  `company_id`); surfaced via `GET /loan-files/{id}/findings` (404 cross-company).
- **Distinct from the Phase 3 verification `Finding`** (a rule's red/yellow/green
  result with a resolution trail). A `DocumentFinding` is an *input observation*;
  Phase 3 reads these and may *produce* a verification `Finding`. Two models, two
  tables (`document_findings` vs `findings`).
- This ticket **records** findings (single-document); Phase 3 does the
  **cross-source** comparison. The full display is **LP-72**.

### Implications engine (LP-67) — the first consumer of findings

The implications engine (`app/services/implications.py`) turns each finding into a
`SuggestedNeed` for the processor: an `obligation` finding → "payment history /
obligation documentation"; `income_related` → "VOE / income explanation";
`property_interest` → "property documentation review"; `discrepancy_candidate` →
"review"; `other` → none. The locked rule is **surface + suggest, do NOT act**: it
produces suggestions only — it **never** mutates the financial picture, persists
anything, or creates a needs-list item (acting is Phase 3, human-confirmed). Each
`SuggestedNeed` is **explainable + traceable** (`reasoning` + `source_finding_id` →
`source_document_id`). It is **findings-scoped** (one finding → its implied need) —
the holistic, whole-file needs reasoning is **LP-69**, which *consumes* these
suggestions (an on-demand intermediate; no table) among everything else. **LP-68**
(the needs engine) ingests them too.

## Needs-list engine (LP-68) — the deterministic backbone

The needs list (the file's living checklist of required documents) is a `NeedsItem`
with a **five-state arrival lifecycle**: `PENDING` → `RECEIVED` → `VERIFIED` |
`REJECTED`; any → `WAIVED`. Driven by **document arrivals + processor actions, not
AI** (LP-68 is deterministic; the case-by-case intelligence is LP-69). Key pieces:

- **Type-level satisfaction-matching** (`app/services/needs_engine.py`): when a
  document reaches a terminal status, the oldest open need whose `needs_type` equals
  the document's `document_type` advances Received → Verified (the doc passed) |
  Rejected (it failed). ("Verified" = extraction passed; Phase 3 adds cross-source
  rules later. Quantity/recency matching is a future refinement.)
- **Per-file serialization — the race fix** (`app/tasks/needs.py`): the needs update
  runs as a **separate Celery task** that acquires a **per-loan-file Redis lock**
  before applying the matching. Concurrent arrivals for the SAME file apply one at a
  time (no lost update / double-satisfaction); DIFFERENT files update in parallel.
- **A thin deterministic floor**: near-certain needs seeded from the stated MISMO
  data (employment → pay stubs + W-2; purchase → purchase agreement; assets → bank
  statement), wired into the MISMO import. Thin — LP-69's AI augments it.
- **Source-agnostic + disposition groundwork**: a need carries its `origin` (floor /
  suggestion / ai_reasoning / …), a `disposition` (proposed/confirmed/waived/dismissed
  — AI proposes in LP-69, the processor confirms in LP-70), and `reasoning` +
  `source_finding_id`. `ingest_suggested_need` turns an LP-67 `SuggestedNeed` into a
  need (carrying the reasoning + source link); LP-69 proposals ingest the same way.

## Tier 1 extractors

A Tier-1 type routes to its registered extractor in `EXTRACTORS`
(`app/ai/extraction/__init__.py`). Every extractor follows the **LP-39a shape**: a
typed core of `TypedField`s (each carrying the coerced `value` + its
`SourceLocation`) for the decision-relevant fields, plus an `additional_sections`
grouped **catch-all** for everything else (nothing is lost; a catch-all field can
be promoted to the typed core later). Same result interface, the shared tolerant
parser, honest nulls, and graceful `.failed()`. The typed cores are **V1 starters,
refined with Priya**; accuracy is validated against real samples over time.

Registered so far:

- **LP-39 (Phase 1):** `pay_stub`, `w2` (SSN masked + never logged),
  `bank_statement`.
- **LP-60 (income/employment cluster):** `1099` (one extractor for the whole
  NEC/INT/DIV/MISC/R **series** — a `form_subtype` slug + the primary
  `income_amount`; recipient TIN masked + never logged), `voe` (employer-verified
  employment + income), `profit_and_loss` (self-employment income — `net_profit`
  is the key figure), `letter_of_explanation` (prose-light: `subject` +
  `explanation_summary` + a primary reference).
- **LP-61 (asset/reserves cluster):** `investment_account` (`total_value` is the
  reserves figure; holdings → catch-all; account number masked), `retirement_account`
  (tracks `vested_balance` **and** `total_balance` separately — vested is the
  accessible/reserves figure; never assumed equal to total; account masked),
  `gift_letter` (attestation-oriented — donor + relationship + `gift_amount` + the
  `no_repayment_attestation` that distinguishes a gift from undisclosed debt). These
  cross-check in Phase 3 against the stated MISMO assets (Phase 1.5).
- **LP-62 (property cluster):** spans two contexts. *Subject-property facts* →
  LTV + housing expense: `purchase_agreement` (`sales_price` is the LTV basis),
  `homeowners_insurance` (`coverage_amount` + `annual_premium`). *Other-property
  obligations* → DTI: `mortgage_statement` (`monthly_payment`), `property_tax_bill`
  (`annual_tax_amount`; `due_dates` kept as a string — often two installments),
  `hoa_statement` (`dues_amount` + frequency). The mortgage/tax/HOA extractors
  **capture `property_address`** but do **not** decide subject-vs-other — Phase 3
  matches the address. (The appraisal also feeds LTV but is **Tier 2** in the
  catalog today — a candidate for Tier-1 promotion later, flagged for Priya.)
- **LP-63 (borrower-info/legal cluster):** `drivers_license` (the most PII-dense
  doc — `id_number_masked` + `date_of_birth` captured for the identity check but
  **never logged**; `expiration_date` for staleness), `divorce_decree`
  (`support_obligations` + `property_awards` as first-class typed lists — the
  alimony/child-support obligations are the Phase 3 undisclosed-obligation
  feedstock, **captured now**; formal *findings* are wired when the findings
  infrastructure lands in LP-66/67), and `letter_of_explanation` — the **reused**
  LP-60 general-LOE extractor (one extractor, not two).
- **LP-64 (tax returns — the nested one):** `tax_return` is a **nested bundle** —
  a 1040 typed core + typed **income-critical schedules** (`schedule_c` [a list —
  `net_profit` is the self-employment heart], `schedule_e` [present-or-null, with
  a `properties` list + `depreciation`], `k1s` [a list]) + the catch-all (other
  schedules B/D/1/2/3, attachments). Variable composition: a schedule is empty/null
  if absent; repeatable schedules are lists. Generous token budget (16384) for the
  multi-page bundle; SSN masked + never logged. It **captures the figures**; Phase 3
  does the qualifying-income math + the two-year comparison.

**Tier 1 is complete** — every Tier-1 catalog type now has a registered extractor
(a test asserts this). A future Tier-1 type added to the catalog before its
extractor is built would still be handled gracefully as classified-only.

## What's built vs. what's next

**LP-58 (foundation):** the `Tier` enum + `tier` column (+ migration), the catalog
+ helpers, catalog-driven category, and tier-aware routing (Tier 1 fully working
via the registry; Tier 2/3 cleanly stubbed). The 3 existing types route as Tier 1.

**LP-59 (breadth):** the full ~80-type catalog, the comprehensive catalog-synced
classification prompt (per-type indicators), the advisory category, and
confidence-gated routing (low → `NEEDS_REVIEW`; confident-`unknown` → Tier 3).

**LP-60 (first Tier-1 extractor batch):** the income/employment cluster — 1099
(with subtypes), VOE, P&L, income LOE — registered and routed.

**LP-61 (asset Tier-1 batch):** the asset/reserves cluster — investment account,
retirement account (vested-vs-total), gift letter (attestation) — registered and
routed.

**LP-62 (property Tier-1 batch):** the property cluster — purchase agreement,
homeowner's insurance, mortgage statement, property tax bill, HOA statement
(address captured for subject-vs-other) — registered and routed.

**LP-63 (borrower-info/legal Tier-1 batch):** driver's license (heightened PII),
divorce decree (obligations captured; findings wired in LP-66/67), and the reused
general LOE — registered and routed.

**LP-64 (tax returns — the last Tier-1 batch):** the nested 1040 + schedules
(C/E/K-1) bundle — registered and routed. **Tier 1 is now complete.**

**LP-65 (Tier 2 — the shared summary path):** one lightweight Haiku summary for
every recognized type (no per-type logic); the gist is stored + minimally visible.

**LP-66 (Tier 3 — the generic analyzer + findings):** one flexible Sonnet analysis
for any unrecognized document (+ full-text index), the `DocumentFinding`
infrastructure (uniform across tiers), and the divorce-decree findings wiring
(LP-63 loop closed). **The three-tier handling is complete.**

**LP-67 (the implications engine):** the first consumer of findings — maps each
finding → a `SuggestedNeed` with explainable reasoning (surface + suggest, not act;
findings-scoped; an on-demand intermediate feeding LP-68/69).

**LP-68 (the needs-list engine):** the deterministic backbone — the five-state
lifecycle, type-level satisfaction-matching, **per-file serialization** (the race
fix), a thin deterministic floor from the stated MISMO data, and source-agnostic
ingestion (floor + LP-67 suggestions; LP-69 proposals plug in the same way).

**LP-69 (holistic AI needs reasoning — the differentiator):** the needs list's
intelligence — an AI call (Sonnet) reasons over the **whole file** (stated MISMO
data + documents present + findings + LP-67 suggestions) and **proposes** needs,
each with **file-specific reasoning**. Two guardrails make it trustworthy:
(1) **explainability** — every proposal carries reasoning grounded in *this* file's
data (a proposal with no reasoning is dropped); (2) **confirmation** — proposals
ingest as `disposition=PROPOSED`, `origin=ai_reasoning` (the AI proposes, never
disposes; the processor confirms/adjusts/dismisses in LP-70). It **reconciles** —
the assembled context lists what's already covered (the floor, LP-67's suggestions,
documents present, existing needs incl. dismissed), and reasoning + a deterministic
filter ensure it never duplicates them (LP-69 is the *culminating* holistic
reasoner over LP-68's floor + LP-67's findings-implications). Two triggers, both
through LP-68's per-file serialization: at **MISMO creation** (the "upload → a
tailored checklist appears" payoff — absorbs the deferred smart-needs-from-MISMO)
and **re-proposed** as documents/findings arrive. Corrections (confirm/adjust/
dismiss) are captured on the need's `disposition`; the simple V1 use folds them into
"already covered" so a dismissed proposal isn't re-proposed (a full learning loop is
future). Honestly scoped: **reasoned, explainable, improvable — not perfect out of
the gate**; the reasoning quality is the **highest-value Priya refinement** and the
prompt (`ai/prompts/needs/needs_reasoning.txt`) is a sensible starter. A real AI
call — cost/latency/eval apply; the assembled PII context is **never logged**.

**LP-70 (the needs-list dashboard — the differentiator's face):** the first major
Phase-2 UI — a **self-maintaining checklist** on the loan-file overview that
surfaces LP-68/69 (open the file → a tailored checklist appears). The **five states
made visual + action-oriented**: needs group into **Needs action** (pending /
requested / rejected) → **In review** (received) → **Complete** (verified) → **Set
aside** (waived), so "what to do next" reads at a glance. Each need shows its **AI
reasoning** (the "why", LP-69) in an inset note — explainability made visible, the
trust-making element. The **disposition flow** (the AI proposes, the processor
disposes): Confirm / Adjust / Waive / Dismiss / Add — each a tenant-scoped, audited
write that feeds LP-69's correction-capture. **Live updates** as documents arrive
(the needs query polls off the documents-in-flight flag; a satisfied need moves
Pending → Received → Verified with no manual refresh) plus a **subtle "Updating…"
cue** that shows the outcome, **not** a queue-depth/"engine running" meter (the
per-file serialization stays invisible). Tenant-scoped read + write APIs nest under
the file (`404` cross-company); the needs response carries no raw PII. See
**ADR-179**.

**LP-71.5 (floor flush-timing fix + AI-needs visibility):** a diagnostic found a
MISMO import producing only the floor's "Purchase agreement". Two fixes: (1) the
floor (`seed_floor_needs`) now **flushes first**, so its employment/asset rules see
the just-added stated rows (the session runs `autoflush=False`) and the
deterministic floor (pay stubs + W-2 + bank statements) fires on import
**independent of the AI/worker** — the rules were always correct, they just couldn't
see the data; (2) a nullable `ai_needs_status` on the loan file
(`pending`/`completed`/`failed`) makes LP-69's **async** reasoning state visible —
the dashboard says "AI is still reviewing — more needs may appear" or "AI review
didn't finish — this list may be incomplete", so a floor-only list is never silently
shown as complete (the AI failure swallow now records `failed`). Informational,
never blocking. See **ADR-180**. *(A separate operational note: LP-69's reasoning
runs in a Celery worker — `docker compose --profile worker up -d worker` — which
must be running for AI needs to be produced.)*

**Next:** LP-71 (document versioning + AI staleness) → LP-72 (the full tier-aware
detail view + package groundwork + the full-text search UI). The taxonomy, field
sets, finding/need types — and the reasoning quality — refine with Priya.
