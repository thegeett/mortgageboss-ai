# Phase 3.5 — Vertical Build Plan (Jira Tickets, LP-119 → LP-143)

**Strategy:** Build the pipeline once (proven on one rule), then build rules one at a time end-to-end (applicability → evaluator → test), in dependency order. Cross-cutting work (extractors, UI, eval set) stays horizontal and each unblocks a wave of rules.

**The repeating per-rule pattern (every LP-R ticket below follows this):**
- Save the rule's authored applicability (scope / triggers / required_inputs) into the seed → `verification_rules` table
- Build any missing derived fact the rule needs into the fact-builder (as part of the rule)
- Implement the evaluator (produces finding / satisfied) following the LP-120 pattern
- Test end-to-end on a real file (finding / satisfied / couldn't-check all exercised)
- Document `docs/tickets/LP-XXX.md`; ⚠️ threshold rules → confirm number with Priya before validated=true
- Commit locally, do not push

Source of truth for each rule's applicability = `rule_applicability_authored.md`.

---

# EPIC 1 — Pipeline Foundation (build once, via the first rule)

## LP-119 — Applicability filter engine (thin slice, proven on rule #1)
- Build the three-valued applicability evaluator: reads a rule's scope / triggers / required_inputs from the `verification_rules` table against the fact snapshot
- Returns one of: **doesn't-apply** (scope/trigger false), **couldn't-check** (needed data missing / unknown), **ready-to-run** (applies + data present)
- General engine — reads applicability as DATA, no per-rule logic hardcoded
- Prove on the first rule + a synthetic "missing data → couldn't-check" case
- Establishes the honesty contract: unknown → couldn't-check, never a silent pass

## LP-120 — Evaluator framework + first evaluator (thin slice, sets the pattern)
- Define the evaluator contract every rule follows: read snapshot → apply check → return **finding** or **satisfied** (with confidence + provenance)
- Implement the first rule's evaluator as the reference implementation
- Include the DET-FUZZY confidence approach + the employer-name normalization fix as the pattern for fuzzy-matching rules
- Primary job: **set the pattern** so rules #2–N are fill-in-the-pattern, not reinvention

## LP-121 — Runner: snapshot → filter → evaluator → result (thin slice, end-to-end)
- Wire the full pipeline for one rule: build snapshot → applicability filter (LP-119) → evaluator (LP-120) → collect into the four buckets (finding / couldn't-check / satisfied / doesn't-apply)
- Prove end-to-end on rule #1 against a real file (LF-6T3N)
- After this: engine exists — adding a rule = applicability + evaluator only, no plumbing changes

**MILESTONE:** one rule runs end-to-end; the engine can run any rule.

---

# EPIC 2 — Wave 1 Rules (dependency-free, buildable immediately)

> Each ticket = the repeating per-rule pattern. Rule #1 also validates the pipeline (pick an already-live rule so its output can be checked against known-correct behavior).

## LP-122R — AS-5 Gift-letter present *(RULE #1 — already live; validates pipeline)*
- Applicability: trigger on `assets[].is_gift == true`; gift letter is the check-target (not a required input)
- Evaluator: gift funds present → is a complete gift-letter + transfer trail present? → finding / satisfied
- Validate the new-engine result matches the current live rule's output on LF-6T3N

## LP-123R — AS-8 Bank-statement continuity *(already live)*
- Applicability: trigger on 2+ bank statements; needs transactions + statement periods
- Evaluator: ending balance chains into next beginning balance? → finding / satisfied

## LP-124R — Employer-count matches income items *(already live)*
- Applicability: needs borrower employers + income items
- Evaluator: documented employer count reconciles with stated → finding / satisfied

## LP-125R — AS-1 Large-deposit sourcing ⚠️Priya-validated(>50%)
- **Build the `transactions[].is_large_deposit` derivation into the fact-builder** (amount vs 50% of monthly income) as part of this rule
- Applicability: needs bank statements (no statements → couldn't-check); trigger relevance = a large deposit exists
- Evaluator: each large deposit sourced/explained? → finding / satisfied

## LP-126R — DT-1 DTI within limit ⚠️Priya-threshold
- Applicability: needs `computed.back_end_dti` (uncomputable → couldn't-check)
- Evaluator: DTI ≤ program limit? → finding / satisfied (limit = pass/fail logic, Priya-confirmed)

## LP-127R — PR-1 LTV/CLTV/HCLTV within limits ⚠️Priya-threshold
- Applicability: needs `computed.ltv/cltv/hcltv` (no appraised value → couldn't-check)
- Evaluator: ratios ≤ program limits? → finding / satisfied

## LP-128R — MI-1 MI required when LTV>80 ⚠️Priya-threshold(80)
- Applicability: conventional + trigger `computed.ltv > 80`
- Evaluator: MI present? → finding / satisfied (MI presence is the check-target)

## LP-129R — MI-4 FHA MIP correct
- Applicability: FHA only; needs `computed.mi_monthly`
- Evaluator: upfront + monthly MIP correct? → finding / satisfied

## LP-130R — AS-4 Reserves adequacy ⚠️Priya-threshold
- Applicability: needs `computed.reserves_months`
- Evaluator: reserves ≥ required months? → finding / satisfied

## LP-131R — CL-1 Rate lock not expired ⚠️Priya-threshold
- Applicability: needs `file.rate_lock_expiration` + `file.closing_date`
- Evaluator: lock valid through closing? → finding / satisfied

## LP-132R — AS-6 Account ownership
- Applicability: needs `assets[].holder_name` + borrower names
- Evaluator: each account in a borrower's name? → finding / satisfied (fuzzy name match)

## LP-133R — AS-2 Earnest money traceable
- Applicability: purchase only; needs transactions + bank statement
- Evaluator: EMD traceable to a verified account? → finding / satisfied

## LP-134R — PC-2 Purchase price matches loan
- Applicability: purchase only; needs `property.purchase_price` + `file.loan_amount`
- Evaluator: price consistent with loan terms? → finding / satisfied

## LP-135R — DT-3 MI in DTI ⚠️(fixed: trigger on MI-required)
- Applicability: conventional + `computed.ltv > 80`
- Evaluator: is MI included in the back-end DTI? → finding / satisfied

## LP-136R — Wave-1 remainder (batch)
- Remaining dependency-free rules following the same pattern: PR-3 (property type eligible), OC-1 (occupancy consistent), PE-1/PE-2 (program eligibility / FHA case number), IH-0 (insurance policy present), PR-4A (appraisal present), FR-1 (altered-doc — AI-materialized), FR-6 (cross-source AI pass — already exists)
- Batched because each is small and pattern-identical

---

# EPIC 3 — Wave 2 Rules (need LP-118.8 borrower↔document link)

> **Blocked until LP-118.8 lands.** (LP-118.8 is a separate in-progress ticket — see Epic 6.)

## LP-137R — ID-10 Document name matches a borrower
- Applicability: trigger on documents that have a name; needs `documents[].names` + borrower names
- Evaluator: document name matches a borrower? no-name → genuine; matches nobody → finding

## LP-138R — ID-1 / ID-2 / ID-3 Name / SSN / DOB consistency (per-borrower, batch)
- Applicability: per-borrower; needs stated value + `borrowers[].documents[]`
- Evaluator: each borrower's stated value matches THAT borrower's own documents → finding / satisfied (never cross-borrower)

## LP-139R — IN-5 Employer name consistency (per-borrower)
- Applicability: per-borrower; needs employers + `borrowers[].documents[]`
- Evaluator: each borrower's stated employer matches their own income docs (DET-FUZZY) → finding / satisfied

---

# EPIC 4 — Wave 3 Rules (need small extraction fields)

## LP-140R — AS-7 NSF/overdraft
- **Build `transactions[].is_nsf` extraction** (bank statement) as part of this rule
- Evaluator: overdrafts/NSF present? → finding / satisfied

## LP-141R — AS-9 Missing pages
- **Build `documents[].page_count` extraction** ("page X of Y") as part of this rule
- Evaluator: pages complete? → finding / satisfied

## LP-142R — Pay-stub field rules (batch: IN-2 recency, IN-3 YTD)
- Build `documents[].pay_date` surfacing as needed
- Evaluators: pay stub recent? / YTD consistent with stated income? → finding / satisfied

## LP-143R — Employment-detail rules (batch: IN-4 gaps, IN-6 paystub↔W2 coverage)
- Build employer date-range surfacing as needed
- Evaluators: employment gap? / pay-stub↔W-2 employer coverage? → finding / satisfied

---

# EPIC 5 — Wave 4 Rules (need blocker extractors — each pairs with its extractor)

> Each extractor is built, then the rules it unblocks are built end-to-end right after. Extractors are in Epic 6.

## LP-144R — Credit rule family (after credit extractor)
- CR-4 (undisclosed tradeline), CR-5 (inquiry LOE), CR-6 (derog seasoning ⚠️Priya), CR-7 (min score ⚠️Priya), CR-8 (mortgage history), CR-9 (student loan ⚠️needs is_student_loan flag), CR-10 (collections), CR-11 (judgments), CR-12 (disputes), CR-13 (report validity ⚠️Priya)
- Each = the per-rule pattern, reading `documented.credit_*`

## LP-145R — Appraisal rule family (after appraisal extractor)
- PR-2 (value vs price), PR-4B (complete), PR-5 (condition), PR-6 (validity ⚠️Priya), PR-7 (address), PE-4 (FHA condition), DT-4 (property taxes)

## LP-146R — AUS rule family (after DU findings extractor)
- AU-1 (data matches), AU-2 (conditions), AU-3 (recommendation), AU-4 (rerun)

## LP-147R — Title rule family (after title extractor)
- TI-1..6 (parties, legal description, liens, judgments, vesting, chain), FR-2 (non-arm's-length)

## LP-148R — Flood + Insurance detail rules (after flood + insurance extractors)
- IH-1 (adequacy), IH-2 (mortgagee), IH-3 (effective date), IH-4 (premium), IH-5 (flood determination), IH-6 (flood insurance), IH-8 (wind/hail — also needs geography dimension), DT-5 (insurance in DTI)

## LP-149R — Condo rule family (after condo extractor) ⚠️warrantability
- CO-1 (questionnaire + warrantable), CO-2 (dues consistency), CO-3A/3B (master policy), CO-4A/4B (budget/reserves ⚠️Priya), CO-5 (litigation/delinquency ⚠️Priya), IH-7 (condo master policy), DT-2 (HOA in DTI)

## LP-150R — Self-employment + income-detail rules (after tax-return extractor)
- IN-12A (SE docs present), IN-12B (SE calc ⚠️Priya), IN-13 (other income continuance ⚠️Priya), IN-14 (rental support), IN-1 (stated vs documented income ⚠️Priya 5%), IN-10 (declining income), IN-11 (variable income ⚠️needs flag)

## LP-151R — Remaining rules (batch)
- ID-4 (address consistency — needs current_address wired), ID-6/7/8/9, DT-6/DT-7, OC-2/OC-3, AS-3/AS-10/AS-11/AS-12, PC-1/3/4/5/6/7/8/9, PE-3, RE-1/RE-2, FR-3/FR-4/FR-5, LO-1/LO-2, MI-2/3/5

---

# EPIC 6 — Cross-Cutting Work (horizontal; each unblocks rule waves)

## LP-118.8 — Borrower↔document linking *(IN PROGRESS)*
- Unblocks Epic 3 (Wave 2). Fuzzy "whose document is this" matching; conservative (ambiguous → unassigned)

## LP-152 — Credit report extractor
- Unblocks LP-144R. Nested tradelines / scores / inquiries / public records. Golden-file validated (LP-143)

## LP-153 — DU / AUS findings extractor
- Unblocks LP-146R

## LP-154 — Appraisal extractor (UAD 2.6 + 3.6)
- Unblocks LP-145R. Handles both layouts through the Nov 2026 cutover

## LP-155 — Flood determination extractor
- Unblocks flood rules in LP-148R

## LP-156 — Title commitment extractor
- Unblocks LP-147R

## LP-157 — Insurance typed sub-model (extend, incl. mortgagee)
- Unblocks insurance rules in LP-148R. Adds the missing mortgagee field

## LP-158 — Condo document extractor
- Unblocks LP-149R (with warrantability)

## LP-159 — Tax-return extractor
- Unblocks LP-150R (self-employment + rental)

## LP-160 — Rule params admin UI
- Edit tunable thresholds live (hybrid storage); audited via `rule_change_audit`. Build once threshold rules exist

## LP-161 — Retire dormant threshold engine
- Remove the old dormant path; preserve calculators' threshold-data lookup; rename the colliding `run_verification`

## LP-162 — Verification trust surface (two-tab UI)
- Displays the four-bucket result: findings + couldn't-check (Tab 1 "needs attention", visually distinct) / satisfied (Tab 2, rich) / doesn't-apply (hidden)
- Distinguish "waiting on upload" from "have doc, couldn't read it"; paired-snapshot history
- Buildable once LP-121 produces real results; grows as rules are added

## LP-143 — Golden-file eval set
- Guards silent-misread (extraction, canonicalization, borrower↔doc matching). Grows with each rule; every blocker-fed rule gets eval cases

---

# Build order (the practical sequence)

1. **LP-119 → LP-120 → LP-121** (pipeline, via rule #1 = AS-5)
2. **Epic 2 (Wave 1)** — all dependency-free rules; you have a working engine with ~20 real rules
3. **LP-118.8 finishes → Epic 3 (Wave 2)** — identity family
4. **Epic 4 (Wave 3)** — small extraction fields
5. **Trust surface (LP-162)** — as soon as LP-121 gives real results (strong parallel candidate; do early for visibility)
6. **Extractors (Epic 6) + their rule families (Epic 5)** — pair each extractor with its wave, in priority order (credit first)
7. **LP-160 (params UI), LP-161 (retire dormant), LP-143 (eval set)** — fold in as the rule count grows
8. **LP-151R remainder** — mop up

---

# Notes

- **Rule tickets are small and pattern-identical** — after LP-119/120/121 set the pattern, each LP-R is applicability + evaluator + test. Batch later waves by category to reduce ticket count.
- **Every threshold rule** carries ⚠️Priya — confirm the number before validated=true.
- **Numbering is indicative** — the "R" suffix marks per-rule tickets; renumber to your Jira scheme.
- **The authoring doc stays the source of truth** for each rule's applicability; these tickets implement it in dependency order (not doc order).
