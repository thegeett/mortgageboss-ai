# Consolidated Verification Rule Master List — mortgageboss-ai

What this is. A single, reviewable master list of every candidate verification rule, merged from three sources: the Claude rule catalog (the detailed WHEN/CHECK/FIRES version), and two ChatGPT processor checklists. It is built for you to review, prioritize, and eventually develop into the rule engine.

How to use it. Each rule has a Source tag so you can see where it came from as you review. Work down the list, decide keep / cut / defer per rule, set the thresholds (with Priya), and the surviving set becomes the engine's rule book.


## Legend

Source — where the rule originated (for your review):

Claude — proposed in the Claude rule catalog (reasoned from mortgage-processing principles + your actual files).

ChatGPT — appeared in a ChatGPT processor checklist but not in the Claude catalog.

Both — independently in both (higher confidence it's a real, standard check).

Layer — how it must be built (from the classification pass):

DET — pure deterministic (structured values; arithmetic/date/presence/exact).

DET-FUZZY — deterministic logic with tolerant name/address/institution matching (LP-115 discipline).

DET+AI — deterministic core, AI refines/classifies one input.

AI — interpretation; AI-surface + human-confirm, not a deterministic rule.

HYBRID — genuinely two checks (one DET + one AI).

DEFERRED-DET — deterministic once Priya fixes the methodology.

CALC — already handled by the on-demand calculators (DTI/LTV), not a finding.

Status — buildability:

NOW — data available, buildable now (as a CrossSourceRule — see build note).

EXTRACT — needs a small extraction addition first.

BLOCKED — needs a data source not in the system (chiefly the credit report, AUS findings, flood cert, title, appraisal).

SCOPE? — may be the LOS's job, not this tool's — confirm scope with Priya.

EXISTS? — likely already built; audit before re-building.

Scope — in/out for your current product (Conventional + FHA via UWM/Sun-West, pre-submission processing):

IN — in scope.

OUT — out of scope for now (other programs, or post-close operations).

? — scope uncertain; Priya decides.

⚙️ BUILD NOTE (critical, from the pipeline map). The threshold engine (verification_engine.py) is dormant — nothing calls it. To make a deterministic rule that actually fires today, add a CrossSourceRule in app/verification/cross_source/rules.py (give it a canonical_type so the AI defers, a templated message, and a pure check() over CrossSourceFacts), and make sure the facts it needs exist in build_cross_source_facts. DTI/LTV are handled by the calculators (CALC), not findings. Confidence: the engine hardcodes deterministic = 1.0; DET-FUZZY rules must emit < 1.0 for fuzzy matches (LP-115 establishes this).


# A. Borrower application / identity


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| ID-1 | Borrower name consistency | Name matches across MISMO / ID / paystub / W-2 / bank (nickname, initial, maiden tolerant) | DET-FUZZY | Both | NOW | IN |
| ID-2 | SSN consistency | SSN matches exactly across MISMO / documents | DET | Both | EXTRACT | IN |
| ID-3 | DOB consistency | DOB matches across ID / MISMO (format-normalized) | DET | Both | EXTRACT | IN |
| ID-4 | Current address consistency | Application address matches credit/bank/paystub address | DET-FUZZY | ChatGPT | EXTRACT | IN |
| ID-5 | ID expiration | Government ID (driver's license) not expired | DET | Both | NOW | IN |
| ID-6 | Application completeness | Required 1003 fields present (declarations, occupancy, loan purpose, REO) | DET | ChatGPT | EXTRACT | IN |
| ID-7 | Marital status / title consistency | Marital status consistent (affects title/community-property) | DET | ChatGPT | EXTRACT | ? |
| ID-8 | Citizenship / residency eligibility | Residency/visa status acceptable for program | DET+AI | ChatGPT | EXTRACT | ? |
| ID-9 | Power of attorney acceptability | If POA signs, POA is acceptable | AI | ChatGPT | BLOCKED | ? |
| ID-10 | OFAC / fraud / sanctions check | Borrower cleared against sanctions/fraud lists | DET | ChatGPT | BLOCKED | OUT |


# B. Credit & liabilities


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| CR-1 | Undisclosed liability (MISMO vs app) | Each MISMO liability with a payment is in DTI or explicitly excluded | DET | Claude | NOW | IN |
| CR-2 | HELOC in HCLTV | HCLTV uses HELOC credit limit, not balance | DET | Claude | NOW | IN |
| CR-3 | Paid-to-qualify verification | Liability excluded as paid-off has payoff evidence | DET | Claude | NOW | IN |
| CR-4 | Undisclosed tradeline (report vs app) | Each credit-report tradeline has a matching stated liability | DET-FUZZY | Both | BLOCKED | IN |
| CR-5 | Credit inquiry LOE | Recent hard inquiry has a matching new account or an LOE | DET | Both | BLOCKED | IN |
| CR-6 | Derogatory seasoning | BK/foreclosure/collection within program seasoning window | DET | Both | BLOCKED | IN |
| CR-7 | Minimum credit score | Representative score ≥ program/lender minimum | DET | Both | BLOCKED | IN |
| CR-8 | Mortgage payment history | Late payments / current status on existing mortgages | DET | ChatGPT | BLOCKED | IN |
| CR-9 | Student loan payment calculation | Correct payment per program (% of balance vs actual) | DET | ChatGPT | BLOCKED | IN |
| CR-10 | Collections / charge-offs treatment | Program-specific handling of collections | DET+AI | ChatGPT | BLOCKED | IN |
| CR-11 | Judgments / liens resolution | Judgments/tax liens paid or resolved | DET | ChatGPT | BLOCKED | IN |
| CR-12 | Disputed accounts | Disputed tradelines may need resolution / AUS rerun | DET+AI | ChatGPT | BLOCKED | IN |
| CR-13 | Credit report validity at closing | Report within ~120 days at closing | DET | Claude | BLOCKED | IN |


# C. Income & employment


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| IN-1 | Stated vs documented income variance | Computed income vs stated within variance threshold | DET | Claude | EXISTS? | IN |
| IN-2 | Pay stub recency | Most recent pay stub within 30 days (of today / closing) | DET | Both | NOW | IN |
| IN-3 | YTD income consistency | YTD ÷ periods ≈ stated monthly (catches inflation) | DET | Claude | NOW | IN |
| IN-4 | Employment gap | Gap between employment records > threshold → LOE | DET | Both | EXTRACT | IN |
| IN-5 | Employer name consistency | Documented employer matches stated (legal-name tolerant) — LP-115 | DET-FUZZY | Both | IN PROGRESS | IN |
| IN-6 | Paystub↔W2 employer coverage | Each paystub employer appears on a W-2 and vice-versa | DET-FUZZY | Claude | NOW | IN |
| IN-7 | Job title / same line of work | Job change stays in same field (stability) | AI | ChatGPT | EXTRACT | IN |
| IN-8 | VOE present | Written/verbal verification of employment on file | DET | Both | EXTRACT | IN |
| IN-9 | Future employment (offer letter) | New-job files have offer letter + start date + first paystub | DET | ChatGPT | EXTRACT | IN |
| IN-10 | Declining income | Most recent year < prior → qualify at lower figure | DEFERRED-DET | Both | NOW* | IN |
| IN-11 | Variable income averaging / history | OT/bonus/commission has 2-yr history, averaged | DEFERRED-DET | Both | NOW* | IN |
| IN-12 | Self-employment income analysis | Sched C / K-1 net + add-backs (its own calculator) | DEFERRED-DET | Both | EXTRACT | IN |
| IN-13 | Other income continuance | SS/pension/alimony/child support has continuance proof | DET+AI | ChatGPT | EXTRACT | ? |
| IN-14 | Rental income support | Lease / tax returns / appraisal rent schedule present | DET+AI | ChatGPT | EXTRACT | ? |

* IN-10/11 logic is deterministic but the methodology (how declining/variable income is treated) is Priya-validated before coding.


# D. Assets & funds to close


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| AS-1 | Large-deposit sourcing sweep | Every deposit > threshold (50% monthly income) is sourced | DET+AI | Both | NOW | IN |
| AS-2 | Earnest money deposit sourcing | EMD cleared from borrower's account + sourced | DET+AI | Both | NOW | IN |
| AS-3 | Cash-to-close sufficiency | Liquid assets ≥ down payment + costs + reserves | DET | Claude | NOW | IN |
| AS-4 | Reserves adequacy | Verified reserves ≥ required months of PITIA | DET | Both | EXISTS? | IN |
| AS-5 | Gift-fund documentation chain | Gift letter + donor ability + transfer evidence all present | DET+AI | Both | NOW | IN |
| AS-6 | Account ownership | Asset account is in the borrower's name | DET-FUZZY | Both | EXTRACT | IN |
| AS-7 | NSF / overdraft flag | Statement NSF/overdraft items → possible LOE | DET+AI | Both | NOW | IN |
| AS-8 | Statement chaining (continuity) | Statement N ending = N+1 beginning; no gap month | DET | Claude | NOW | IN |
| AS-9 | Missing pages | "Page X of Y" — all Y pages present | DET | Claude | EXTRACT | IN |
| AS-10 | Statement recency completeness | N consecutive recent months present per account | DET | Claude | NOW | IN |
| AS-11 | Retirement/stock liquidation terms | Vested balance / liquidation terms if used | DET+AI | ChatGPT | EXTRACT | ? |
| AS-12 | Borrowed funds detection | Funds from a loan counted as a liability | AI | ChatGPT | NOW | IN |


# E. DTI & ability-to-repay


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| DT-1 | DTI ratio vs limit | Back-end DTI vs program limit (36/45/50) | CALC | Both | EXISTS | IN |
| DT-2 | HOA dues in DTI | HOA dues included in the payment | DET | ChatGPT | EXISTS? | IN |
| DT-3 | Mortgage insurance in DTI | MI/MIP included in the payment | DET | ChatGPT | EXISTS? | IN |
| DT-4 | Property taxes estimate | Taxes estimated correctly (esp. new construction) | DET+AI | ChatGPT | EXTRACT | IN |
| DT-5 | Insurance premium in DTI | Actual quote/binder premium used | DET | Both | NOW | IN |
| DT-6 | Retained-property PITIA | Other mortgages' full PITIA counted | DET | ChatGPT | EXTRACT | IN |
| DT-7 | ATR documentation completeness | File documents all ATR factors | DET+AI | ChatGPT | EXTRACT | ? |


# F. Property & appraisal


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| PR-1 | LTV / CLTV / HCLTV limits | Ratios vs program limits (purpose-aware) | CALC | Both | EXISTS? | IN |
| PR-2 | Appraised value vs purchase price | LTV on lesser-of; flag appraisal < price | DET | Both | NOW | IN |
| PR-3 | Property type eligibility | Type permitted for program/occupancy | DET+AI | Both | EXTRACT | IN |
| PR-4 | Appraisal completeness | Report has value, comps, photos, correct subject | DET+AI | ChatGPT | BLOCKED | IN |
| PR-5 | Appraisal condition rating | C5/C6 or repairs-required flagged | AI | ChatGPT | BLOCKED | IN |
| PR-6 | Appraisal validity at closing | Appraisal within validity window at closing | DET | Both | EXTRACT | IN |
| PR-7 | Appraisal address matches | Appraisal property matches contract/MISMO | DET-FUZZY | ChatGPT | BLOCKED | IN |
| PR-8 | Disaster-area reinspection | If disaster declared, reinspection present | DET+AI | ChatGPT | BLOCKED | ? |


# G. Occupancy


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| OC-1 | Occupancy consistency | Stated occupancy consistent across docs | DET+AI | Both | EXTRACT | IN |
| OC-2 | Occupancy reasonableness | Buying far from job / owns nearby primary / mailing address unchanged | AI | Both | EXTRACT | IN |
| OC-3 | Investment property rental support | Investment occupancy has lease/rental income | DET+AI | ChatGPT | EXTRACT | ? |


# H. Title


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| TI-1 | Title commitment parties | Borrower/seller/property match loan file | DET-FUZZY | Both | BLOCKED | IN |
| TI-2 | Legal description match | Legal description matches appraisal/contract | DET+AI | ChatGPT | BLOCKED | IN |
| TI-3 | Existing liens / unreleased mortgage | Liens cleared / payoff obtained | DET+AI | Both | BLOCKED | IN |
| TI-4 | Judgments / tax liens on title | Resolved before closing | DET | ChatGPT | BLOCKED | IN |
| TI-5 | Vesting | How borrower takes title is acceptable | DET+AI | ChatGPT | BLOCKED | IN |
| TI-6 | Chain of title / rapid transfer | Recent transfers → flip/fraud review | AI | ChatGPT | BLOCKED | IN |


# I. Insurance & flood


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| IH-1 | Insurance adequacy | Dwelling coverage ≥ loan amount / replacement cost | DET | Both | NOW | IN |
| IH-2 | Mortgagee clause | Lender named as mortgagee | DET+AI | Both | NOW | IN |
| IH-3 | Insurance effective date | Effective on or before closing | DET | Both | EXTRACT | IN |
| IH-4 | Premium matches DTI | Binder premium matches the premium used in payment | DET | Both | NOW | IN |
| IH-5 | Flood zone determination | Flood cert present; zone identified | DET | Both | BLOCKED | IN |
| IH-6 | Flood insurance required/present | If SFHA (Zone A/V), flood policy present + adequate | DET | Both | BLOCKED | IN |
| IH-7 | Condo master policy | Condo loans have master hazard/liability policy | DET | Both | BLOCKED | ? |
| IH-8 | Wind/hail coverage | State/property-specific coverage present | DET+AI | ChatGPT | BLOCKED | ? |


# J. Condo / HOA


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| CO-1 | Condo questionnaire present | Project questionnaire on file | DET | Both | BLOCKED | ? |
| CO-2 | HOA dues in DTI | HOA dues included in payment | DET | Both | EXTRACT | ? |
| CO-3 | Master insurance / fidelity | Project insurance adequate | DET+AI | ChatGPT | BLOCKED | ? |
| CO-4 | HOA budget / reserves | Reserve amount adequate | DET+AI | ChatGPT | BLOCKED | ? |
| CO-5 | Litigation / delinquency / concentration | Warrantability factors | AI | Both | BLOCKED | ? |


# K. Purchase contract


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| PC-1 | Contract parties match | Buyer/seller match loan file & title | DET-FUZZY | Both | NOW | IN |
| PC-2 | Purchase price matches loan terms | Contract price = LOS/MISMO price | DET | Both | NOW | IN |
| PC-3 | Property address matches | Contract address = all docs | DET-FUZZY | Both | NOW | IN |
| PC-4 | Seller credit / IPC limit | Seller credit within program interested-party limit | DET | Both | EXTRACT | IN |
| PC-5 | EMD amount & source | Earnest money amount + sourced (→ AS-2) | DET+AI | Both | NOW | IN |
| PC-6 | Addenda signed | All addenda present and signed | HYBRID | ChatGPT | EXTRACT | IN |
| PC-7 | Closing date realistic/current | Contract closing date not passed | DET | Both | NOW | IN |
| PC-8 | Personal property not inflating value | Personal property excluded from value | AI | ChatGPT | EXTRACT | IN |
| PC-9 | Financing contingency dates | Contingency terms/dates tracked | DET | ChatGPT | EXTRACT | ? |


# L. Mortgage insurance / fees


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| MI-1 | PMI required (Conv >80% LTV) | If LTV > 80%, PMI present | DET | Both | NOW | IN |
| MI-2 | MI factor correct | MI factor used matches certificate | DET | Both | EXTRACT | IN |
| MI-3 | MI certificate present | MI cert obtained before closing | DET | Both | EXTRACT | IN |
| MI-4 | FHA MIP (upfront + monthly) | FHA loans have correct UFMIP + monthly MIP | DET | Both | NOW | IN |
| MI-5 | Borrower-paid vs lender-paid MI | Correct MI structure | DET | ChatGPT | EXTRACT | IN |


# M. Program eligibility


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| PE-1 | Conventional eligibility | Credit/DTI/LTV/reserves/type/occupancy meet Conv | DET | Both | EXISTS? | IN |
| PE-2 | FHA case number | FHA case number present | DET | ChatGPT | EXTRACT | IN |
| PE-3 | FHA minimum required investment | 3.5% MRI met | DET | ChatGPT | NOW | IN |
| PE-4 | FHA property condition | FHA appraisal/condition requirements | AI | ChatGPT | BLOCKED | IN |
| PE-5 | VA / USDA / Jumbo / Non-QM | Program-specific eligibility | DET | ChatGPT | — | OUT |


# N. AUS (DU / LP / TOTAL) — high value


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| AU-1 | AUS data matches documents | Income/assets/debts entered match the docs | DET | Both | BLOCKED | IN |
| AU-2 | AUS required conditions collected | Each DU/LP condition has a matching document/need | DET+AI | Both | BLOCKED | IN |
| AU-3 | AUS recommendation status | Approve/Eligible vs Refer surfaced | DET | Both | BLOCKED | IN |
| AU-4 | AUS rerun needed | Income/assets/debts/rate/amount changed since last run | DET | Both | NOW | IN |

Note. AUS/DU findings are the underwriter's own condition list — the single highest-value data unlock. Ingesting the DU findings report (as a document type) turns "our best guess at conditions" into "the actual conditions." Confirm with Priya how DU findings arrive.


# O. Disclosure & compliance (TRID)


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| DC-1 | Loan Estimate timely | LE delivered within required window | DET | ChatGPT | SCOPE? | ? |
| DC-2 | Intent to proceed | Borrower gave intent-to-proceed | DET | ChatGPT | SCOPE? | ? |
| DC-3 | Closing Disclosure 3-day timing | CD sent ≥ 3 business days before closing | DET | ChatGPT | SCOPE? | ? |
| DC-4 | Fee tolerance (0% / 10%) | Fees within tolerance buckets | DET | ChatGPT | SCOPE? | ? |
| DC-5 | APR change threshold | APR change within redisclosure tolerance | DET | ChatGPT | SCOPE? | ? |
| DC-6 | Appraisal delivery (ECOA) | Borrower received appraisal copy timely | DET | ChatGPT | SCOPE? | ? |
| DC-7 | Changed-circumstance validity | Revised LE has a valid changed circumstance | DET+AI | ChatGPT | SCOPE? | ? |

Note. This whole category may be the LOS's job, not this tool's — it's the biggest scope question. Priya confirms whether disclosure/compliance timing is in your product's lane before any of these are built.


# P. Real estate owned (REO)


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| RE-1 | REO reconciliation | Owned properties reconcile across app / credit / mortgage statements / title | DET-FUZZY | Both | BLOCKED | IN |
| RE-2 | Retained-property tax & insurance | Taxes/insurance on retained REO documented | DET | ChatGPT | EXTRACT | IN |


# Q. Closing / funding / post-close — mostly OUT of pre-submission scope


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| CL-1 | Rate lock expiration | Rate lock not expired vs closing date | DET | Both | EXTRACT | IN |
| CL-2 | Clear-to-close conditions | All conditions cleared | DET+AI | ChatGPT | BLOCKED | OUT |
| CL-3 | Final CD accuracy | Final CD fees / cash-to-close accurate | DET | ChatGPT | BLOCKED | OUT |
| CL-4 | Final VOE | Final employment re-verified | DET | ChatGPT | BLOCKED | OUT |
| CL-5 | Final credit refresh | No new debt before closing | DET | ChatGPT | BLOCKED | OUT |
| CL-6 | Signed docs / notarization / recording | Post-close package complete | DET+AI | ChatGPT | BLOCKED | OUT |
| CL-7 | Right of rescission (refi) | Rescission period observed | DET | ChatGPT | EXTRACT | OUT |


# R. Fraud / QC (mostly AI-surface)


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Altered-document appearance | Paystub/statement format anomalies | AI | Both | NOW | IN |
| FR-2 | Non-arm's-length / flip | Rapid transfer, related parties, inflated value | AI | ChatGPT | BLOCKED | IN |
| FR-3 | Unusual seller credits / side agreements | Credits beyond norms | DET+AI | ChatGPT | EXTRACT | IN |
| FR-4 | Garnishment on paystub | Deduction implies undisclosed obligation | AI | Claude | NOW | IN |
| FR-5 | Recurring undisclosed debit | Recurring debit implies undisclosed debt | AI | Claude | NOW | IN |
| FR-6 | Novel cross-source discrepancy | Open-ended AI discovery (divorce-decree obligation) | AI | Claude | EXISTS | IN |


# S. Letters of explanation (LOE) tracking


| ID | Rule | What it checks | Layer | Source | Status | Scope |
| --- | --- | --- | --- | --- | --- | --- |
| LO-1 | LOE required-and-present | Each condition needing an LOE has a matching LOE | DET+AI | Both | EXTRACT | IN |
| LO-2 | LOE completeness | LOE has explanation + date + amount + signature | HYBRID | ChatGPT | EXTRACT | IN |


# Summary counts


| Dimension | Breakdown |
| --- | --- |
| By source | Both: ~50 · Claude-only: ~15 · ChatGPT-only: ~35 |
| By layer | DET / DET-FUZZY (deterministic): majority · DET+AI: ~20 · AI: ~10 · DEFERRED-DET: 3 · CALC: 3 · HYBRID: 2 |
| By status | NOW: ~25 · EXTRACT: ~30 · BLOCKED: ~30 · SCOPE?: 7 · EXISTS?: ~6 |
| By scope | IN: majority · OUT: ~10 (other programs, post-close) · ?: ~20 (Priya decides) |

The blockers that unlock the most rules:

Credit report ingestion → unlocks CR-4..13 (10 rules).

AUS/DU findings ingestion → unlocks AU-1..3 + validates the whole file against the underwriter's own list (highest leverage).

Title, appraisal, flood cert as document types → unlock the H, I, PR-blocked, and CO categories.


# How to review this (suggested process)

Scope pass — mark every ? and OUT row: is it in your product's lane? (Especially the whole Disclosure/Compliance category — is that you or the LOS?)

Priority pass — of the IN + NOW rows, which prevent the most conditions? (Wave 1.)

Threshold pass (with Priya) — set every grounded-starter number; validate every DET-FUZZY match tolerance.

Blocker pass — decide the order to unlock credit report / AUS findings / title / appraisal (each unlocks a batch).

The gold pass (with Priya) — ask what conditions UWM/Sun-July actually issue that are NOT on this list. Generic checklists (both ChatGPT and Claude) describe standard processing; only Priya's real condition history reveals your lenders' specific quirks. Those additions are worth more than anything a generic source can provide.


# Provenance note

Both = the rule appears in both the Claude catalog and a ChatGPT checklist (highest confidence it's a real, standard check).

Claude = reasoned from mortgage-processing principles and grounded in your actual files (LF-6T3N, the DU MISMO) — these tend to be the more specifically buildable ones (they name the exact data).

ChatGPT = from a generic U.S. processor checklist — good for coverage (what exists in the domain), but generic; not grounded in your lenders or your extracted data, so each needs a scope + specifics check.

Every number is a grounded-starter; every scope ? is Priya's call. This list is the possible rule universe; Priya's real conditions determine the actual one.
