# Blocker Document Extraction Schemas — mortgageboss-ai

What this is. A research-backed specification for the extraction schemas needed to unblock the deterministic (Mode-1) verification rules. Each blocker document below gets: what it is, how standardized it is (schema difficulty), the fields to extract, a proposed schema shape, which rules it unlocks, and the open questions to confirm with Priya before building.

Why schemas, not "extractors." The AI can already read these documents. What's missing is a defined extraction schema per type — the field list + structure that tells the AI what to pull and produces the structured, reliable data deterministic rules compare against. Building a "blocker extractor" = defining and validating that schema against real de-identified samples.

The through-line finding. The highest-value blockers (credit report, AUS findings, appraisal, flood) are also the most standardized — government/industry forms with fixed fields (MISMO credit, UAD/URAR, DU findings, FEMA SFHDF). Standardized source data means the schema is more parse-like and less guess-like, so the extraction is more reliable. Good news: the documents you most want are the ones most amenable to a dependable schema.

Standing caveats.

Schema before rows. Build and validate the schema first; deterministic rule-rows without it are inert (false-green). A blocked rule loaded before its schema must be held in an explicit "awaiting-data" state, never shown as passing.

Every field's reliability is the rule's ceiling. A rule is only as deterministic as its least-reliable extracted field. Where extraction is uncertain (variable layouts), emit lower confidence, don't fire hard.

Confirm format with Priya first. For the two biggest unlocks (credit report, AUS), whether they arrive structured (cheap parse) or PDF (extraction build) decides the entire effort. Ask before building.

Validate against real samples. Don't build a schema against a guessed layout; you need real de-identified examples, or the extractor breaks on the first live file.


# Priority order (by unlock value)


| # | Document | Rules unlocked | Standardization | Schema difficulty |
| --- | --- | --- | --- | --- |
| 1 | Credit report (tri-merge) | ~10 (CR-4..13) | High (MISMO credit) underlying; PDF varies | Low if structured feed; Med-High if PDF |
| 2 | AUS / DU findings | AU-1..4 + informs AS-10 | High (DU/LP structured) | Low-Med |
| 3 | Appraisal (URAR/1004→UAD) | PR-2,4,5,6,7; IN-14; DT-4 | Very high (UAD/XML) | Low if UAD-XML; Med if PDF |
| 4 | Flood determination (SFHDF) | IH-5, IH-6 | Very high (FEMA form) | Low |
| 5 | Homeowners insurance dec/binder | IH-1,2,3,4; DT-5 | Med (varies, but ACORD forms) | Low-Med (may already exist) |
| 6 | Title commitment (ALTA) | TI-1..6; RE-1 | Med (ALTA Sched A/B structure) | Med |
| 7 | Condo / tax / compliance | CO-, IN-12, DC- | Low-Med | Med-High (scope-dependent) |


# 1. Credit report (tri-merge / RMCR) — the biggest unlock

What it is. A merged credit report consolidating Equifax, Experian, and TransUnion into one standardized document. The lender pulls it (not borrower-provided) — so it enters via the credit vendor / LOS, and may already exist in structured form in the LOS. Composed of four sections: applicant information, the infile report, tradelines, and public records (plus scores and inquiries).

Standardization. The underlying data is standardized (MISMO credit reporting); modern mortgage credit reporting integrates directly with LOS, auto-parsing tri-merge data into fields underwriters need, flowing into AUS, DTI calculators, and pricing. So a structured form very likely exists upstream. The rendered PDF varies by vendor (Equifax/Experian/TransUnion resellers), so PDF extraction is harder than parsing the structured feed.

Fields to extract.

Borrower / header:

report ID, report date, credit vendor, report type (tri-merge/RMCR)

borrower name(s), SSN, DOB, current + prior addresses (as reported)

Scores (per bureau):

Equifax score + model, Experian score + model, TransUnion score + model

(derive: representative/middle score, or lower-of-two)

Tradelines (repeating — the core):

creditor/lender name

account type (revolving / installment / mortgage / open)

account number (masked)

date opened, date of last activity/reported

credit limit or original amount

current balance

monthly payment

account status (open/closed/paid/charge-off/collection)

past-due amount

payment history / worst delinquency (30/60/90/120) + dates

months reviewed / terms

responsibility (individual/joint/authorized user)

bureau(s) reporting it

included-in-bankruptcy flag

dispute flag

Public records (repeating):

type (bankruptcy chapter 7/11/13; foreclosure; tax lien; judgment)

filing/discharge date, status, amount, court/reference

(note: since 2017, civil judgments & tax liens largely dropped from bureau reports — capture when present)

Collections (repeating):

original creditor, collection agency, amount, date, status (paid/unpaid), medical flag

Inquiries (repeating):

creditor name, inquiry date, inquiry type (hard/soft)

Proposed schema shape.

credit_report:

meta: {report_id, report_date, vendor, report_type}

borrowers: [{name, ssn, dob, addresses[]}]

scores: [{bureau, score, model}]

tradelines: [{creditor, type, account_number_masked, date_opened,

date_last_activity, credit_limit, original_amount, balance,

monthly_payment, status, past_due, worst_delinquency,

delinquency_dates[], responsibility, bureaus[],

included_in_bankruptcy, disputed}]

public_records: [{type, filing_date, discharge_date, status, amount, reference}]

collections: [{original_creditor, agency, amount, date, status, is_medical}]

inquiries: [{creditor, date, type}]

Rules unlocked. CR-4 undisclosed tradeline (report tradelines vs stated liabilities) · CR-5 inquiry LOE (inquiries vs new accounts) · CR-6 derogatory seasoning (public_records dates) · CR-7 min score (scores → representative) · CR-8 mortgage payment history (mortgage tradelines' delinquency) · CR-9 student loan calc (student tradelines) · CR-10 collections treatment · CR-11 judgments/liens · CR-12 disputes (disputed flag) · CR-13 credit validity (report_date).

Confirm with Priya (blocking). How does the credit report arrive in your workflow — a structured file (credit-MISMO/LOS fields) or only a PDF? Structured → a cheap deterministic parser unlocks all 10 rules. PDF → an AI-extraction schema build (harder, variable layouts). This one answer decides the entire credit-report effort. Also: which vendor(s) does UWM/Sun-West use (fixes the PDF layout if PDF)?


# 2. AUS / DU findings report — highest leverage

What it is. The Desktop Underwriter (DU) Underwriting Findings report: Fannie Mae's automated risk engine output. It is the underwriter's own condition list for this specific loan — every other rule is you guessing what the underwriter wants; this tells you. Divided into sections, each a different message type; also carries the recommendation and the required verification messages / approval conditions.

Standardization. Highly structured. The recommendation is a fixed enum: Approve/Eligible, Approve/Ineligible, Refer with Caution, Out of Scope. You already have a DU MISMO sample (submission side); the findings report is the companion. LOS can deliver an enhanced HTML/structured version (file type 16).

Fields to extract.

Header:

casefile ID, submission date/time, DU version, submission number

recommendation (Approve/Eligible | Approve/Ineligible | Refer w/ Caution | Out of Scope)

risk/eligibility summary

Loan/qualifying data DU used (for reconciliation):

loan amount, LTV/CLTV/HCLTV, purpose, occupancy, property type

qualifying income (total), total expense ratio (DTI), housing ratio

total funds required / reserves required

representative credit score DU used

Verification messages / conditions (repeating — the core):

message ID/code, category (credit/income/asset/property/appraisal/etc.)

message text

required documentation (what the condition asks for)

applies-to (borrower/loan)

Special/red-flag messages (repeating):

data-integrity / potential-red-flag messages (excessive resubmissions, frozen credit, casefile reuse, etc.)

Documentation waivers:

value acceptance (appraisal waiver) offered? income/asset validation (DU validation service)?

Proposed schema shape.

aus_findings:

meta: {casefile_id, submission_datetime, du_version, submission_number}

recommendation: {status, risk_summary}

data_used: {loan_amount, ltv, cltv, hcltv, purpose, occupancy,

property_type, qualifying_income, dti, housing_ratio,

reserves_required, funds_required, representative_score}

conditions: [{message_id, category, text, required_documentation, applies_to}]

red_flags: [{message_id, text}]

waivers: {appraisal_waiver, income_validation, asset_validation}

Rules unlocked. AU-1 AUS-data-matches-documents (data_used vs extracted docs) · AU-2 required conditions collected (conditions[] vs collected docs/needs) · AU-3 recommendation status (recommendation) · AU-4 rerun needed (data_used vs current file). Also feeds AS-10 — the "how many months of statements" requirement comes from the DU conditions, shared with the needs list.

Confirm with Priya. How do DU findings arrive — the structured/HTML findings report, or a PDF printout? Do you have a real findings report sample (not just the submission MISMO)? Is it always DU, or also LP (Loan Product Advisor) for some loans?


# 3. Appraisal (URAR / Form 1004 → UAD 3.6) — standardized form

What it is. The Uniform Residential Appraisal Report — the appraiser's opinion of market value. Fannie 1004 / Freddie 70 for 1-unit; 1073 for condos; 1025 for 2-4 units; 1007/1025 for rentals. Submitted to the UCDP as standardized UAD data.

Standardization — very high, but a transition is underway. UAD defines 209 required/conditionally-required data points (91 required, 118 conditional) in a standardized XML. Important: UAD is moving from 2.6 (static 1004/1073/1025 forms) to UAD 3.6 — a single dynamic URAR, mandatory Nov 2, 2026, delivered as a ZIP with XML. Both coexist through 2026. Design the schema to tolerate both — field names map across, but structure differs. Condition/quality ratings are standardized enums either way.

Fields to extract.

Subject:

property address, legal description, APN/parcel, county

borrower name, owner of public record

occupancy (owner/tenant/vacant), property rights (fee/leasehold)

FHA case number (if FHA)

Contract (purchase):

contract price, contract date, seller concessions amount

Site / property:

property type, units, year built, GLA (sq ft), lot size

FEMA flood zone, FEMA map #, map date (appraisal carries flood info too)

zoning

Ratings (standardized enums — key):

condition rating C1–C6 (C5/C6 = repairs/safety issue)

quality rating Q1–Q6

as-is vs subject-to-repairs/completion

Valuation:

appraised value (final opinion)

effective date of appraisal, report date

approaches used (sales comparison / cost / income)

comparable sales (repeating: address, sale price, adjustments, date)

Rental (if 1007/1025 or UAD 3.6 rental section):

estimated monthly market rent

Appraiser:

appraiser name, license #, state, signature date

(1004D update/completion: update date, value-declined flag)

Proposed schema shape.

appraisal:

meta: {form_type, uad_version, report_date, effective_date}

subject: {address, legal_description, apn, county, borrower_name,

owner_of_record, occupancy, property_rights, fha_case_number}

contract: {price, date, seller_concessions}

property: {type, units, year_built, gla_sqft, lot_size, zoning,

flood_zone, fema_map_number, fema_map_date}

ratings: {condition_c, quality_q, as_is, subject_to}

valuation: {appraised_value, approaches[], comparables[]}

rental: {estimated_monthly_rent}

appraiser: {name, license, state, signature_date}

update_1004d: {update_date, value_declined}

Rules unlocked. PR-2 appraised-vs-price (appraised_value vs contract) · PR-4 completeness (required fields present) · PR-5 condition rating (condition_c = C5/C6) · PR-6 validity at closing (effective_date) · PR-7 address match (subject.address) · IN-14 rental income (rental) · DT-4 property taxes (from subject) · also feeds IH-5 flood (property.flood_zone).

Confirm with Priya. Does the appraisal arrive as UAD XML (from UCDP/LOS — easy parse) or only PDF? Given the Nov 2026 UAD 3.6 cutover, are you seeing 2.6, 3.6, or both? How many condos (1073) vs 1-unit (1004)?


# 4. Flood determination (FEMA SFHDF, Form 086-0-32) — small, standardized

What it is. The Standard Flood Hazard Determination Form — federally standardized, required for all federally-backed loans, tells you whether the property is in a Special Flood Hazard Area (SFHA) and thus whether flood insurance is mandatory.

Standardization — very high. It's a single FEMA form with fixed sections (A: community jurisdiction, B: NFIP data, C: availability, D: determination, E: comments, F: preparer). Small schema, very reliable.

Fields to extract.

property address / legal description

NFIP community name + 6-digit community number

NFIP map/panel number (11-digit), map effective/revised date

flood zone (e.g. X, AE, VE, A, AO — zones starting with A or V = SFHA)

is-in-SFHA determination (yes/no) — the key output

federal flood insurance available (community participates in NFIP)?

Letter of Map Change (LOMC) present + date

BFE (base flood elevation) where applicable

determination date, preparer name/company

Proposed schema shape.

flood_determination:

property: {address, legal_description}

community: {nfip_name, nfip_number}

map: {panel_number, effective_date}

flood_zone: "AE"

in_sfha: true            # the key field

nfip_available: true

lomc: {present, date}

bfe: null

determination: {date, preparer}

Rules unlocked. IH-5 flood zone determination present (in_sfha, flood_zone) · IH-6 flood insurance required/present (if in_sfha → require a flood policy).

Confirm with Priya. Is a flood determination always ordered/on file (it should be for federally-backed loans)? Does it arrive as a PDF or a structured vendor feed (ServiceLink/CoreLogic often deliver XML)?


# 5. Homeowners insurance declaration / binder — may already exist

What it is. The dec page (or binder — temporary evidence before the full policy) summarizing coverage. Check your registry first — your catalog had insurance rules as "NOW," implying a schema may already exist. If so, audit it against this field list rather than rebuilding.

Standardization — medium. Layout varies by carrier, but the standard evidence form is ACORD 27 (Evidence of Property Insurance), and the fields are consistent (named insured, property, coverages, mortgagee).

Fields to extract.

named insured(s) + property address

carrier name, policy number

policy period: effective date + expiration date

Coverage A — dwelling coverage amount (the key figure)

other coverages (B other structures, C personal property, D loss of use, E liability)

deductible(s) (incl. wind/hail/hurricane separate deductible)

annual premium

mortgagee clause: lender name + address + loan number

document type (dec page vs binder)

wind/hail coverage present (coastal)

Proposed schema shape.

insurance:

meta: {carrier, policy_number, doc_type}   # doc_type: dec_page | binder

insured: {names[], property_address}

period: {effective_date, expiration_date}

coverages: {dwelling_a, other_structures_b, personal_property_c,

loss_of_use_d, liability_e}

deductibles: {standard, wind_hail}

premium_annual: 1450

mortgagee: {lender_name, address, loan_number}

Rules unlocked. IH-1 adequacy (dwelling_a vs loan amount) · IH-2 mortgagee clause (mortgagee) · IH-3 effective date (period vs closing) · IH-4 / DT-5 premium in DTI (premium_annual).

Confirm with Priya / audit. Does a homeowners-insurance schema already exist in the extractor registry? (Likely — audit before building.) Dec page vs binder handling — both should map to the same schema.


# 6. Title commitment (ALTA) — structured but variable

What it is. The title company's offer to insure title. Standard ALTA three-schedule structure: Schedule A (the facts), Schedule B-I (requirements to clear before closing), Schedule B-II (exceptions — what the policy won't cover).

Standardization — medium. The A / B-I / B-II structure is universal (ALTA), so the sections are predictable; the content within (especially B-II exceptions) is free-text and varies by title company. Extract the structured Schedule A cleanly; treat B-I/B-II as itemized lists with some AI interpretation.

Fields to extract.

Schedule A (structured — reliable):

effective/commitment date

policy type(s) (owner's / lender's) + amounts (owner=price, lender=loan)

proposed insured (buyer/borrower + lender)

current owner / vested owner (seller)

vesting (how title is/will be held)

legal description

Schedule B-I (requirements — itemized list):

each requirement (deed to record, seller mortgage payoff, lien releases, tax payment, HOA approval, probate, etc.)

(per item: what/who/responsible)

Schedule B-II (exceptions — itemized, some interpretive):

standard exceptions (survey, taxes, parties in possession, mechanic's liens)

special exceptions (easements, CC&Rs, HOA, existing liens/unreleased mortgages, judgments, encroachments)

Proposed schema shape.

title_commitment:

schedule_a: {effective_date, policies: [{type, amount}],

proposed_insured[], vested_owner, vesting, legal_description,

property_address}

requirements_b1: [{text, category, party_responsible}]

exceptions_b2: [{text, type, is_standard, is_lien}]

Rules unlocked. TI-1 parties (schedule_a insured/owner vs file) · TI-2 legal description (vs appraisal/contract) · TI-3 existing liens/unreleased mortgage (exceptions_b2 is_lien) · TI-4 judgments/tax liens · TI-5 vesting · TI-6 chain of title · RE-1 REO reconciliation (partial).

Confirm with Priya. Does the title commitment always arrive before submission, or later? PDF only (likely) or any structured feed? Which title companies (fixes the layout)?


# 7. Condo docs / Tax returns / Compliance (LE-CD) — scope-dependent

Build only if in scope — confirm with Priya first.

7a. Condo questionnaire + master policy + HOA budget — unlocks CO-1..5. Fields: project name, HOA, questionnaire answers (owner-occupancy %, investor concentration, delinquency %, litigation y/n, special assessments), master hazard/liability/fidelity coverage amounts, reserve % of budget. Scope: only if Priya does meaningful condo volume. Highly variable forms (though Fannie 1076/1077 exist as semi-standard).

7b. Tax returns / P&L / K-1 — unlocks IN-12 (self-employment), IN-14 (rental via Schedule E). Fields: 1040 AGI, Schedule C net + depreciation/depletion add-backs, Schedule E rental income/expenses, K-1 distributions/ownership %, business returns (1120/1120S/1065) income. May partially exist — audit. Complex; pairs with the planned self-employed calculator (methodology = Priya-validated).

7c. Compliance docs (Loan Estimate / Closing Disclosure) — unlocks DC-1..7. Fields: LE issue date, CD issue/received date, fee itemization by tolerance bucket, APR, loan terms. Scope: biggest question — this may be the LOS's job, not your tool's. Confirm with Priya before building any of it. If the LOS owns TRID timing, skip the whole category.


# Build sequence (schema-first)

Confirm formats with Priya (credit report, AUS, appraisal): structured vs PDF. This gates effort estimates for the top 3.

Audit the extractor registry: is insurance (and maybe tax returns) already schema'd? Don't rebuild.

Build in unlock-value order, validating each schema against real de-identified samples before wiring rules:

Credit report (biggest unlock; effort depends on format) → then CR-4..13 rows

AUS/DU findings (highest leverage) → AU-1..4 + AS-10 requirement source

Appraisal (standardized; tolerate UAD 2.6 + 3.6) → PR/IN-14/DT-4 rows

Flood determination (small, standardized) → IH-5/6 rows

Insurance (audit first) → complete IH-1..4/DT-5 rows

Title (structured A, itemized B) → TI-* rows

Condo/tax/compliance (scope-gated) → only what Priya confirms in-scope

Hold un-schema'd blocked rule-rows in an explicit "awaiting-data" state — never let them show as passing (false-green).


# The one-page answer

The seven blocker documents, each needing an extraction schema to feed deterministic rules:

Credit report — extract scores, tradelines, public records, collections, inquiries → unlocks 10 credit rules. Format (structured vs PDF) = confirm with Priya; decides the effort. Most standardized underlying data (MISMO credit).

AUS/DU findings — extract recommendation, data-used, conditions list → unlocks AUS rules + the underwriter's own condition list. Highest leverage. Highly structured.

Appraisal (URAR/UAD) — extract subject, value, condition rating, flood zone → unlocks appraisal/rental/tax rules. Very standardized (209 UAD points); design for the 2.6→3.6 transition.

Flood determination (FEMA SFHDF) — extract zone + in-SFHA flag → unlocks 2 flood rules. Small, very standardized.

Insurance dec/binder — extract dwelling coverage, mortgagee, dates, premium → completes insurance rules. Audit — may already exist.

Title commitment (ALTA) — extract Schedule A + itemized B-I/B-II → unlocks title/REO rules. Structured sections, variable content.

Condo / tax / compliance — scope-dependent; confirm with Priya (compliance is likely the LOS's job).

Pattern: the highest-value blockers are the most standardized, so their schemas are the most tractable. Build schema-first, validate against real samples, hold un-schema'd rules as "awaiting-data," and confirm the top-three formats with Priya before estimating effort.
