# Schema-gap remediation plan

_From the 268-document bench-vs-free comparison. Three phases, in dependency order._

---

## Why the gaps exist — the root cause

The 108 schemas were derived **from the rules**, not from the documents.

A rule says *"compare the tax figure used to the assessed tax"*, so `annual_tax_amount` went into the schema.
Nothing in that rule mentions a per-jurisdiction breakdown, so **no list was declared**. The rules describe
conclusions; the documents arrive as tables that produce them.

A second reason compounded it: when the specs were written, a nested list cost **~5 hand-written files**
(LP-421's finding). That made lists expensive, so they were declared only where a rule demonstrably needed
one. **LP-437 reduced a list to a single declaration** — but the specs had already been written under the old
assumption and were never revisited.

**So these gaps were rational when the specs were authored and are cheap to close now.**

---

## PHASE 1 — Fix the nulls _(prompt / extractor, no schema change)_

The field exists and came back null anyway. **These are the highest-value fixes because they need no new
structure — the plumbing is already there and is producing nothing.**

| type | field | docs | note |
|---|---|---|---|
| **homeowners_insurance** | `replacement_cost_or_coinsurance_basis` | **104, 114, 116, 117** | ⚠️ **A LIVE RULE.** IH-1 was built on this field in LP-447. It is returning `couldnt_check` on 4 of 16 real policies **that carry the answer** |
| homeowners_insurance | `policy_form` | 105, 108, 113, 114, 117 | form code visible on the page |
| w2 | `statutory_employee_checked` | 083, 086, 096, 099 | checkbox determinable; feeds IN-12 |
| credit_report | `total_tradeline_count` | 2 / 2 | derivable from its own list |
| credit_report | `security_freeze_or_fraud_alert`, `address_usage_alert` | 250 | promoted in LP-445, not populating |
| credit_report | `inquiries` list empty, data in `catch_all` | 249 | **extractor bug** — the list exists, the data is misrouted |
| voe | `gross_earnings_history` | 226 | empty despite 4 pay dates on the document |
| property_tax_bill | `penalties_and_interest` | 169, 172 | `$0.00` line present |
| hoa_statement | `special_assessment_items` | 136 | empty despite a $235 line |
| investment/retirement | `account_number_masked` | 257, 267 | numbers visible on the page |

**⚠️ Do not treat `drivers_license.date_of_birth` / `address` as a null to fix** — those are a **bench
artifact**; the harness blanked them. The fields work.

**Effort:** prompt hints per field, plus one extractor bug (credit_report 249).
**Sequencing:** first. Independent of Phases 2 and 3, and it includes the only live-rule regression.

---

## PHASE 2 — Add the missing repeating-row lists

**The dominant pattern.** Six types where the substance of the document is a table with nowhere to land.

| type | list to add | evidence | note |
|---|---|---|---|
| **mortgage_statement** | `transaction_activity[]` | **12 / 13** | ⚠️ **no list at all today**; `_MAX_TOKENS` 4096 → **must bump to 8192** |
| **hoa_statement** | `payment_ledger[]` | **7 / 11** | on 135 this dropped **28 of 29 rows**. Already at 8192 |
| **retirement_account** | `holdings[]` | **3 / 3** | no list at all |
| **property_tax_bill** | `jurisdiction_breakdown[]` | **5 / 5** | installments list exists; this is a second one |
| **master_insurance_condo** | multi-row `coverage_lines[]` | **3 / 3** | list collapses to 1 row — on 238 dropped an entire Boiler & Machinery policy |
| **homeowners_insurance** | `coverage_lines[]` (B–F + per-line deductibles) | **~10 / 16** | only a scalar `coverage_amount` today |

**Plus one column addition:** `forms_and_endorsements` needs an **amount** column (4 docs; dropped a $1,402
line on 116).

**Effort:** spec edit + regenerate per type. **All `flat_row`** — the LP-437 mechanism handles them.
**⚠️ Watch `_MAX_TOKENS`** on the flat-capped types.

---

## PHASE 3 — Add the missing fields

**Geet's decisions applied:** `sex`, `height` and `eye colour` are **excluded** from driver's licences.
`PTO balances` and `payroll processor name` are **included**.

### pay_stub (30 docs)
`net_pay_ytd` **16** · taxable-wage bases (fed/medicare/OASDI/state, current+YTD) **13** · employer-paid
benefits **11** · employer phone **9** · per-category deduction subtotals **8** · PTO/absence balances **5** ·
YTD hours **4** · payroll processor name **3** · check/payment status (VOID) **1**

### w2 (22 docs)
State block Box 15–17 **18** · Box 12 codes **14** _(needs a small nested list)_ · Box 13 third-party sick pay
**9** · control number **7** · local Box 18–20 **3**
⚠️ `_MAX_TOKENS` is **4096** — the Box 12 list likely needs a bump.

### bank_statement (25 docs)
⚠️ **Multi-account representation — 5 docs. This is DATA LOSS, not a missing field:** on **046 and 057 real
transaction rows were dropped** because the schema assumes one account per statement.
Also: fee-waiver options + service-fee waived flag **6** · per-transaction source IDs **4** · statement
reference code **4**

### drivers_license (10 docs)
Class **9** · restrictions **9** _(encodes legal-presence / immigration-expiry on 143, 147)_ · endorsements
**7** · DD/audit number **6**
**Excluded per Geet:** sex, height, eye colour.

### purchase_agreement (5 docs)
⚠️ Due-diligence fee + **additional EMD distinct from `earnest_money_amount`** — on **183 a $204k additional
EMD was understated** · buyer-default remedy · title conveyance · survey-paid-by · as-is · lead-paint ·
option fee + termination-option period (TREC) · financing type / LTV / DSCR

### tax_return (4 docs)
State-return figures **4 / 4** (PA-40 / NC D-400 / AZ 140PY) · per-employer W-2 breakdown · preparer
identity · Schedule D / Form 8949 capital-gains list **2 / 4**

### credit_report · gift_letter · voe · property_tax_bill · payoff_statement · hoa_statement
Alias/AKA names **2/2** · order provenance · `loan_number` on gift letters **3/3** · VOE work location vs
corporate address · staffing-agency client assignment · solid-waste fees · interest-begins date · legal
description/PIN · FDCPA notice · lender NMLS · HOA statement period range · prior/starting balance · owner
email

### letter_of_explanation family (12 docs)
A repeating `explanation_items[]` list for multi-item letters (base 215 dropped a second inquiry date) ·
verbatim inquiry text · `loan_number` / `property_address`
⚠️ **Separately:** the base `letter_of_explanation` schema is **credit-inquiry-shaped** and is being used as a
wrong-type proxy for employment-verification (155) and refi-benefit (213) letters. **That is a type problem,
not a field gap** — it belongs with the missing-types work.

---

## Sequencing

**Phase 1 first** — no schema change, and it fixes a live rule.

**Phases 2 and 3 touch the same spec files.** Doing them per type in one pass avoids regenerating twice —
but they are different kinds of change and worth reviewing separately. **Suggested: one ticket per phase,
but group the work by document type inside each.**

**⚠️ Regeneration safety:** every change must go in the **JSON spec**, not only the generated module —
LP-445 proved a spec-only edit regenerates byte-identically, and a module-only edit would be lost.

**⚠️ Equivalence:** 37 live rules must produce identical verdicts throughout, **except** where a Phase-1 fix
deliberately improves one (IH-1). **Any other movement is a real finding.**
