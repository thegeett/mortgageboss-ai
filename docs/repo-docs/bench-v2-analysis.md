# Bench re-run (v2) — deep analysis

_303 documents, run `8c999b3f7a1b`, against the same free-read baseline. **Every difference vs v1 is
attributable to LP-434 → LP-470.**_

---

## The scorecard — apples to apples on the 276 documents both runs processed

| metric | v1 | v2 | |
|---|---|---|---|
| **Succeeded with a schema** | 194 | **229** | ▲ **+35** |
| no_extractor | 64 | **44** | ▼ −20 |
| Extractor failures | 10 | **3** | ▼ −7 |
| Classification AI-call failures | 8 | **0** | ▼ **eliminated** |

**Full v2 run (303):** succeeded **243 (80%)** · no_extractor 56 · failed 3 · partial 1.

**33 documents captured by 9 new types**, plus `closing_disclosure` (9) and `loan_estimate` (3) now
extracting where v1 had nothing.

---

## What is validated as fixed

**Every field and list gap v1 flagged now populates.** Not "mostly" — the report checks each one:

`mortgage_statement.transaction_activity` **12/12** *(v1: empty)* · `hoa_statement.payment_ledger`
*(135: 30 rows · 140: 36 rows)* · `w2` Box 15-17 **and** the Box 12 list *(18/22 and 14/22 v1 gaps closed)* ·
`pay_stub` YTD-net, federal taxable wages, employer phone, VOID status · `homeowners_insurance` coverage
lines **and** endorsement amounts · `retirement_account` holdings · `property_tax_bill` jurisdiction
breakdown · `drivers_license` class/restrictions/endorsements · LOX `explanation_items` · `gift_letter`
loan_number · `voe` work_location.

**The crash clusters are gone.** The `ValueError` cluster (URLA 205/206 → 31 typed + 94 catch-all; leases;
investment 257 → 29 positions), and every RateLimit crash.

**And the two force-apply harms:** T4s no longer emit plausible-but-wrong US W-2 numbers; **271 recovered
~$164k of wages** previously lost to a `1099` mislabel.

⚠️ **The schema layer also beat the free reader again** — 162 (free put a $1,255,000 sale price into
`loan_amount`), 182/183 (v1's "buyer/seller swap" was the *free reader's* error), 259, 291, and four W-2s.

---

## ⚠️ THE COST SIDE — this is the finding that matters

### 1. The classifier became more conservative, and over-corrected

**~14 documents that v1 extracted now drop to `unknown` / `no_extractor` / failed.**

| doc | v1 → v2 | lost |
|---|---|---|
| **222** | offer_letter → **extraction FAILED to empty** | ⚠️ **SEVERE** — v1 had 14 typed + 21 catch-all |
| 132 | hoa_statement → unknown | a real HOA statement |
| 177, 178 | lease_agreement → unknown | 12 fields each |
| 196 | tax_return → unknown | a 1040 package, **lost the K-1 list** |
| 202 | title_commitment → unknown | Schedule A/B |
| **204** | URLA → unknown | ⚠️ **a 1003 — and the URLA extractor demonstrably works on 205/206** |
| 208, 209 | earnest_money_receipt → unknown | |
| 211 | evidence_of_payment → unknown | |
| 236 | LOX_property → general_correspondence | 16 occupancy fields |
| 265 | PRC → passport/no_extractor | all identity fields *(265/266 appear swapped)* |

**Plus field-level drops with the type kept:** 219 (`issuer_name`→null) · **251** (freeze/fraud + address
alerts + `date_opened`→null) · 119 (`delinquency_status`→null).

**The diagnosis is precise:** LP-463 made declining legitimate — **correctly**, and it is why T4s, HOA budgets
and portal screenshots are no longer force-fit. **But the classifier now abstains when a specialised type is
not a clean match**, even where that type exists and its extractor works.

⚠️ **We measured the benefit of declining and never measured its cost. This is the cost.**

### 2. New accuracy errors — the confident-wrong class

Nine, and they are a different failure from a gap:

**088** fabricated Texas state tax (= federal Box 2; **Texas has no state income tax**) · **091** retirement
checkbox regressed · **096** Box 12 misread (code C carrying the Medicare value; DD dropped) ·
**104** `replacement_cost_or_coinsurance_basis` = *"coinsurance contract"* on a replacement-cost HO3 ·
**146 & 294** hallucinated DL values on hard scans (294 read a DL-back as a vehicle registration and
fabricated a date) · **244** the 1098 taxes field echoing the interest value · **253** a gift amount read as
**$224,307.94** instead of **$24,307.94** · **293** wrong check dates.

⚠️ **A missing field returns `couldnt_check`. A wrong field returns a confident wrong verdict.**
**253 is a $200,000 error on an asset field.**

### 3. Carried-over bugs, still open

**`loan_number_masked` stores the UNMASKED number** across mortgage statements — ⚠️ **a PII violation whose
field name conceals it.** · **049** a Zelle amount holding the running balance ($732.27 vs $700.00) ·
**pay_stub `employee_ssn_masked` holding bank/SIN digits** (018/019/020/027) · `pay_frequency` mis-inference
(012/028/030) · **credit_report `date_opened` fabricating a day-of-month from MM/YY.**

---

## The three remaining extractor failures

| doc | error | note |
|---|---|---|
| **222** | empty failure, **no error type recorded** | ⚠️ **A REGRESSION** — v1 handled it. A Services Agreement misfiled as an offer letter: both a classification and an extraction problem |
| **069** | `BadRequestError` on **extraction** | ⚠️ **The classification-side size fix did not cover extraction** — the same one-call-path lesson as LP-464. A 6+MB package |
| **174** | `ValueError` | The one lease still failing; siblings 175/176 now succeed. Likely a scanned page |

---

## ⚠️ The single highest-leverage fix

> **Add a Tier-3 fallback whenever extraction errors or a type has no extractor.**

**One change rescues:** the 7 LOX emails · the 34 `unknown` documents · **069 and 222** · and every future
failure.

**Today a `no_extractor` or a crash yields *nothing*.** With a fallback it degrades to structured
key-fields — parties, amounts, dates — instead of empty. **Nothing would ever be fully lost again.**

---

## Recommended order

| # | action | why |
|---|---|---|
| **1** | ⚠️ **Tier-3 fallback on no_extractor + extraction error** | **The single highest-leverage change.** Rescues ~40 documents at once and makes every future failure degrade gracefully |
| **2** | **222 · 069 · 174** | 222 first — a regression on a type v1 handled. 069 mirrors LP-464's fix onto the extraction path |
| **3** | ⚠️ **Tune the classifier's new conservatism** | **Keep the good demotions** (T4, HOA budget, portals — give them their own types). **Stop dropping real EMD receipts, title binders, 1003s, tax packages and offer letters.** Positive cues for types whose extractors already work |
| **4** | **The accuracy-audit layer** | ⚠️ **Now is the right time** — the schema is broad and filled confidently, so wrong values are the dominant residual risk. Catches 088 (a state with no income tax), 091, 096, 244, 253's magnitude, 293's dates |
| **5** | `loan_number_masked` + the mortgage_statement breadth | A live PII violation |
| **6** | The niche extractors | warranty_deed, passport, CD, money_market, credit_explanation_letter |

---

## ⚠️ What this means for the rule-engine plan

**Phase 1 of `finish-the-rule-engine-plan.md` is now answered** — the fields populate, and the fill rates are
in `_SCHEMA_GAPS.md` per type.

**But do NOT go straight to Phase 2 (writing tags).** Two reasons:

1. ⚠️ **The regressions must be fixed first.** Writing a tag against `hoa_statement` or `tax_return` fields
   is pointless while those documents drop to `unknown`.
2. ⚠️ **The accuracy layer should come BEFORE tags at scale.** A tag on a wrong value is worse than a tag on
   a missing value — 253's $224k and 088's fabricated state tax are exactly what a rule would consume
   confidently.

**Revised sequence: fallback → regressions → accuracy layer → then tags.**

---

## The bottom line

**v2 is a decisive, measured improvement.** +35 documents extracting, crashes 10 → 3, classification crashes
8 → 0, and every flagged field and list gap closed.

**The cost is a cluster of reclassification regressions from a more conservative classifier — one severe —
and nine new accuracy errors from a broader, more confident schema.**

⚠️ **Both are addressable, and both were only visible because the run was repeated against the same corpus.**
