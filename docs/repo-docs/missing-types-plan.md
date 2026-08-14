# Missing catalog types — plan

_From `_MISSING_TYPES.md` and the raw `unknown/` listing (36 files)._

---

## ⚠️ First: the headline number is wrong

The report says **42 documents fit no catalog type**. The raw listing shows that is not what happened.

| what | count | status |
|---|---|---|
| **AI call failed** — 12 documents, **4 of them listed twice** (a re-run) | 16 files | ✅ **already fixed** by LP-462 (oversized) and LP-464 (truncation-retry) |
| **Already in the catalog** — 243 is a **Form 1098 recognised at 0.95** | 1 | → belongs to **missing EXTRACTORS**, not missing types |
| **Genuinely no catalog type** | **~21** | this plan |

**So the real gap is ~21 documents across 8 genres — not 42.** A third of the list was infrastructure noise
already resolved.

---

## ⚠️ Second: two genres are single-source

- **4 processing invoices — all from HR Loan Processing, LLC**
- **3 dashboard screenshots — all UWM**

**That is one borrower's workflow, not a market pattern.** The counts look like frequency and are not.
**Weigh these by value, not by count.**

---

## BUILD — five types

### 1. `temporary_buydown_agreement` · 3 docs (059, 067, 068)
⚠️ **Highest value per document in the set.** A subsidy schedule means **the borrower's actual payment
differs from the note payment** for the first year or two — so it **affects the qualifying payment**, and DTI
is what everything else hangs off.

**Schema:** loan #, lender, borrower(s), property, note rate, base monthly payment, subsidy amount and
account, **a payment-schedule list** (month range → effective rate, borrower payment, monthly subsidy),
prepayment/foreclosure clauses, signatory + date.

### 2. `uscis_notice_of_action` · 2 docs (062, 065) + absorbs 4 misroutes
**Feeds ID-8** (citizenship and residency eligibility). An I-797A with validity dates is exactly that
evidence. ⚠️ **Also absorbs `visa_documentation` 187/188/240 and `work_visa` 242 — effectively 6 documents.**

**Schema:** form type, receipt #, case type, received/notice dates, petitioner, beneficiary (name, A-number,
DOB, country), classification, **validity from/to**, I-94 block, service center.

### 3. `home_value_estimate` · 2 pure (070, 197) + 3 embedded (061, 063, 160)
Simple schema; the estimated value plus range is what a processor uses. ⚠️ **Not an appraisal** — an AVM is
not evidence of value for underwriting, and the type name should make that obvious.

**Schema:** property address, type, beds/baths, sqft, estimated value + low/high range, annual property
taxes, disclaimer.

### 4. `wire_instructions` · 2 docs (154, 158)
⚠️ **The highest operational and fraud risk content in the set** — ABA routing and account numbers, currently
landing in `general_correspondence`. **No rule reads it; the reason to build it is PII handling.** Typed and
masked beats free-form. *(158 already declines correctly post-LP-463.)*

**Schema:** firm/beneficiary name + address, bank name + address, **ABA routing # and account # — both
PII-registered**, account type, **verification phone**, reference note.

### 5. `certificate_of_liability_insurance` (ACORD 25) · 1 doc (073)
⚠️ **The count is a corpus artifact, not a frequency finding.** ACORD 25 is standard evidence for a condo
master policy and fidelity bond — **CO-3 reads exactly that.**

**Schema:** cert # and date, producer, insured, certificate holder, insurer(s) + NAIC, coverage lines
(CGL/Auto/WC) with policy #s and limits, project details.

---

## BUILD CHEAPLY — two types

### 6. `service_invoice` · 6 docs (064, 072, 079, 210, 058, 074)
One generic vendor-invoice schema covers processing, survey and credit-order invoices. **Low value per
document** — vendor, amount, loan number — but six documents and a trivial schema.

### 7. `lender_dashboard_screenshot` · 3 docs (061, 063, 160)
⚠️ **A type that deliberately extracts almost nothing.** These are software screenshots, not documents. **The
earlier analysis found declining to extract from them was CORRECT** — the value is stopping them diluting
`unknown` and, where an HVE block is embedded, routing that to `home_value_estimate`.

---

## SKIP — four genres

| genre | docs | why |
|---|---|---|
| `insurance_policy` (EO) · 071 | 1 | Lawyers' professional liability. **No rule reads it. Not property insurance.** |
| `entity_formation_doc` · 076 | 1 | ⚠️ **Tier 3 already handles this class well** — 075 returned project name, unit count, HOA structure and two real deed restrictions |
| `nc_mineral_oil_gas_disclosure` · 077, 078 | 2 | ⚠️ **State-specific, and the corpus is mostly one state.** The purchase-agreement lesson: building NC types from NC files is how you get fields that are always null elsewhere |
| `nc_property_disclosure` · 263 | 1 | Same — and it classified at **0.25**, the lowest in the set, so readability may be the real issue |

---

## RECLASSIFY — not a missing type

**243 — Form 1098**, recognised at **0.95**. ⚠️ **The type is already in the catalog; it has no extractor.**
→ **missing-extractors work.**

**066, 069 — closing packages.** ⚠️ **Not a missing type: two or more documents in one file** (CD + Note +
Deed of Trust + 1003 + riders). A flat schema cannot represent that. → **splitter work.**

---

## What building a type costs

**Four pieces**, and they are not equal:
1. a **catalog entry**
2. a **classifier indicator** — ⚠️ **catalog and classifier are CI-locked: both or neither**
3. a **JSON spec** — where the thought goes
4. **generate** the extractor, prompt and test

**Realistically one ticket per two or three types.**

---

## The rule that decides what earns a schema

**A type earns one for either reason:**
- **a rule reads it** — buydown (qualifying payment) · USCIS (ID-8) · ACORD 25 (CO-3)
- **a processor needs it reliably** — wire instructions, for PII handling rather than a rule

**Tier 3 gives visibility without reliability** — model-chosen labels, uncoerced values, and **no
deterministic rule may read it.** That is sufficient for the condo declaration and the EO policy.

---

## Suggested sequence

| ticket | types |
|---|---|
| **1** | `temporary_buydown_agreement` + `uscis_notice_of_action` — **both rule-relevant** |
| **2** | `home_value_estimate` + `wire_instructions` + `lender_dashboard_screenshot` — the AVM/dashboard pair belongs together |
| **3** | `certificate_of_liability_insurance` + `service_invoice` |

**Then:** the 1098 with the missing-extractor work; the closing packages with the splitter.
