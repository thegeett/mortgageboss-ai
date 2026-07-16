Nine categories left, covering roughly 120 rules. Here's the honest breakdown.
Done (1 of 10)
Identity (ID-1..ID-10) — nine rules live, ID-10 correctly out-of-scope. Pending LP-323-ID-C (the eval).
Plus two orphans from before the wave system: AS-1 (assets) and OC-2 (occupancy) — built and validated, but their families aren't done.
Remaining (9 categories, ~120 rules)
CategoryRulesNotesIncome (IN)~14Biggest family. Natural wave 2 — exercises consistency, dates, per-borrower judgment, and calculator inputs

Assets (AS)~11 moreAS-1 done; AS-2..AS-12 remain

Credit (CR)~13Blocked — credit report is a blocker document (PDF-only, nested schema, no cross-check)

Property (PR)~8Blocked — appraisal is a blocker document (UAD 2.6/3.6 cutover)

DTI (DT)~7Depends on the calculators; LP-318's Caveat A is relevant

Title (TI)~6

Insurance/Hazard (IH)~8

Condo (CO)~5Priya's team works condos — warrantable vs non-warrantable, not just questionnaire-presence

Purchase/Program + MI + AUS + Fraud + Occupancy remainder (PC/PE/MI/AU/FR/OC)~30Several small families; could be grouped

Plus CL (closing) and DC (disclosures) — mostly out-of-scope per the earlier classification, so they'd resolve to not_applicable rather than needing waves.


2. The remaining waves (~21 tickets)
   CategoryRulesTicketsAssets (AS-2..AS-12)~113DTI~73Title~63Insurance/Hazard~83Condo~53Small families (program/MI/AUS/fraud/occupancy)~306
3. Blocked on blocker documents (~6 tickets + extractors)
   Credit (~13) and Property (~8) cannot activate until the credit report, DU/AUS findings, and appraisal are extractable. PDF-only, deeply nested schemas, no independent cross-check source. Needs the golden-file eval set (LP-143) built alongside the first extractor. That's 3-4 extractor tickets + 6 wave tickets.
4. The product (unestimated, and the biggest)

The UI — four tabs, finding detail, upload + re-run, resolve/override/waive actions. Doesn't exist. This is the gap between an engine and something Priya can use.
Priya's session — ~40 items by the time all waves land
Breadth validation — everything is validated on LF-6T3N (one conventional purchase) + synthetic. No jumbo, FHA, condo, self-employed, or refinance corpus.
The mortgageboss-synthetic tool completion


EPIC 1 — CALIBRATION & TRUST
Why: 15 of 21 inert rules are gated on this. The engine's correctness is proven; its trustworthiness isn't.
LP-341 — Priya's judgment labels + the full calibration re-run

Fill lf6t3n-labels-judgment.csv (170 rows) with Priya — txn.apparent_category (50), has_identified_source (16), income.type/is_declining/has_2yr_history/continuance_3yr, stmt.is_reserve_eligible, asset.liquidation_terms
The 2 id.current_address_type rows — checks LP-335's fix against a real driver's license (currently only tested on a synthetic fixture)
Re-run with LP334_LIVE=1 → the complete picture in one measurement
Not a code ticket — a session with Priya + a run
Output: per-tag numbers + failing cases + reasoning

LP-342 — Fuzzy scoring for free-text tags (FINDING-2)

String equality can't score id.name_normalized, id.address_normalized, txn.counterparty, txn.source_reference — Maria Garcia-Lopez vs Maria Garcia Lopez is a valid rendering, not an error
Decide the method: AI-judge comparison, human review of recorded detail, or a normalized-distance metric
Without this, 4+ tags are permanently unmeasurable

LP-343 — The prompt-exemplar audit

Two found so far: LP-335's id_address ("prior = e.g. an old driver's-licence address") and LP-340's income_employer ("drop Inc/LLC noise where it aids matching")
Both were downstream rule concerns smuggled into tag prompts — a systematic authoring error, not bad luck
Audit every AI group prompt: txn_stage_a (feeds live AS-1), the income groups, stmt_facts, asset_facts
The rule: a tag reports what the document states; the rule does the judging
Report, don't tune — each finding gets its own fix ticket

EPIC 1 — CALIBRATION & TRUST
LP-344 — The two-prompt drift (measurement validity) ⬅ highest priority

Two prompts produce the same txn.* tags: the standalone STAGE_A_TRANSACTION_SYSTEM_PROMPT (what LIVE AS-1 runs) and the generic txn_stage_a YAML group
LP-337's 98%/n=50 measured the YAML group — not the prompt AS-1 uses
They already differ (the standalone defines apparent_category; the YAML doesn't)
This is LP-326's deferred txn.* migration coming due
Converge them, or make the live path consume the generic group → the measured prompt becomes the shipped prompt

LP-345 — Priya's judgment labels + full calibration re-run

Fill lf6t3n-labels-judgment.csv (170 rows) with Priya
The 2 id.current_address_type rows → LP-335's fix on a real driver's license
Tests F1 (has_identified_source, 16 rows) and F2 (income tags, 8 each) against real content
Not a code ticket — a session + a run

LP-346 — F1: Stage-B sourcing "no vs unknown"

Prompt: "an unsourced deposit is exactly the signal downstream rules must catch, so do not soften it to 'unknown'" — a purpose hedge on a LIVE AS-1 feed
Equates "I was given no candidates" with "no source exists" → false-positive on AS-1 when the search is incomplete
Principle: "the file shows no source" ≠ "I wasn't shown the source"
Do after LP-345 — the audit rated it UNSURE and wants a measured check first

LP-347 — F2: qualifying_monthly's undefined convention

The prompt asks the tag to apply "continuity/averaging" — an underwriter's determination, undefined
Latent AS-1 false-green: over-stated qualifying income raises the 50% threshold → a large unsourced deposit slips under
Mitigated today (AS-1 reads MISMO income, not the tag) — HIGH if wired
Either make it a documented figure the rule adjusts, or define the convention (LP-340's pattern)

LP-348 — F6: stmt.is_reserve_eligible

The tag judges reserve eligibility — an agency determination, underspecified
Account type is a fact; reserve-eligibility is a rule
Pre-empts the Priya-pending retirement discount

LP-349 — F3 + F4: small prompt fixes

voe_present has no unknown → forces fabrication on ambiguous docs
id_title — a measured check, not a prompt edit (the sanctioned deterministic-over-enum pattern, but it's ID-7's LIVE verdict)

LP-350 — Priya's activation bars (D2)

"How often can this tag be wrong before you'd stop trusting it?" — risk-weighted per tag
Gates every activation decision


EPIC 2 — EXTRACTION FIELDS
LP-351 — Bank statement page count → unblocks AS-9
LP-352 — Pay stub / VOE employment dates → unblocks IN-4, IN-7
LP-353 — Loan Estimate / Closing Disclosure extraction

No LE/CD extraction exists at all; closing_costs blocks AS-3 and later DTI


EPIC 3 — ACTIVATION
LP-354 — Declared recipe dependencies

_required_ai_groups traces only direct load-bearing tags → a derived tag's feeding AI groups never run
Unblocks IN-1/3/5/10's wiring

LP-355 — Per-borrower document context

The borrower subject's build_context reads MISMO only, not the borrower's documents
Blocks IN-7, IN-13, IN-14

LP-356 — IN-3 per-borrower

Carries PIN #1's masking (loan-level YTD aggregate) — must land before IN-3 activates

LP-357 — IN-11 set-membership operand (PIN #2)

Fires for any income lacking 2-yr history, not just variable — false-fires on salaried today

LP-358 — IN-12 self-employment calculator wiring (PIN #3)
LP-359 — The activation pass

The number that matters: how many of the 21 go live?


EPIC 4 — DEFERRED SHAPES
LP-360 — The multi-value gather leg
LP-361 — IN-6: paystub ↔ W-2 coverage (depends on LP-360)
LP-362 — AS-8: statement chaining (pairwise-sequential)
LP-363 — Borrower-set reconciliation

EPIC 5 — THE UI
LP-364 — The findings surface (thin, read-only) — was drafted as LP-339

Four tabs, finding list, finding detail with provenance
One file, no actions, real findings only

LP-365 — Finding actions (§10)
LP-366 — Upload + re-run
LP-367 — Multi-file + auth

EPIC 6 — WAVES 4-8

LP-368/369/370 — DTI (~7) (needs LP-353)
LP-371/372/373 — Title (~6)
LP-374/375/376 — Insurance (~8)
LP-377/378/379 — Condo (~5)
LP-380/381/382 — Small families PC/PE/MI/AU/FR/OC (~30)

EPIC 7 — BLOCKER DOCUMENTS

LP-383 — LP-143 golden-file eval set
LP-384 — Credit report extractor
LP-385 — DU/AUS extractor
LP-386 — Appraisal extractor (UAD 2.6 + 3.6)
LP-387/388/389 — Wave 9: Credit (~13)
LP-390/391/392 — Wave 10: Property (~8)

EPIC 8

LP-393 — CL/DC out-of-scope disposition
