# Stage 2 — Rule-kind classification (companion to `rule_kinds.csv`)

Generated from `backend/app/verification/rules/rule_kinds.csv` (the source of truth) via `app.scripts.generate_rule_kinds_md` — do not edit by hand. See ADR-247 / LP-301.

**135 rules** — calculative 28, structural 65, judgmental 27, out-of-scope 15. Numeric-check (deterministic bookend): 28. Priya-validated: 0/135. Thresholds needing sign-off: 19.

`exact_match` applies to structural rules only (true = deterministic-only, no AI; false = AI fuzzy entity match). `numeric_check` = the calculative bookend. `signoff` = a regulatory threshold Priya must sign off before ship. All rules are `priya_validated=false` until confirmed.

## calculative (28)

| rule_id | name | category | kind | evaluation_path | numeric | exact_match | validated | signoff |
|---|---|---|---|---|---|---|---|---|
| CR-2 | HELOC in HCLTV | Credit | calculative | deterministic_bookend+ai | true | — | false | false |
| CR-6 | Derogatory seasoning | Credit | calculative | deterministic_bookend+ai | true | — | false | true |
| CR-7 | Minimum credit score | Credit | calculative | deterministic_bookend | true | — | false | true |
| CR-9 | Student loan payment calc | Credit | calculative | deterministic_bookend+ai | true | — | false | true |
| CR-13 | Credit report validity at closing | Credit | calculative | deterministic_bookend | true | — | false | true |
| IN-1 | Stated vs documented income variance | Income | calculative | deterministic_bookend+ai | true | — | false | true |
| IN-3 | YTD income consistency | Income | calculative | deterministic_bookend+ai | true | — | false | true |
| IN-10 | Declining income | Income | calculative | deterministic_bookend+ai | true | — | false | true |
| IN-11 | Variable income averaging / history | Income | calculative | deterministic_bookend+ai | true | — | false | true |
| IN-12 | Self-employment income analysis | Income | calculative | deterministic_bookend+ai | true | — | false | true |
| AS-1 | Large-deposit sourcing sweep | Assets | calculative | deterministic_bookend+ai | true | — | false | true |
| AS-3 | Cash-to-close sufficiency | Assets | calculative | deterministic_bookend+ai | true | — | false | false |
| AS-4 | Reserves adequacy | Assets | calculative | deterministic_bookend+ai | true | — | false | true |
| AS-11 | Retirement/stock liquidation terms | Assets | calculative | deterministic_bookend+ai | true | — | false | true |
| DT-1 | DTI ratio vs limit | DTI | calculative | deterministic_bookend+ai | true | — | false | true |
| DT-4 | Property taxes estimate | DTI | calculative | deterministic_bookend+ai | true | — | false | false |
| DT-5 | Insurance premium in DTI | DTI | calculative | deterministic_bookend | true | — | false | false |
| PR-1 | LTV / CLTV / HCLTV limits | Property | calculative | deterministic_bookend+ai | true | — | false | true |
| PR-2 | Appraised value vs purchase price | Property | calculative | deterministic_bookend | true | — | false | false |
| PR-6 | Appraisal validity at closing | Property | calculative | deterministic_bookend | true | — | false | true |
| IH-4 | Premium matches DTI | Insurance | calculative | deterministic_bookend | true | — | false | false |
| CO-4 | HOA budget / reserves | Condo | calculative | deterministic_bookend | true | — | false | true |
| PC-4 | Seller credit / IPC limit | Contract | calculative | deterministic_bookend | true | — | false | true |
| MI-1 | PMI required (Conv >80% LTV) | MI | calculative | deterministic_bookend | true | — | false | true |
| MI-2 | MI factor correct | MI | calculative | deterministic_bookend | true | — | false | false |
| MI-4 | FHA MIP (upfront + monthly) | MI | calculative | deterministic_bookend | true | — | false | true |
| PE-1 | Conventional eligibility | Program | calculative | deterministic_bookend | true | — | false | false |
| PE-3 | FHA minimum required investment | Program | calculative | deterministic_bookend | true | — | false | false |

## structural (65)

| rule_id | name | category | kind | evaluation_path | numeric | exact_match | validated | signoff |
|---|---|---|---|---|---|---|---|---|
| ID-1 | Borrower name consistency | Identity | structural | ai_fuzzy_match | false | false | false | false |
| ID-2 | SSN consistency | Identity | structural | deterministic_only | false | true | false | false |
| ID-3 | DOB consistency | Identity | structural | deterministic_only | false | true | false | false |
| ID-4 | Current address consistency | Identity | structural | ai_fuzzy_match | false | false | false | false |
| ID-5 | ID expiration | Identity | structural | deterministic_only | false | true | false | false |
| ID-6 | Application completeness (1003) | Identity | structural | deterministic_only | false | true | false | false |
| ID-7 | Marital status / title consistency | Identity | structural | ai_fuzzy_match | false | false | false | false |
| CR-1 | Undisclosed liability (MISMO vs app) | Credit | structural | ai_fuzzy_match | false | false | false | false |
| CR-3 | Paid-to-qualify verification | Credit | structural | deterministic_only | false | true | false | false |
| CR-4 | Undisclosed tradeline (report vs app) | Credit | structural | ai_fuzzy_match | false | false | false | false |
| CR-5 | Credit inquiry LOE | Credit | structural | ai_fuzzy_match | false | false | false | false |
| CR-11 | Judgments / liens resolution | Credit | structural | deterministic_only | false | true | false | false |
| CR-12 | Disputed accounts | Credit | structural | deterministic_only | false | true | false | false |
| IN-2 | Pay stub recency | Income | structural | deterministic_only | false | true | false | false |
| IN-4 | Employment gap | Income | structural | deterministic_only | false | true | false | false |
| IN-5 | Employer name consistency | Income | structural | ai_fuzzy_match | false | false | false | false |
| IN-6 | Pay-stub <-> W-2 coverage | Income | structural | ai_fuzzy_match | false | false | false | false |
| IN-8 | VOE present | Income | structural | deterministic_only | false | true | false | false |
| IN-9 | Future employment (offer letter) | Income | structural | deterministic_only | false | true | false | false |
| IN-15 | Terminated employment documentation | Income | structural | deterministic_only | false | true | false | false |
| IN-16 | Pay-stub-only documentation | Income | structural | deterministic_only | false | true | false | false |
| AS-2 | Earnest money deposit sourcing | Assets | structural | ai_fuzzy_match | false | false | false | false |
| AS-5 | Gift-fund documentation chain | Assets | structural | ai_fuzzy_match | false | false | false | false |
| AS-6 | Account ownership | Assets | structural | ai_fuzzy_match | false | false | false | false |
| AS-7 | NSF / overdraft flag | Assets | structural | ai_fuzzy_match | false | false | false | false |
| AS-8 | Statement chaining (continuity) | Assets | structural | deterministic_only | false | true | false | false |
| AS-9 | Missing pages | Assets | structural | deterministic_only | false | true | false | false |
| AS-10 | Statement recency completeness | Assets | structural | deterministic_only | false | true | false | false |
| DT-2 | HOA dues in DTI | DTI | structural | deterministic_only | false | true | false | false |
| DT-3 | Mortgage insurance in DTI | DTI | structural | deterministic_only | false | true | false | false |
| DT-6 | Retained-property PITIA | DTI | structural | ai_fuzzy_match | false | false | false | false |
| PR-7 | Appraisal address matches | Property | structural | ai_fuzzy_match | false | false | false | false |
| OC-1 | Occupancy consistency | Occupancy | structural | ai_fuzzy_match | false | false | false | false |
| TI-1 | Title commitment parties | Title | structural | deterministic_only | false | true | false | false |
| TI-3 | Existing liens / unreleased mortgage | Title | structural | ai_fuzzy_match | false | false | false | false |
| TI-4 | Judgments / tax liens on title | Title | structural | deterministic_only | false | true | false | false |
| IH-1 | Insurance adequacy | Insurance | structural | deterministic_only | false | true | false | false |
| IH-2 | Mortgagee clause | Insurance | structural | deterministic_only | false | true | false | false |
| IH-3 | Insurance effective date | Insurance | structural | deterministic_only | false | true | false | false |
| IH-5 | Flood zone determination | Insurance | structural | deterministic_only | false | true | false | false |
| IH-6 | Flood insurance required/present | Insurance | structural | ai_fuzzy_match | false | false | false | false |
| IH-7 | Condo master policy | Insurance | structural | deterministic_only | false | true | false | false |
| CO-1 | Condo questionnaire present | Condo | structural | deterministic_only | false | true | false | false |
| CO-2 | HOA dues in DTI | Condo | structural | deterministic_only | false | true | false | false |
| CO-3 | Master insurance / fidelity | Condo | structural | deterministic_only | false | true | false | false |
| CO-5 | Litigation / delinquency / concentration | Condo | structural | deterministic_only | false | true | false | false |
| PC-1 | Contract parties match | Contract | structural | ai_fuzzy_match | false | false | false | false |
| PC-2 | Purchase price matches loan terms | Contract | structural | deterministic_only | false | true | false | false |
| PC-3 | Property address matches | Contract | structural | ai_fuzzy_match | false | false | false | false |
| PC-5 | EMD amount & source | Contract | structural | ai_fuzzy_match | false | false | false | false |
| PC-6 | Addenda signed | Contract | structural | ai_fuzzy_match | false | false | false | false |
| PC-7 | Closing date realistic/current | Contract | structural | deterministic_only | false | true | false | false |
| PC-9 | Financing contingency dates | Contract | structural | deterministic_only | false | true | false | false |
| MI-3 | MI certificate present | MI | structural | deterministic_only | false | true | false | false |
| MI-5 | Borrower-paid vs lender-paid MI | MI | structural | deterministic_only | false | true | false | false |
| PE-2 | FHA case number | Program | structural | deterministic_only | false | true | false | false |
| AU-1 | AUS data matches documents | AUS | structural | ai_fuzzy_match | false | false | false | false |
| AU-2 | AUS required conditions collected | AUS | structural | ai_fuzzy_match | false | false | false | false |
| AU-3 | AUS recommendation status | AUS | structural | deterministic_only | false | true | false | false |
| AU-4 | AUS rerun needed | AUS | structural | deterministic_only | false | true | false | false |
| RE-1 | REO reconciliation | REO | structural | ai_fuzzy_match | false | false | false | false |
| RE-2 | Retained-property tax & insurance | REO | structural | deterministic_only | false | true | false | false |
| CL-1 | Rate lock expiration | Closing | structural | deterministic_only | false | true | false | false |
| LO-1 | LOE required-and-present | LOE | structural | ai_fuzzy_match | false | false | false | false |
| LO-2 | LOE completeness | LOE | structural | ai_fuzzy_match | false | false | false | false |

## judgmental (27)

| rule_id | name | category | kind | evaluation_path | numeric | exact_match | validated | signoff |
|---|---|---|---|---|---|---|---|---|
| ID-8 | Citizenship / residency eligibility | Identity | judgmental | ai_judgment | false | — | false | false |
| ID-9 | Power of attorney acceptability | Identity | judgmental | ai_judgment | false | — | false | false |
| CR-8 | Mortgage payment history | Credit | judgmental | ai_judgment | false | — | false | false |
| CR-10 | Collections / charge-offs treatment | Credit | judgmental | ai_judgment | false | — | false | false |
| IN-7 | Same line of work (job change) | Income | judgmental | ai_judgment | false | — | false | false |
| IN-13 | Other income continuance | Income | judgmental | ai_judgment | false | — | false | false |
| IN-14 | Rental income support | Income | judgmental | ai_judgment | false | — | false | false |
| AS-12 | Borrowed funds detection | Assets | judgmental | ai_judgment | false | — | false | false |
| DT-7 | ATR documentation completeness | DTI | judgmental | ai_judgment | false | — | false | false |
| PR-3 | Property type eligibility | Property | judgmental | ai_judgment | false | — | false | false |
| PR-4 | Appraisal completeness | Property | judgmental | ai_judgment | false | — | false | false |
| PR-5 | Appraisal condition rating | Property | judgmental | ai_judgment | false | — | false | false |
| PR-8 | Disaster-area reinspection | Property | judgmental | ai_judgment | false | — | false | false |
| OC-2 | Occupancy reasonableness | Occupancy | judgmental | ai_judgment | false | — | false | false |
| OC-3 | Investment rental support | Occupancy | judgmental | ai_judgment | false | — | false | false |
| TI-2 | Legal description match | Title | judgmental | ai_judgment | false | — | false | false |
| TI-5 | Vesting | Title | judgmental | ai_judgment | false | — | false | false |
| TI-6 | Chain of title / rapid transfer | Title | judgmental | ai_judgment | false | — | false | false |
| IH-8 | Wind/hail coverage | Insurance | judgmental | ai_judgment | false | — | false | false |
| PC-8 | Personal property not inflating value | Contract | judgmental | ai_judgment | false | — | false | false |
| PE-4 | FHA property condition | Program | judgmental | ai_judgment | false | — | false | false |
| FR-1 | Altered-document appearance | Fraud | judgmental | ai_judgment | false | — | false | false |
| FR-2 | Non-arm's-length / flip | Fraud | judgmental | ai_judgment | false | — | false | false |
| FR-3 | Unusual seller credits / side agreements | Fraud | judgmental | ai_judgment | false | — | false | false |
| FR-4 | Garnishment on paystub | Fraud | judgmental | ai_judgment | false | — | false | false |
| FR-5 | Recurring undisclosed debit | Fraud | judgmental | ai_judgment | false | — | false | false |
| FR-6 | Novel cross-source discrepancy | Fraud | judgmental | ai_judgment | false | — | false | false |

## out_of_scope (15)

| rule_id | name | category | kind | evaluation_path | numeric | exact_match | validated | signoff |
|---|---|---|---|---|---|---|---|---|
| ID-10 | OFAC / fraud / sanctions | Identity | out_of_scope | static_filter | false | — | false | false |
| PE-5 | VA / USDA / Jumbo / Non-QM | Program | out_of_scope | static_filter | false | — | false | false |
| DC-1 | Loan Estimate timely | Compliance | out_of_scope | static_filter | false | — | false | false |
| DC-2 | Intent to proceed | Compliance | out_of_scope | static_filter | false | — | false | false |
| DC-3 | Closing Disclosure 3-day timing | Compliance | out_of_scope | static_filter | false | — | false | false |
| DC-4 | Fee tolerance (0%/10%) | Compliance | out_of_scope | static_filter | false | — | false | false |
| DC-5 | APR change threshold | Compliance | out_of_scope | static_filter | false | — | false | false |
| DC-6 | Appraisal delivery (ECOA) | Compliance | out_of_scope | static_filter | false | — | false | false |
| DC-7 | Changed-circumstance validity | Compliance | out_of_scope | static_filter | false | — | false | false |
| CL-2 | Clear-to-close conditions | Closing | out_of_scope | static_filter | false | — | false | false |
| CL-3 | Final CD accuracy | Closing | out_of_scope | static_filter | false | — | false | false |
| CL-4 | Final VOE | Closing | out_of_scope | static_filter | false | — | false | false |
| CL-5 | Final credit refresh | Closing | out_of_scope | static_filter | false | — | false | false |
| CL-6 | Signed docs / notarization / recording | Closing | out_of_scope | static_filter | false | — | false | false |
| CL-7 | Right of rescission (refi) | Closing | out_of_scope | static_filter | false | — | false | false |
