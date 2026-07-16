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

LP-344 — Priya's activation bars (D2)

"How often can this tag be wrong before you'd stop trusting it?"
Risk-weighted per tag: income.documented_monthly feeds a deterministic fraud verdict; id.name_normalized feeds a ratification-pending judgment
Not a code ticket — encode her answers afterward
Gates every activation decision in Epic 3


EPIC 2 — EXTRACTION FIELDS
Why: 3 rules blocked on fields the extractors don't pull. Pattern confirmed across two waves.
LP-345 — Bank statement page count

bank_statement.py extracts holder/bank/account/type/period/balances/totals — no page count
Add "Page X of Y" → unblocks AS-9 (missing pages)

LP-346 — Pay stub / VOE employment dates

employment_start / employment_end don't exist → unblocks IN-4 (employment gap) and IN-7 (job change)

LP-347 — Loan Estimate / Closing Disclosure extraction

The biggest of the three. No LE/CD extraction exists at all
closing_costs blocks AS-3 (cash-to-close), and will block DTI and closing rules in later waves
New extractor, not a field addition


EPIC 3 — ACTIVATION
Why: 21 rules authored, evaluated, correct — and switched off.
LP-348 — Declared recipe dependencies

_required_ai_groups traces a rule's direct load-bearing tags — so a derived tag's feeding AI groups are never marked required, and the orchestrator never runs them
A derived tag should declare its depends_on so wiring is generic
Unblocks IN-1/3/5/10's wiring (they still need calibration too)

LP-349 — Per-borrower document context

The borrower subject's build_context reads MISMO only — not the borrower's documents
A per-borrower judgment can't see the job history it must reason over
Blocks IN-7, IN-13, IN-14

LP-350 — IN-3 per-borrower

IN-3 carries PIN #1's masking (a loan-level YTD aggregate hides one borrower's inflated YTD)
Mirrors IN-1's recipe (LP-332 built the pattern)
Must land before IN-3 activates — or you re-ship the bug LP-332 fixed

LP-351 — IN-11 set-membership operand (PIN #2)

IN-11 fires for any income lacking 2-year history, not just variable income — the operand algebra has no income.type in {bonus, overtime, commission}
A salaried borrower with a new job false-fires today
Decide: a set-membership operand, or a judgment reframe

LP-352 — IN-12 self-employment calculator wiring (PIN #3)

compute_self_employed_income exists in services/ but isn't in snapshot.calculations
IN-12 is a minimal 2-year-return check; the real 1084 cash-flow analysis isn't modeled
The calc operand already generalizes (proven by AS-1 and AS-4) — no new primitive

LP-353 — The activation pass

With Epics 1-3 landed: which rules genuinely activate?
Per rule: activated, or inert + the precise reason (LP-333's bucket model)
The discipline holds: no rule ships an uncalibrated AI tag; no rule that uniformly couldnt_checks
The number that matters — how many of the 21 go live?


EPIC 4 — DEFERRED SHAPES
Why: 4 rules can't be authored. Each needs a one-time reusable primitive.
LP-354 — The multi-value gather leg

A judgment reasoning over a multi-valued gathered fact (several paystubs for one borrower)
Unblocks IN-6 (paystub↔W-2 coverage) and any future judgment-over-a-set

LP-355 — IN-6: paystub ↔ W-2 coverage

Bidirectional set-coverage — a borrower with two jobs should show two employers; the sets legitimately differ
Judgment over the gathered sets (not a rigid set-diff, which false-fires on every second job)
Depends on LP-354

LP-356 — AS-8: statement chaining (pairwise-sequential)

ending_balance[n] == beginning_balance[n+1] across sorted statements — fits no existing evaluator
LP-336 gave it per_account + resolve_accounts; it needs its shape
Decide: a sequential_pairwise evaluator or a derived per-account "chain-breaks" tag

LP-357 — Borrower-set reconciliation

A belongs_to borrower not in MISMO (or a MISMO borrower on no document) isn't evaluated — the borrower subject enumerates MISMO, the judgment enumerates belongs_to
Today it fail-closes (honest); a union of the two sets is the fix
Small


EPIC 5 — THE UI
Why: ~31 rules produce honest, provenance-carrying findings that no human has ever seen.
LP-339 — The findings surface (thin, read-only) ← already drafted

Four tabs (§8's five outcomes → four tabs), a finding list, a finding detail with provenance
One file (LF-6T3N), read-only, no actions
The honesty contract in the UI: couldnt_check blocks and lives in Tab 1 — never rendered as a pass, never filed under Satisfied or Not-applicable. Tab 3 (subject left) ≠ Tab 4 (never relevant)
The provenance is the product — each load-bearing tag with its value, confidence, and the AI's reasoning
Shows LF-6T3N's real findings, however sparse. No seeded fakes
Uses the frontend-design skill

LP-358 — Finding actions (§10)

Resolve / override / accept-risk / add-note / request-docs
The append-only event log per finding (LP-316/322)
Depends on LP-339 teaching us whether the model is right

LP-359 — Upload + re-run

Trigger a verification run from the UI; watch it complete
Makes the system usable without a developer

LP-360 — Multi-file + auth

The loan list; who's looking at what
The point at which Priya can actually use it


The critical path
LP-341 (Priya labels) ─┐
LP-342 (fuzzy scoring) ─┼→ LP-344 (bars) → LP-353 (activation) → LP-339 (UI)
LP-343 (prompt audit) ─┘
Epics 2 and 4 run in parallel — they don't block the UI.
My honest recommendation on order

LP-341 — Priya's labels. It's a conversation, it's the artifact you've been batting toward, and it unblocks the whole trust chain.
LP-339 — the UI slice. Do it in parallel, not after. It'll teach you whether the four-tab model is right while calibration runs, and it's the thing that makes Priya's session concrete.
Then Epic 1's remainder → Epic 3 → activation.

Epics 2 and 4 can wait. They're 7 tickets that unblock 7 rules. Epic 1 + 3 unblock ~15.
And note what's not here: waves 4-10 (DTI, Title, Insurance, Condo, small families, Credit, Property). ~90 rules, ~20 more tickets, plus the blocker-document extractors. That's after the UI — because by then you'll know whether the findings model is right, and you won't be building 90 more rules into a shape nobody's validated.where are tickets for different waves or categories like Assets,  Credit, Property, DTI, Title, Insurance, Condo, Purchase/Program + MI + AUS + Fraud + Occupancy remainder (PC/PE/MI/AU/FR/OC)~30Several small families; could be groupedPlus CL (closing) and DC (disclosures) — mostly out-of-scope per the earlier classification, so they'd resolve to not_applicable rather thaYou're right — I cut them deliberately at "till UI" per your ask, but they belong in the plan. Here's the rest.

EPIC 6 — THE REMAINING WAVES
Each wave = 3 tickets (-A recon → -B author → -C eval). Proven across three waves: 7 → 3 → 3.
LP-361/362/363 — Wave 4: DTI (~7 rules)

-A recon — the gate; rules by kind/shape; tags exist vs new; thresholds
-B author — reads the wired DTI calculator (the calc operand generalizes — proven by AS-1 and AS-4's case-12). No new primitive predicted
-C eval — full matrix; case 12 real (gated DTI → couldnt_check)
Risk: multi-scenario DTI (with/without a retained property) may want a small operand
Dependency: LP-347 (LE/CD extraction) — DTI needs closing_costs for some rules
Thresholds: DTI limits are a matrix (occupancy × program × LTV) → ADR-278's derived-tag pattern

LP-364/365/366 — Wave 5: Title (~6 rules)

Vesting, liens, commitment presence, chain of title
Shapes covered: LP-329 applicability + LP-330 expected-absence + consistency
ID-7 (title vesting) is already live — the family exemplar

LP-367/368/369 — Wave 6: Insurance / Hazard (~8 rules)

Coverage adequacy, binder presence, flood determination, HOA master policy
Coverage-vs-replacement-cost is arithmetic → a derived recipe (ADR-273)
Note: the insurance binder gates the DTI's housing expense (LP-318) — this family and DTI interact

LP-370/371/372 — Wave 7: Condo (~5 rules)

Warrantable vs non-warrantable — not merely "is the questionnaire present"
Owner-occupancy %, HOA delinquency, litigation, single-entity ownership
Priya's team works on condos — she's the authority here
Risk: the questionnaire may need extraction (bucket C)

LP-373/374/375 — Wave 8: The small families (~30 rules)
Grouped: PC (purchase contract) · PE (program eligibility) · MI (mortgage insurance) · AU (AUS/DU findings) · FR (fraud indicators) · OC (occupancy remainder)

OC-2 is already live — the exemplar
MI coverage % is a matrix (LTV × program × term) → derived tag
AU is blocked — DU/AUS findings are a blocker document (see Epic 7)
Possibly 2 waves — 30 rules across 6 families may not fit one -B


EPIC 7 — BLOCKER DOCUMENTS
Why: Credit (~13) and Property (~8) cannot activate until these exist. This is an extraction project, not a wave.
LP-376 — LP-143: the golden-file eval set

Must land alongside the first blocker extractor, not after
Credit report, DU/AUS, appraisal have no independent cross-check source — unlike a pay stub (cross-checked against MISMO stated income), a silent misread has nothing to catch it
Hand-labeled ground truth per document type
This is the whole reason blocker docs are different

LP-377 — Credit report extractor

PDF-only, deeply nested: repeating tradelines, scores, public records, inquiries
"Schema complexity, not PDF complexity" — the existing AI-PDF path handles pay stubs/W-2s/statements fine
Blocker-fed rules carry computed lower confidence until eval-validated

LP-378 — DU/AUS findings extractor

Findings, conditions, risk factors
Feeds the AU family (Epic 6)

LP-379 — Appraisal extractor

Must handle both UAD 2.6 and 3.6 visual layouts through the Nov 2026 cutover
Value, condition, comparables, repairs required

LP-380/381/382 — Wave 9: Credit (~13 rules)

Depends on LP-377 + LP-376
Tradeline analysis, derogatory events, disputes, inquiries, score thresholds
Seasoning periods (bankruptcy/foreclosure) → Priya thresholds

LP-383/384/385 — Wave 10: Property (~8 rules)

Depends on LP-379 + LP-376
Appraised value vs contract, condition, repairs, comparables


EPIC 8 — OUT OF SCOPE (resolve, don't build)
LP-386 — CL (closing) + DC (disclosures) disposition

Per the LP-301 classification, most are out_of_scope → not_applicable (Tab 4)
Verify the classification rather than assume it — rule_kinds.csv is the gate of record
The honesty contract: not_applicable must mean "irrelevant to this file's nature" — never "we couldn't check it"
Likely 1 ticket: confirm the disposition, ensure they resolve correctly, document why
