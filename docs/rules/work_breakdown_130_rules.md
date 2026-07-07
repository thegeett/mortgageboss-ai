# Work Breakdown — 130-Rule Verification Engine, Blocker Extraction, Newly-Scoped Rules

**Purpose.** A detailed breakdown of the work to (A) accommodate the full ~130-rule playbook in the engine, (B) build the blocker-document extraction schemas, and (C) build the newly-scoped rules. Written to become Jira-style tickets. Grounded in the actual build state: Phase 3 (verification engine, calculators, cross-source, findings, FHA rules) is substantially built (LP-74..115); this is **extension and systematization**, not a from-scratch build.

**Grounding facts (from the plan + journal — verify against the repo before building):**
- Phase 3 already delivered: multi-layer rules architecture (regulatory/investor/lender-overlay), DTI/LTV/MI/reserves calculators, ~a handful of live cross-source rules, findings system (four-part findings, why/fix, undo, dedup LP-92..98), refi support (LP-99/100/101), and quality fixes (LP-102..115).
- **Reality check:** the plan *targeted* ~60 Conv + ~50 FHA + 15-20 cross-source rules, but the pipeline map showed the **threshold engine is dormant** — live findings come from the **cross-source pass** only. So the "~60/~50" threshold rules were largely *scaffolded but not firing*; the real live rule set is small. **This must be audited first** — it's the single biggest unknown in this whole plan.
- Scope tiers now set: **117 IN**, **3 PHASE 4.5**, **13 V2**.

**⚠️ Standing dependency:** the whole plan assumes the engine generalization (registry + evaluators) from the rule-engine design. Do that first, or every rule is hand-coded and the count doesn't scale.

---

# EPIC 0 — Audit & foundation (do first, blocks everything)

The most important epic, because this session reconstructed a lot from memory. **No building until these are known.**

## LP-E0.1 — Audit the live rule inventory (read-only)
- **What:** Enumerate every rule that actually *fires* today. Distinguish: live `CrossSourceRule`s, the dormant threshold engine rules (scaffolded, not firing), and calculator-surfaced checks.
- **Output:** a factual list of "rules that exist and fire" vs "rules scaffolded but dormant" vs "playbook rules not yet built."
- **Why:** the plan targeted ~110 threshold rules but they don't fire. Need the truth before estimating "how many to build."
- **Est:** S (read-only trace).

## LP-E0.2 — Audit the extractor/schema registry (read-only)
- **What:** List every document type with a registered extraction schema, and every field each schema produces. Confirm which of the 7 blockers already have partial schemas (insurance suspected; tax returns possibly).
- **Output:** a "what we extract today" map, cross-referenced to the playbook's Required-Documents column.
- **Why:** determines which blocked rules are actually blocked vs already-feedable; avoids rebuilding insurance.
- **Est:** S.

## LP-E0.3 — Confirm formats with Priya (blocking questions)
- **What:** The gating questions that determine effort:
  1. Credit report — structured (credit-MISMO/LOS fields) or PDF? (decides CR-4..13 effort: parser vs extraction)
  2. DU findings — structured/HTML report or PDF? Do we have a real findings sample (not just submission MISMO)? Always DU or also LP?
  3. Appraisal — UAD XML or PDF? Seeing UAD 2.6, 3.6, or both?
  4. Condo volume — what % of loans? (decides whether Condo epic is now or later)
  5. Borrower mix — % with rental / retirement / self-employment income? (decides IN-13/14, OC-3, AS-11 priority)
- **Output:** answers that set effort estimates for Epics 3 and 4.
- **Est:** one Priya session.

## LP-E0.4 — Reconcile the confidence model (DET vs DET-FUZZY)
- **What:** The engine hardcodes `DETERMINISTIC_CONFIDENCE = 1.0`. DET-FUZZY rules (name/address/employer matching) must emit <1.0. LP-115 establishes the pattern for one rule; generalize it so the confidence field is per-rule/computed, not a global constant.
- **Why:** structural — the employer false-positive-at-100% bug is the symptom; the whole G-family + fuzzy rules need this.
- **Est:** M. Depends on LP-115 landing.

---

# EPIC 1 — Rule engine generalization (the registry + evaluators)

Turn the hand-coded rule mechanism into the data-driven engine that can hold 130 rules. This is the "build general now" work.

## LP-E1.1 — Rule registry schema
- **What:** A rule-as-data structure (table + config): `id, name, category, evaluator, applicability{purpose/program/occupancy/property_type/requires_docs/requires_data}, params, severity, confidence_mode, message_template, canonical_type, status, scope`.
- **Output:** the schema + loader; rules become rows, not classes.
- **Est:** M.

## LP-E1.2 — Applicability filter
- **What:** The per-file selector: build file attributes, evaluate each rule's applicability predicate, run only applicable rules. Extends the existing purpose-gating (LP-99/100).
- **Critical sub-feature:** the "applicable-but-blocked-on-missing-data" state — surface rules that *would* apply but lack their data as **"awaiting-data," never silently pass** (the AS-10 / false-green safeguard).
- **Est:** M.

## LP-E1.3 — Evaluator interface + the first evaluators (~5-6)
- **What:** A common evaluator signature (`check(facts, params) -> finding|none`), then build the evaluators the seed rules need:
  - `threshold_compare` (DTI, LTV, coverage, score, IPC, cash-to-close, reserves)
  - `date_staleness` (paystub, appraisal, credit, rate lock, ID expiration)
  - `presence_check` (VOE, MI cert, case #, questionnaire)
  - `cross_source_match` (name, address, SSN, employer, price — **with DET-FUZZY tolerance + <1.0 confidence built in**)
  - `continuity_check` (chaining, pages, month completeness)
  - `reconcile_list` (undisclosed liability, gift chain — extend for tradelines/AUS later)
- **Est:** L (this is the core reusable logic).

## LP-E1.4 — Runner integration with the existing pipeline
- **What:** Wire the registry+evaluators into the existing cross-source pass so registry rules flow through the SAME dedup (graduation LP-86), reconcile (LP-93/94), provenance (LP-114.1), confidence, and findings UI. Registry rules become `CrossSourceRule`-equivalents at runtime.
- **Why:** must reuse the built findings/provenance/submission-gate machinery, not fork it.
- **Est:** M.

## LP-E1.5 — Params as editable config
- **What:** Move thresholds/windows/tolerances from code into rule `params`, editable via the existing overlay-admin UI (LP-80/87). Priya tunes without deploy.
- **Est:** M. Reuses the lender-overlay config pattern.

## LP-E1.6 — Migrate existing live rules into the registry
- **What:** Port the handful of live CrossSourceRules (employer, etc.) into registry rows to prove the pattern end-to-end. Retire/park the dormant threshold engine or decide its fate (LP-E0.1 informs this).
- **Est:** M.

---

# EPIC 2 — Seed rules (the ~30 buildable-now, IN + NOW)

Build the first batch as registry rows + their evaluators. These need no new extraction.

**The seed set (filter NOW + IN):** AS-1 large deposit, AS-2 EMD, AS-3 cash-to-close, AS-8 chaining, AS-10 completeness, IN-2 paystub recency, IN-3 YTD, IN-5 employer (LP-115), IN-6 paystub↔W2, CR-1 undisclosed liability, CR-2 HELOC-HCLTV, CR-3 paid-to-qualify, PR-2 appraised-vs-price, DT-5 insurance premium, IH-1 insurance adequacy, IH-2 mortgagee, MI-1 PMI, MI-4 FHA MIP, PC-2 price match, PC-3 address match, PC-7 closing date, PE-3 FHA MRI, plus G-family (after LP-115): G1/ID-1 name, G2/ID-4 address, G4/ID-2 SSN, G6 co-borrower.

## LP-E2.1 — Seed rules: assets (AS-1, AS-2, AS-3, AS-8, AS-10, AS-7)
- Build as registry rows using `threshold_compare`, `continuity_check`, `reconcile_list`. AS-10 requires the shared month-count requirement (from DU findings or config).
- **Est:** M.

## LP-E2.2 — Seed rules: income (IN-2, IN-3, IN-5, IN-6)
- `date_staleness`, arithmetic, `cross_source_match` (fuzzy). IN-5 = LP-115 ported.
- **Est:** M.

## LP-E2.3 — Seed rules: credit/liabilities-from-MISMO (CR-1, CR-2, CR-3)
- `reconcile_list` against MISMO liabilities. No credit report needed (uses MISMO).
- **Est:** S-M.

## LP-E2.4 — Seed rules: property/insurance/MI (PR-2, DT-5, IH-1, IH-2, MI-1, MI-4, PE-3)
- `threshold_compare`, `presence_check`. Depends on insurance schema (audit LP-E0.2).
- **Est:** M.

## LP-E2.5 — Seed rules: contract + identity (PC-2, PC-3, PC-7, ID-1, ID-2, ID-4, G6)
- `cross_source_match` (fuzzy) + `date_staleness`. Depends on LP-E0.4 confidence + extraction of SSN/DOB.
- **Est:** M.

---

# EPIC 3 — Blocker document extraction schemas

Build the schemas that unblock the ~30 blocked rules. **Schema-first, validate against real samples, hold rules "awaiting-data" until schema lands.** Order by unlock value; effort gated by LP-E0.3 format answers.

## LP-E3.1 — Credit report schema *(biggest unlock)*
- **What:** Define + build the credit-report extraction schema (scores, tradelines, public records, collections, inquiries) per the blocker-schema spec.
- **Two paths (from LP-E0.3):** structured credit-MISMO → deterministic parser (S-M); PDF → AI-extraction schema + validation (L).
- **Unlocks:** CR-4, CR-5, CR-6, CR-7, CR-8, CR-9, CR-10, CR-11, CR-12, CR-13 (10 rules).
- **Est:** M-L (format-dependent). **Highest priority blocker.**

## LP-E3.2 — AUS/DU findings schema *(highest leverage)*
- **What:** Extract recommendation, data-used, conditions list, red-flags.
- **Unlocks:** AU-1, AU-2, AU-3, AU-4; feeds AS-10's month-count requirement.
- **Special value:** AU-2 reconciles the file against the underwriter's own condition list.
- **Est:** M (structured); depends on having a real findings sample.

## LP-E3.3 — Appraisal (URAR/UAD) schema
- **What:** Extract subject, valuation, condition rating, flood zone, comps. **Design for UAD 2.6 + 3.6 (Nov 2026 cutover).**
- **Unlocks:** PR-2 (fully), PR-4, PR-5, PR-6, PR-7, IN-14, DT-4; feeds IH-5.
- **Est:** M (UAD XML) to L (PDF + dual-format).

## LP-E3.4 — Flood determination (SFHDF) schema
- **What:** Extract zone, in-SFHA flag, community/map, LOMC. Small, standardized.
- **Unlocks:** IH-5, IH-6.
- **Est:** S.

## LP-E3.5 — Insurance schema (audit-then-complete)
- **What:** If LP-E0.2 shows a partial schema, extend it (dwelling coverage, mortgagee, dates, premium); else build. 
- **Unlocks/completes:** IH-1, IH-2, IH-3, IH-4, DT-5.
- **Est:** S (extend) to M (build).

## LP-E3.6 — Title commitment (ALTA) schema
- **What:** Extract Schedule A (structured), B-I requirements (list), B-II exceptions (list, some AI). 
- **Unlocks:** TI-1..6, RE-1.
- **Est:** M.

## LP-E3.7 — Rules unblocked by schemas (registry rows)
- **What:** As each schema lands, add the corresponding rule rows (CR-4..13 after E3.1, AU-* after E3.2, PR/TI/IH-flood after their schemas). Mostly config rows reusing evaluators; `reconcile_list` extends for tradelines/AUS-conditions.
- **Est:** M total, spread across schemas.

---

# EPIC 4 — Newly-scoped IN rules (Condo, uncommon income, boundary)

The rules moved from SCOPE? to IN. Priority gated by LP-E0.3 (condo volume, borrower mix).

## LP-E4.1 — Condo/HOA epic (CO-1..5, IH-7, IH-8) + condo-doc schema
- **What:** Condo questionnaire + master policy + HOA budget schema; then the 7 condo rules (questionnaire present, HOA dues in DTI, master insurance/fidelity, reserves, litigation/concentration, condo master policy, wind/hail).
- **Gated by:** condo volume (LP-E0.3). If low volume, defer within V1.
- **Est:** L (new doc type + 7 rules, some AI-layer for warrantability).

## LP-E4.2 — Uncommon income types (IN-13, IN-14, OC-3, AS-11)
- **What:** Other-income continuance, rental income support, investment rental, retirement/stock liquidation. Some need Schedule E / award-letter extraction.
- **Gated by:** borrower mix (LP-E0.3).
- **Est:** M.

## LP-E4.3 — Product-boundary rules (ID-7, ID-8, ID-9, PC-9, DT-7)
- **What:** Marital/title consistency, citizenship/residency, POA acceptability (AI), financing contingency dates, ATR completeness. Some lean AI/judgment; DT-7 may be redundant — evaluate.
- **Est:** M. Build the clean ones (ID-7, ID-8); evaluate ID-9/PC-9/DT-7 for value.

---

# EPIC 5 — Confidence, monitoring, and hardening

## LP-E5.1 — DET-FUZZY confidence rollout
- Apply the LP-E0.4 confidence model across all DET-FUZZY rules (G-family, employer, institution, creditor matching).
- **Est:** M.

## LP-E5.2 — Production rule-quality monitoring (V2 design, stub now)
- The AI review-and-flag + disposition-capture + override-rate monitoring from the plan's V2 section. Stub the `finding_review_signals` table now; full build is V2.
- **Est:** S now (schema stub), L later (V2).

## LP-E5.3 — Golden-file eval set
- A durable measurement layer: real de-identified files with known-correct findings, to catch regressions as rules grow.
- **Est:** M. High value — the measurement backbone.

---

# Dependency order (what blocks what)

```
EPIC 0 (audit + Priya formats + confidence model)   <- do first, blocks all
        |
        v
EPIC 1 (registry + evaluators + runner)              <- the engine generalization
        |
        v
EPIC 2 (seed ~30 rules)  ---- provable value, no new extraction
        |
        +--> EPIC 3 (blocker schemas) --> unblocked rule rows   [gated by E0.3 formats]
        |
        +--> EPIC 4 (newly-scoped IN rules)                     [gated by E0.3 mix]
        |
        v
EPIC 5 (confidence rollout, monitoring, eval set)    <- hardening, ongoing
```

**Critical path:** E0 → E1 → E2 delivers a working data-driven engine with ~30 rules. E3/E4 then add breadth in parallel, each gated by a Priya answer or a schema. E5 hardens throughout.

---

# Effort summary (rough, verify after E0 audit)

| Epic | Work | Rough size |
|---|---|---|
| E0 Audit & foundation | 4 tickets (audits + Priya + confidence) | S-M each |
| E1 Engine generalization | 6 tickets (registry, filter, evaluators, runner, config, migrate) | M-L |
| E2 Seed rules | 5 tickets (~30 rules as rows) | M each |
| E3 Blocker schemas | 7 tickets (6 schemas + unblocked rows) | S-L, format-gated |
| E4 Newly-scoped rules | 3 tickets (condo, income, boundary) | M-L |
| E5 Hardening | 3 tickets (confidence, monitoring, eval set) | M |

**Rule accounting (to confirm in E0):**
- ~30 seed (E2) — buildable now, no new extraction
- ~30 blocked (E3) — unblock via 6 schemas
- ~16 newly-scoped IN (E4)
- ~41 remaining IN — mostly EXTRACT-gated or existing; fill in as data/rows land
- 3 Phase 4.5 — separate phase
- 13 V2 — deferred

---

# What to confirm before writing tickets

1. **The E0 audit** — the real live-rule count and extractor inventory. Everything estimates off this. My numbers are reconstructions; the audit replaces them with facts.
2. **The Priya formats** (LP-E0.3) — credit/AUS/appraisal structured-vs-PDF, condo volume, borrower mix. These gate Epics 3 and 4.
3. **The engine-generalization decision** — confirm you want the full registry+evaluator build (E1) before seeding rules, vs. continuing to hand-code. (You confirmed: build general for 130.)

Once E0 lands, the estimates firm up and this converts cleanly to a Jira epic/story/task hierarchy.
