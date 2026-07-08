# Phase 3.5 — Verification Scale-Up & Trust Surface — Jira Tickets (LP-115+)

**Phase 3.5** carves out the rule-engine scale-up and verification-trust work from Phase 3 (following the 1.5 / 4.5 sub-phase pattern). Six epics.

**Note on LP-115 (the employer name-matching fix).** The original standalone LP-115 was written but intentionally NOT run — the discussion it triggered produced this 130-rule engine decision. Rather than run it as a throwaway hand-coded fix and rebuild it later, **the employer fix is absorbed into this work as the reference implementation for the DET-FUZZY fuzzy-matching machinery** — built once, correctly, as the proof-of-concept for the new engine (LP-117 confidence model + LP-120 evaluator). This is cleaner in a development phase where nothing is live yet.

**Standing rule for every threshold-bearing story:** any rule with a threshold/window/tolerance/limit ships the value as **editable config**, and does **not** go live at full confidence until **Priya validates the number**. This is a required acceptance criterion — unvalidated thresholds are the main over-flagging risk.

**Cross-cutting conventions:** deterministic rules are built as CrossSourceRules flowing through the existing dedup (LP-86) / reconcile (LP-93/94) / provenance (LP-114.1) / findings pipeline. Read-only audits change nothing. Every rule ticket writes `docs/tickets/LP-XX.md` + an ADR; changes committed locally, Geet pushes.

---

# EPIC A — Audit & Foundation (LP-115..117) — *do first, blocks all*

## LP-115 — Audit the live rule inventory (read-only) ✅ DONE
**Type:** Spike · **Epic:** A · **Blocks:** all rule tickets · **Status:** COMPLETE
**Key findings (drive the tickets below):** Only **5 rules fire today** (not ~30). Of 18 deterministic
cross-source rules, **13 are fact-starved** (wired but their facts are never populated → can't fire).
The threshold engine is **confirmed dormant** — 107 threshold rules emit zero findings, no caller
(two functions named `run_verification` — the live API route vs. the dead service — caused the prior
mis-reconstruction). Calculators reuse the threshold engine's threshold DATA as a limits lookup (that
dependency is live even though the finding path is dead). Employer rule ground truth captured (see LP-120).
A rule-table completeness view would over-count live coverage 3.6×. See docs/audits/LP-115-live-rule-inventory.md.
**Summary:** Establish the true set of verification rules that actually fire today.
**Description:** The 130-rule strategy reconstructed counts from memory; the pipeline map showed the threshold engine is dormant (live findings come only from the cross-source pass). Produce a factual inventory before estimating the scale-up.
**Work:**
- Enumerate every rule that produces a live finding today (the wired CrossSourceRules).
- List every threshold-engine rule that exists but is dormant (scaffolded, not firing).
- List calculator-surfaced checks (DTI/LTV/MI/reserves) that are not findings.
- Map each to its playbook ID where one exists.
- Note the current state of the employer-consistency rule (the one with the known false-positive bug) — it becomes the DET-FUZZY reference case in LP-117/LP-120.
  **Acceptance criteria:**
- [ ] Written inventory: `fires-today` / `scaffolded-dormant` / `not-built` per rule.
- [ ] True count of live rules stated (replaces the "~30 exists" reconstruction).
- [ ] Dormant threshold engine's fate flagged (wire vs. retire — decided in Epic B).
- [ ] Read-only — no code changed.

## LP-116 — Audit the extractor / schema registry (read-only) ✅ DONE
**Type:** Spike · **Epic:** A · **Blocks:** Epic D, Epic E · **Status:** COMPLETE
**Key findings (reframe Epics C & D):** There is NO per-type schema registry — extraction is ONE
monolithic AI prompt returning a single flat `ExtractedData` shape (everything hangs off one
`financial_data` dict). Crucially: **the fields are mostly ALREADY EXTRACTED** (14 of 16 spot-checked
present — SSN, DOB, address, employer, YTD, pay dates, deposits, balances, W-2), but
`build_cross_source_facts` maps only **~5 of 22 available fields** into CrossSourceFacts. So the 13
fact-starved rules are a **FACT-BUILDER-GAP (wiring), not an extractor gap.** Only TWO genuine
extractor gaps: page-count (AS-9) and NSF/overdraft flags (AS-7). Insurance = PARTIAL (coverage/carrier
as generic fields; NO mortgagee, no typed structure → extend with a typed sub-model). Tax returns =
EXCLUDED entirely (IN-12 is a real build). All 6 blockers lack typed structure → add typed sub-models,
don't bloat the monolith. Flat extraction has no per-field plausibility check → silent-misread risk
(strengthens the eval-set case). See docs/audits/LP-116-extractor-schema-registry.md.
**Summary:** Establish which document types have extraction schemas and what fields each produces.
**Description:** Determines which "blocked" rules are truly blocked vs. already feedable; prevents rebuilding existing schemas (insurance suspected; tax returns possibly).
**Work:**
- List every registered document type + its extraction schema fields.
- Cross-reference against the playbook's Required-Documents column.
- Flag partial schemas (esp. insurance, tax returns).
  **Acceptance criteria:**
- [ ] A "what we extract today" field map per document type.
- [ ] Each of the 6 blocker docs marked: no-schema / partial-schema / full-schema.
- [ ] Insurance status confirmed (build vs. extend).
- [ ] Read-only.

## LP-117 — Priya format & volume/mix session + confidence-model decision (spike)
**Type:** Spike · **Epic:** A · **Blocks:** Epic D (formats), Epic E (volume/mix), LP-120 (confidence)
**Summary:** Get the answers that gate blocker-schema effort and newly-scoped-rule priority; lock the DET-FUZZY confidence approach.
**Description:** A structured Priya session for the format/volume questions, plus locking the confidence-model direction that the employer fix (absorbed here) establishes.
**Work / questions:**
- Credit report — structured (credit-MISMO/LOS fields) or PDF? Which vendor(s)?
- DU findings — structured/HTML or PDF? Real findings sample on hand? DU only, or also LP?
- Appraisal — UAD XML or PDF? Seeing UAD 2.6, 3.6, or both?
- Condo volume — what % of loans?
- Borrower mix — rough % with rental / retirement / self-employment income?
- Confirm the DET-FUZZY confidence direction (fuzzy match → computed <1.0), using the employer-name case as the worked example to validate the tolerance with Priya.
  **Acceptance criteria:**
- [ ] Each format question answered → effort path chosen for CR/AUS/appraisal schemas.
- [ ] Condo volume + borrower mix captured → Epic E priority set.
- [ ] DET-FUZZY confidence approach confirmed; employer-match tolerance validated with Priya.
- [ ] Answers recorded in the plan/decision log.

## LP-117.5 — Commit reference docs to the repo + add playbook_id
**Type:** Story · **Epic:** A · **Blocks:** LP-118 (registry references playbook IDs)
**Summary:** The engine plan references playbook IDs, but the LP-115 audit found the reference docs aren't in the repo and no rule carries a playbook_id.
**Description:** verification_rule_playbook.xlsx, blocker_extraction_schemas.md, consolidated_rule_master_list.md, and work_breakdown_130_rules.md exist only as generated artifacts, not repo files. The rule model has no playbook_id field, so rules can't be traced to the playbook. Fix both so the engine's playbook-ID references resolve to real, version-controlled sources.
**Work:**
- Commit the reference docs into the repo (e.g. `docs/rules/`): the playbook (xlsx), the blocker schema spec, the master list, the work breakdown.
- Add a `playbook_id` field to the rule model/registry schema (feeds LP-118).
- Optionally add a machine-readable rule seed (CSV/JSON) derived from the playbook, as the version-controlled authoring source for the registry (per the hybrid storage decision).
  **Acceptance criteria:**
- [ ] Reference docs committed under `docs/rules/` (version-controlled, not just generated artifacts).
- [ ] `playbook_id` field present on the rule model/registry schema.
- [ ] Every rule can be traced to its playbook ID.
- [ ] (If done) a version-controlled rule seed derived from the playbook exists for LP-118 to load.

---

# EPIC B — Rule Engine Generalization (LP-118..123)

> The data-driven engine (registry + evaluators). The employer fix is built here as the first DET-FUZZY rule — the proof-of-concept.

## LP-118 — Rule registry: table + seed + audit trail (HYBRID storage)
**Type:** Story · **Epic:** B · **Depends:** LP-115, LP-117.5
**Summary:** Rules become data rows the engine reads per run, authored from version-controlled config, with a change-audit trail. **Storage decision: HYBRID (locked).**
**Storage design (ADR — record this decision):**
- **`verification_rules` table** — each rule a row the engine iterates per run; PK `rule_id` (AS-1, CR-4, …) referenced by findings, monitoring, activity_log. Also carries `playbook_id` (LP-117.5).
- **Version-controlled seed file** authors the rule definitions (evaluator, applicability, canonical_type, default params) in the repo — git-tracked, code-reviewed — and populates the table via migration. Structural rule logic stays reviewable; the table is the runtime read-source.
- **`rule_change_audit` table** (or activity_log integration) records every change to a rule row (old/new value, who, when) — the compliance history a pure table would lose.
- **Change discipline:** STRUCTURAL fields (evaluator, applicability, canonical_type) change via seed + migration (reviewed); TUNABLE fields (params, severity, enabled) editable live via admin UI (LP-122), captured in the audit trail.
  **Work:**
- Rule-row structure: `rule_id, playbook_id, name, category, evaluator, applicability{purpose, program, occupancy, property_type, requires_docs, requires_data}, params, severity, confidence_mode, message_template, canonical_type, status, scope, enabled, validated`.
- Create `verification_rules` + `rule_change_audit` tables + migration.
- Version-controlled seed (from LP-117.5's rule seed) → loader populates the table.
- Write the ADR documenting the hybrid choice (why: compliance wants logic changes in git; Priya wants live param tuning).
  **Acceptance criteria:**
- [ ] `verification_rules` table exists; the engine reads rules from it per run; `rule_id` is the stable reference used by findings/monitoring/activity_log.
- [ ] Rule definitions are authored in a version-controlled seed and loaded via migration (not hand-entered).
- [ ] `rule_change_audit` records every rule-row change (old/new/who/when).
- [ ] `params` editable as data; `enabled`/`validated` present (validated=false → runs at reduced confidence, not full-blocking — the Priya-validation gate).
- [ ] `canonical_type` present (AI graduation); `playbook_id` present (traceability); scope/status present (IN / PHASE 4.5 / V2; NOW / EXTRACT / BLOCKED).
- [ ] ADR records the hybrid storage decision.

## LP-119 — Applicability filter (with the awaiting-data state)
**Type:** Story · **Epic:** B · **Depends:** LP-118
**Summary:** The engine self-selects applicable rules per file and never silently skips a rule blocked on missing data.
**Work:**
- Build file attributes (purpose, program, occupancy, property type, docs-present, data-present).
- Evaluate each rule's applicability; run only applicable rules.
- Classify each applicable rule as runnable vs. **awaiting-data**.
- Extend the existing purpose-gating (LP-99/100).
  **Acceptance criteria:**
- [ ] FHA-purchase applies FHA rules, not VA/refi; condo rules only if condo.
- [ ] A rule missing its data is **awaiting-data**, NOT silently skipped and NOT flagged failed.
- [ ] The applicable/awaiting/failed split is exposed for the 3.9 UI.
- [ ] No rule hand-picked per file.

## LP-120 — Evaluator interface + first evaluators + DET-FUZZY confidence (absorbs the employer fix)
**Type:** Story · **Epic:** B · **Depends:** LP-118, LP-117
**Summary:** The reusable logic shapes, including the fuzzy-match evaluator and per-rule confidence — with the employer-consistency rule as the first concrete DET-FUZZY case.
**Description:** This ticket both builds the evaluator library AND lands the employer name-matching fix (the original LP-115 intent) as the reference DET-FUZZY rule.
**Audit ground truth (from LP-115 — build against these facts, not reconstructions):**
- Current check: `_check_employer_name_consistency` at `app/verification/cross_source/rules.py:208-224`; rule row `XSRC_INCOME_EMPLOYER_NAME` (`rule_id="xsrc.income.employer_name_consistency"`, canonical_type `employer_mismatch`, category INCOME, YELLOW) at rules.py:468-475.
- Current matching: `_norm` (rules.py:105-107) does lowercase + strip + collapse-internal-whitespace ONLY — no suffix stripping, no containment, no fuzzy distance. It fires when a documented employer's normalized string is not exactly in the stated set. This is the bug: "novant health" ∉ {"novant"} → false positive.
- Current confidence: the finding is written with the GLOBAL constant `DETERMINISTIC_CONFIDENCE = 1.0` at `app/verification/confidence.py:27`, applied in `_to_finding` (cross_source_deterministic.py:148). There is no per-rule confidence today.
- Current dedup: `subject_key=f"employer_name:{_norm(emp)}"`. Downstream identity-collapse (LP-93/94) ALREADY lands one-finding-per-IDENTICAL-normalized-name. What it does NOT do is group NEAR-VARIANT names. So the dedup gap is the SAME gap as the matching bug — not a missing `_distinct`.
  **Work:**
- Common evaluator signature: `check(facts, params) -> passed | failed(finding) | awaiting_data`.
- Build seed evaluators: `threshold_compare`, `date_staleness`, `presence_check`, `cross_source_match` (fuzzy), `continuity_check`, `reconcile_list`.
- In `cross_source_match`: corporate-suffix canonicalization (Inc/LLC/Health/Medical Group/etc.) + conservative containment/subset matching; clean match → high confidence; shared-token-not-subset → computed low-confidence "possible variation — verify"; never silent-match (identity false-negative is the danger), never a false 100%.
- Replace the global `DETERMINISTIC_CONFIDENCE = 1.0` (confidence.py:27) with per-rule `confidence_mode` (`certain` = 1.0 vs `computed` from match quality); update `_to_finding` to read it.
- Configure the employer-consistency rule as a `cross_source_match` registry row (replacing the rules.py:208-224 check), preserving its canonical_type `employer_mismatch` so AI graduation still works.
  **Acceptance criteria:**
- [ ] Pure-DET rules emit 1.0; DET-FUZZY rules emit computed <1.0 on fuzzy matches, 1.0 only on clean matches.
- [ ] Employer case (LF-6T3N): "Novant" matches "Novant Health"/"NOVANT MEDICAL GROUP LLC" → no false finding; a genuine mismatch → fires; the ambiguous middle → low-confidence "verify".
- [ ] Near-variant employer names GROUP to one finding (the real gap — not just identical-name dedup, which already works).
- [ ] No code reads the old global `DETERMINISTIC_CONFIDENCE` constant (confidence.py:27 removed/replaced).
- [ ] canonical_type `employer_mismatch` preserved so the AI still defers via graduation.
- [ ] Each evaluator returns the three-state result (passed/failed/awaiting-data), with unit tests.

## LP-121 — Runner integration with the existing pipeline
**Type:** Story · **Epic:** B · **Depends:** LP-119, LP-120
**Summary:** Registry rules flow through the SAME findings machinery as today.
**Work:**
- Runner loads applicable rules, invokes evaluators, emits results.
- Failed → findings via existing `_to_finding`, dedup (LP-86), reconcile (LP-93/94), provenance (LP-114.1), submission gate.
- Passed / awaiting-data → captured for the 3.9 lists (Epic F).
  **Acceptance criteria:**
- [ ] A registry-defined failing rule produces a finding indistinguishable (to the UI) from a hand-coded one.
- [ ] Dedup/reconcile/provenance/confidence all apply unchanged.
- [ ] Passed and awaiting-data results captured, not discarded.

## LP-122 — Params as editable config (admin UI)
**Type:** Story · **Epic:** B · **Depends:** LP-118 · **Reuses:** LP-80/87 overlay admin
**Summary:** Priya tunes thresholds without a deploy.
**Work:**
- Surface rule `params` in the overlay-admin UI; edits take effect next run; audit-logged.
  **Acceptance criteria:**
- [ ] A threshold changed via UI affects the next verification run.
- [ ] ⚠️ **Priya-validate:** thresholds ship as grounded-starters; UI marks unvalidated params.
- [ ] Changes audit-logged.

## LP-123 — Migrate remaining live rules into the registry
**Type:** Story · **Epic:** B · **Depends:** LP-121, LP-115
**Summary:** Port any other live CrossSourceRules to registry rows; decide the dormant threshold engine's fate.
**Audit recommendation (LP-115):** RETIRE the threshold engine, don't wire it. Its 107 threshold
rules emit zero findings (no caller — the live `run_verification` API route never calls the dead
`run_verification` threshold service; note the name collision, rename one for clarity). Port the
still-wanted single-source checks (credit-score floors, DTI/LTV ceilings, doc-age/staleness, FHA
MIP/MPR) into the LP-118 registry as data rows. CRITICAL: the calculators reuse the threshold
engine's threshold DATA as a limits lookup — that dependency must be preserved (keep the threshold
values available to the calculators even after retiring the finding-emitter path).
**Work:**
- Convert remaining live cross-source rules to registry rows (the 5 that fire; employer already done in LP-120).
- Retire the dormant threshold engine's finding-emitter path; port its wanted single-source checks into the registry as rows.
- Preserve the calculators' threshold-data lookup dependency.
- Rename one of the two `run_verification` functions to remove the collision that caused prior mis-reconstruction.
  **Acceptance criteria:**
- [ ] All currently-live rules run from the registry with identical behavior.
- [ ] Threshold engine's finding path retired; its wanted checks ported to registry rows; calculators' threshold-data lookup intact.
- [ ] The `run_verification` name collision resolved.
- [ ] Regression: LF-6T3N produces correct findings (employer false-positives gone); DTI/LTV calculators still show correct limits.

---

# EPIC C — Seed Rules (LP-123.5, LP-124..128) — mostly fact-WIRING, not extraction

> **Reframed by the LP-116 audit — Epic C is far cheaper than originally planned.** The fields the
> 13 fact-starved rules need are ALREADY EXTRACTED; they're just not wired through. `build_cross_source_facts`
> maps only ~5 of 22 available extracted fields into `CrossSourceFacts`. So most "seed rules" are a
> MAPPING-LAYER FIX (wire an already-extracted field into CrossSourceFacts), NOT extraction work and
> NOT new rule logic — the rule shell already exists, inert. Only TWO seed rules need genuine
> extraction additions: AS-7 (NSF/overdraft flags) and AS-9 (page-count) — both confirmed non-extracted.
> **Fast first win = LP-123.5 below: extend the fact-builder 5→22 mappings, lighting up ~13 dormant
> rules at once.** Migrate lit shells into the registry (LP-118). Every threshold → Priya-validate.

## LP-123.5 — Extend build_cross_source_facts (5→22 field mappings) — the fast first win
**Type:** Story · **Epic:** C · **Depends:** LP-116 · **Can precede full registry** (targeted fix)
**Summary:** Wire the ~17 already-extracted-but-unmapped fields into CrossSourceFacts, lighting up the 13 fact-starved dormant rules.
**Description:** Per LP-116, the extraction already produces SSN, DOB, address, employer, YTD, deposits, balances, W-2 fields, etc., but `build_cross_source_facts` maps only ~5 of the 22 available fields. Extending the mapping lights up the dormant cross-source rules with no extractor or rule-logic changes.
**Work:**
- Map the ~17 unwired extracted fields into `CrossSourceFacts` (SSN, DOB, current address, employer, YTD, pay date, deposits, statement balances, account holder, W-2 fields, etc. — the exact list from LP-116).
- Verify each newly-wired fact reaches its dormant rule and the rule now fires on LF-6T3N where expected.
- Do NOT change rule logic or the employer rule (that's LP-120); this is purely the mapping layer.
  **Acceptance criteria:**
- [ ] `build_cross_source_facts` maps the full set of available extracted fields (per LP-116's list).
- [ ] The 13 fact-starved rules now receive their inputs; those that should fire on LF-6T3N do.
- [ ] No extractor changes, no rule-logic changes — mapping layer only.
- [ ] ⚠️ Any rule that fires with a threshold ships that threshold as config; Priya-validate before full-confidence.

> Registry rows reusing Epic B evaluators. Every threshold → Priya-validate.

## LP-124 — Seed: asset rules
**Type:** Story · **Epic:** C · **Depends:** LP-120, LP-121, LP-123.5
**Rules:** AS-1 large-deposit sweep, AS-2 EMD sourcing, AS-3 cash-to-close, AS-7 NSF/overdraft, AS-8 chaining, AS-9 missing pages, AS-10 recency completeness.
**Note (LP-116):** AS-1/AS-2/AS-3/AS-8/AS-10 are wire-the-fact rules (LP-123.5 supplies deposits, balances, periods). AS-7 (NSF/overdraft flags) and AS-9 (page-count) are the TWO genuine EXTRACTION-GAP rules — they need new fields added to the extraction before they can fire.
**Acceptance criteria:**
- [ ] Fact-wired rules (AS-1/2/3/8/10) built as registry rows using threshold_compare / continuity_check / reconcile_list on the LP-123.5 facts.
- [ ] AS-7 and AS-9 include the extraction addition (NSF/overdraft flags; declared page-count) — the only two seed rules needing extractor work.
- [ ] AS-10's month-count comes from DU findings (when available) or config, SHARED with the needs list (LP-108).
- [ ] AS-8 (chaining) and AS-10 (enough months) are distinct — chaining only when 2+ statements exist.
- [ ] ⚠️ **Priya-validate:** large-deposit % (AS-1), recency window (AS-10), NSF tolerance (AS-7).

## LP-125 — Seed: income rules
**Type:** Story · **Epic:** C · **Depends:** LP-120
**Rules:** IN-2 paystub recency, IN-3 YTD consistency, IN-6 paystub↔W2 coverage. *(IN-5 employer consistency already landed in LP-120.)*
**Acceptance criteria:**
- [ ] IN-6 uses cross_source_match with DET-FUZZY confidence.
- [ ] ⚠️ **Priya-validate:** paystub recency window, YTD variance tolerance.

## LP-126 — Seed: credit-from-MISMO rules
**Type:** Story · **Epic:** C · **Depends:** LP-120
**Rules:** CR-1 undisclosed liability (MISMO vs DTI), CR-2 HELOC-in-HCLTV, CR-3 paid-to-qualify.
**Acceptance criteria:**
- [ ] Uses MISMO liabilities only (no credit report needed).
- [ ] CR-2 uses HELOC credit limit, not balance.
- [ ] CR-3 flags excluded-paid-off liabilities lacking payoff evidence.

## LP-127 — Seed: property / insurance / MI rules
**Type:** Story · **Epic:** C · **Depends:** LP-120, LP-133 (typed insurance sub-model)
**Rules:** PR-2 appraised-vs-price, DT-5 insurance premium in DTI, IH-1 insurance adequacy, IH-2 mortgagee clause, MI-1 PMI-required, MI-4 FHA MIP, PE-3 FHA MRI.
**Note (LP-116):** Insurance is PARTIAL — coverage amount and carrier come through as generic financial fields (IH-1/DT-5 close), but there is NO mortgagee and no typed structure, so IH-2 (mortgagee clause) is blocked until the typed insurance sub-model lands (LP-133, extend-not-build).
**Acceptance criteria:**
- [ ] IH-1/DT-5 use the already-captured coverage/premium fields (wire if needed).
- [ ] IH-2 (mortgagee) depends on the typed insurance sub-model (LP-133).
- [ ] MI-1 fires only Conv + LTV>80%; MI-4 fires only FHA.
- [ ] ⚠️ **Priya-validate:** coverage/threshold values.

## LP-128 — Seed: contract & identity rules
**Type:** Story · **Epic:** C · **Depends:** LP-120, LP-123.5
**Rules:** PC-2 price match, PC-3 address match, PC-7 closing date, ID-1 name consistency, ID-2 SSN, ID-4 address consistency, G6 co-borrower.
**Note (LP-116):** SSN, DOB, and address are ALREADY EXTRACTED — these are fact-WIRING rules (LP-123.5 supplies the facts), not extraction work.
**Acceptance criteria:**
- [ ] Fuzzy matches (name/address) use DET-FUZZY confidence; SSN is exact-match.
- [ ] ID-2 (SSN) / ID-4 (address) consume the LP-123.5-wired facts (no extractor change needed).
- [ ] Over-loosening guarded (identity false-negative is the danger).

---

# EPIC D — Blocker Document Typed Sub-Models (LP-129..135) — *format-gated by LP-117*

> **Reframed by the LP-116 audit.** There is NO per-type schema registry to add to — extraction is
> one monolithic AI prompt returning a flat `ExtractedData` shape. The audit's recommendation
> (adopted here): for each blocker, add a TYPED SUB-MODEL (a structured, typed extracted shape for
> that document type) rather than bloating the monolithic prompt with more flat fields. Typed
> sub-models give deterministic rules the reliable structure they need and keep the extraction
> maintainable. Schema-first; validate against real de-identified samples; hold un-modeled rules in
> awaiting-data. Field-lists in docs/rules/blocker_extraction_schemas.md.

## LP-129 — Credit report extraction schema *(biggest unlock)*
**Type:** Story · **Epic:** D · **Depends:** LP-117 (format), LP-116
**Summary:** Structured credit data (scores, tradelines, public records, collections, inquiries).
**Acceptance criteria:**
- [ ] Per LP-117: structured credit-MISMO → parser; PDF → AI-extraction schema.
- [ ] Tradelines, scores, public records, collections, inquiries → typed fields.
- [ ] Validated against ≥2 real de-identified reports.
- [ ] Unblocks CR-4..13 (rows in LP-135).

## LP-130 — AUS / DU findings schema *(highest leverage)*
**Type:** Story · **Epic:** D · **Depends:** LP-117
**Summary:** Recommendation, data-used, conditions list, red-flags.
**Acceptance criteria:**
- [ ] Recommendation enum + conditions list + data-used extracted.
- [ ] Feeds AS-10's month-count requirement.
- [ ] Unblocks AU-1..4. Validated against a real findings sample.

## LP-131 — Appraisal (URAR/UAD) schema
**Type:** Story · **Epic:** D · **Depends:** LP-117
**Summary:** Subject, valuation, condition rating, flood zone, comps — tolerant of UAD 2.6 + 3.6.
**Acceptance criteria:**
- [ ] appraised_value, condition_c (C1-C6), flood_zone, effective_date extracted.
- [ ] Handles UAD 2.6 and 3.6 (Nov 2026 cutover).
- [ ] Unblocks PR-2 (fully), PR-4/5/6/7, IN-14, DT-4; feeds IH-5.

## LP-132 — Flood determination (FEMA SFHDF) schema
**Type:** Story · **Epic:** D · **Depends:** LP-117
**Summary:** Zone, in-SFHA flag, community/map, LOMC. Small, standardized.
**Acceptance criteria:**
- [ ] `in_sfha` + `flood_zone` extracted reliably.
- [ ] Unblocks IH-5, IH-6.

## LP-133 — Insurance typed sub-model (EXTEND — mortgagee is the gap)
**Type:** Story · **Epic:** D · **Depends:** LP-116
**Summary:** Add a typed insurance sub-model. Per LP-116, coverage amount and carrier already come through as generic fields; the real gaps are MORTGAGEE and typed structure.
**Work:**
- Add a typed insurance sub-model (dwelling coverage, mortgagee {lender, loan #}, effective/expiration dates, premium, doc_type dec/binder).
- Wire it so IH-1/IH-2/IH-3/IH-4/DT-5 read typed fields, not generic financial fields.
  **Acceptance criteria:**
- [ ] Typed insurance sub-model captures dwelling coverage, MORTGAGEE (the gap), dates, premium.
- [ ] Completes IH-1..4, DT-5 (feeds LP-127; IH-2 mortgagee unblocked).
- [ ] Validated against a real de-identified dec page + binder.

## LP-134 — Title commitment (ALTA) schema
**Type:** Story · **Epic:** D · **Depends:** LP-117
**Summary:** Schedule A (structured), B-I requirements (list), B-II exceptions (list).
**Acceptance criteria:**
- [ ] Schedule A fields (vesting, legal description, parties, amounts) extracted.
- [ ] B-I/B-II itemized (liens flagged).
- [ ] Unblocks TI-1..6, RE-1.

## LP-135 — Rule rows unblocked by schemas
**Type:** Story · **Epic:** D · **Depends:** LP-129..134
**Summary:** Add the registry rows each landed schema unblocks (mostly config, reusing evaluators).
**Work:** CR-4..13 (after LP-129) · AU-1..4 (after LP-130) · PR-4/5/6/7, IN-14, DT-4 (after LP-131) · IH-5/6 (after LP-132) · TI-1..6, RE-1 (after LP-134). Extend `reconcile_list` for tradelines / AUS-conditions.
**Acceptance criteria:**
- [ ] Each unblocked rule added as a row; runs only when its schema data is present.
- [ ] Until a schema lands, its rules stay **awaiting-data**, never passing.
- [ ] ⚠️ **Priya-validate:** seasoning windows (CR-6), min-score (CR-7), student-loan calc (CR-9).

---

# EPIC E — Newly-Scoped IN Rules (LP-136..138) — *priority-gated by LP-117*

## LP-136 — Condo / HOA epic + condo-doc schema
**Type:** Story · **Epic:** E · **Depends:** LP-117 (volume)
**Rules:** CO-1..5, IH-7 condo master policy, IH-8 wind/hail.
**Acceptance criteria:**
- [ ] Condo-doc schema extracts questionnaire answers, master policy, budget/reserves.
- [ ] Priority set by condo volume (LP-117) — defer within V1 if low.
- [ ] ⚠️ **Priya-validate:** reserve %, delinquency/concentration thresholds.

## LP-137 — Uncommon income types
**Type:** Story · **Epic:** E · **Depends:** LP-117 (mix)
**Rules:** IN-13 continuance, IN-14 rental support, OC-3 investment rental, AS-11 retirement/stock liquidation. *(IN-12 self-employment noted below.)*
**Note (LP-116):** TAX RETURNS are EXCLUDED from extraction entirely (confirmed carve-out) — so IN-12 (self-employment) and IN-14's Schedule-E path are GENUINE BUILDS (new typed sub-models + the self-employed calculator), not extends. Award letters / retirement statements: confirm extraction status before building IN-13/AS-11.
**Acceptance criteria:**
- [ ] IN-12 self-employment = a real build (tax-return typed sub-model + self-employed calculator) — scope separately if pursued.
- [ ] IN-14 rental via Schedule E depends on tax-return extraction (excluded today).
- [ ] Priority set by borrower mix (LP-117).
- [ ] ⚠️ **Priya-validate:** continuance window (typically 3 yrs).

## LP-138 — Product-boundary rules
**Type:** Story · **Epic:** E
**Rules:** ID-7 marital/title, ID-8 citizenship/residency, ID-9 POA (AI/judgment), PC-9 financing contingency, DT-7 ATR completeness.
**Acceptance criteria:**
- [ ] Build the clean ones (ID-7, ID-8).
- [ ] Evaluate ID-9/PC-9/DT-7 for value; DT-7 may be redundant — decide and document.

---

# EPIC F — Verification Trust Surface (LP-139..142) — *the 3.9 work*

> Three-state view, rich satisfied entries, paired-snapshot history. Strengthen the trust surface before later phases. Can run right after Epic B (depends on the engine's three-state output, not on specific rules).

## LP-139 — Backend: capture passed & awaiting-data results per run
**Type:** Story · **Epic:** F · **Depends:** LP-119, LP-121
**Summary:** The engine records, per run, which applicable rules PASSED (Satisfied) and which couldn't run for missing data (Not-yet-checkable), alongside findings.
**Work:**
- Use the applicability filter's applicable + awaiting-data sets (LP-119).
- For runnable rules, record pass/fail; for pass, capture rich detail (what checked, why good, why matters, source docs/stated values via provenance LP-114.1).
- Dedup satisfied & awaiting-data by rule × subject (mirrors findings dedup LP-93/94).
  **Acceptance criteria:**
- [ ] Each run yields three deduped lists: findings / satisfied / not-yet-checkable.
- [ ] Satisfied entries carry what-checked, why-good, why-matters, source (docs/stated).
- [ ] Awaiting-data entries name the missing document/data — never shown as passed.

## LP-140 — Backend: verification history as paired snapshots
**Type:** Story · **Epic:** F · **Depends:** LP-139
**Summary:** Each "Run verification" persists all three lists as a retrievable paired snapshot.
**Work:**
- Extend the Verification run record to store findings + satisfied + not-yet-checkable.
- Store EXPLICITLY (not reconstructed) so history stays accurate as rules/thresholds change.
- Retrieval API by run.
  **Acceptance criteria:**
- [ ] Every run creates a history entry snapshotting all three lists.
- [ ] Selecting a past run returns that run's exact three lists (not recomputed under today's rules).
- [ ] Input-fingerprint short-circuit (LP-78.1) still applies.

## LP-141 — Frontend: two-tab, three-section verification view
**Type:** Story · **Epic:** F · **Depends:** LP-139 · reads frontend-design SKILL
**Summary:** Tab 1 "Needs attention" (Findings + Not-yet-checkable, separate sections); Tab 2 "Satisfied."
**Work:**
- Findings section unchanged (four-part cards).
- Not-yet-checkable: distinct, honest ("couldn't check — {document} missing"), never styled as pass/fail.
- Satisfied: rich entries (what/why-good/why-matters/source), collapsible, provenance doc chips.
  **Acceptance criteria:**
- [ ] Three sections across two tabs exactly as specified.
- [ ] Not-yet-checkable visually distinct from Findings and Satisfied.
- [ ] Satisfied entries show substance + source, not bare checkmarks.
- [ ] Aggression dial still governs finding display; satisfied/awaiting unaffected by the dial.

## LP-142 — Frontend: history navigation
**Type:** Story · **Epic:** F · **Depends:** LP-140, LP-141
**Summary:** Select any past run → load its paired snapshot for all three lists.
**Acceptance criteria:**
- [ ] A history selector lists runs (timestamp, counts).
- [ ] Selecting a run loads its findings + satisfied + not-yet-checkable together.
- [ ] Current/latest run clearly marked.
- [ ] Viewing history is non-destructive (never re-runs).

---

# EPIC G — Hardening (LP-143)

## LP-143 — Golden-file eval set (guards the flat-extraction silent-misread risk)
**Type:** Story · **Epic:** G · **Depends:** LP-123.5 (facts wired)
**Summary:** A durable measurement layer — real de-identified files with known-correct findings — to catch regressions and silent extraction misreads as the rule set grows.
**Description:** The LP-116 audit escalated a real risk: the flat monolithic extraction has NO per-field plausibility check and no per-field confidence, so a field can extract WRONGLY and produce a confidently-wrong finding with no signal. As rules multiply, this is the main way trust silently erodes. A golden-file eval set is the guard — not gold-plating.
**Work:**
- Assemble a small set of real de-identified files (start with LF-6T3N) with known-correct expected findings / satisfied / not-checkable lists.
- A harness that runs verification and diffs actual vs. expected, flagging regressions and extraction misreads.
- Run it as a check when rules or the fact-builder change.
  **Acceptance criteria:**
- [ ] ≥1 golden file with a known-correct expected three-list outcome.
- [ ] The harness diffs actual vs. expected and reports regressions.
- [ ] Catches a deliberately-introduced wrong extracted value (proves the silent-misread guard works).
- [ ] Documented as the measurement backbone for all future rule additions.

---

# Dependency summary

```
EPIC A (LP-115..117)  audit + Priya + confidence direction   <- gate, do first
      |
      v
EPIC B (LP-118..123)  registry + evaluators + runner
                      (employer fix lands here as the 1st DET-FUZZY rule, LP-120)
      |
      +--> EPIC C (LP-124..128)  seed ~30 rules
      |
      +--> EPIC D (LP-129..135)  blocker schemas + unblocked rows   [gated by LP-117]
      |
      +--> EPIC E (LP-136..138)  newly-scoped rules                 [gated by LP-117]
      |
      +--> EPIC F (LP-139..142)  verification trust surface (3.9)
```

**Notes:**
- **The employer fix (original LP-115 intent) is now LP-120** — built once as the reference DET-FUZZY rule proving the new engine, not a throwaway hand-coded fix. It doesn't get run standalone; it lands with the engine.
- **EPIC F can run right after EPIC B** (depends on the engine's three-state output, not specific rules) — strong candidate given the "strengthen verification first" priority.
- D/E estimates firm up after LP-117 (Priya formats/volume).
- Every ⚠️ **Priya-validate** criterion is a hard gate: rule ships as config, goes live at full confidence only after Priya confirms the number.
```


Lets create a claude code prompt for LP-118.6 — The fact namespace.. Before prompting provide detail on the ticket. Once prompt finish give info on what to watch for after running the prompt. Remember For each ticket after implementation document in markdown file about what is that ticket what are acceptance criteria and what we worked, with all assumption or decision we made. If this work is related to frontend design, use claude frontend skill or any other necessary skill. Also all stages can run sequential with auto approval to move forward in implementation. Later commit the change with proper commit message but do not push to github, I will do it manually.
