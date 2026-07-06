# LP-116 — Extraction / Schema Registry Audit (read-only)

**Status:** complete · **Type:** read-only spike · **Epic:** Phase 3.5 / Epic A
**Date:** 2026-07-06 · **Author:** LP-116 audit · **Companion to:** LP-115 (live-rule inventory)

> Maps what the system extracts **today** — every classifiable document type, the exact
> structured fields each type's extractor produces, and therefore which verification rules
> are truly feedable vs. blocked on a missing schema. Replaces reconstructed-from-memory
> claims (e.g. "insurance probably has a schema, brokerage had no extractor") with facts +
> file:line evidence. **No code was changed.**

---

## 1. Summary — headline numbers + blocker status

- **88 document types** are cataloged and classifiable (`app/documents/catalog.py`, 88 slug
  entries across 7 categories); anything **uncataloged** falls to the Tier-3 generic analyzer.
- **18 types have a Mode-1 extraction schema** (a typed-core Pydantic model that produces
  structured fields deterministic rules can read) — the `EXTRACTORS` registry
  (`app/ai/extraction/__init__.py:61-88`). All 18 are Tier 1.
- **70 types are classify-only** (Tier 2): recognized + categorized + a 1–2 sentence AI
  summary, **no structured fields** (`_tier2_summarize`, document_processing.py:227).
- **Only 2 of the 18** extractors produce structured data beyond the flat typed-core +
  free-text catch-all: `bank_statement` (a first-class `transactions[]` list) and `tax_return`
  (nested 1040 + Schedule C/E/K1 bundle).
- **All 18 document extractors are AI (Claude) calls** — no lxml/XPath. The **deterministic**
  parsing is the separate MISMO/URLA XML import (`app/mismo/parser.py`, lxml/XPath), which owns
  the source-of-truth **stated** financials. Cross-source rules compare MISMO-parsed *stated*
  rows vs. AI-extracted *documented* values.

### The 6 blocker documents

| Blocker doc | Cataloged type | Tier | Extraction schema | Verdict |
|---|---|---|---|---|
| Homeowners insurance | `homeowners_insurance` | **Tier 1** | **PARTIAL** — 7 typed fields; mortgagee-clause & deductible in catch-all only | **EXTEND** |
| Credit report | `credit_report` | Tier 2 | **NONE** (classify-only) | **BUILD** |
| Appraisal (URAR) | `appraisal` | Tier 2 | **NONE** (classify-only) | **BUILD** |
| Flood determination (SFHDF) | `flood_certification` | Tier 2 | **NONE** (classify-only) | **BUILD** |
| Title commitment (ALTA) | `title_commitment` | Tier 2 | **NONE** (classify-only) | **BUILD** |
| AUS / DU findings | **not cataloged** | Tier 3 default | **NONE** (not even a recognized type) | **BUILD + catalog** |

**Tax returns** (not one of the 6, but explicitly asked): `tax_return` is **Tier 1 with a full
nested schema** (1040 core + Schedule C/E/K1) — **present, extend if needed**, not build (but
accuracy is unproven — see §7).

---

## 2. Classification vs. extraction split + no-extractor fallback

Two separate steps (confirmed):

1. **Classification** (`app/ai/classification.py`) — a cheap Haiku-class model reads the full
   document bytes and returns a `document_type` slug + confidence. It never extracts fields.
   The slug list is generated from the catalog (`app/ai/classification_prompt.py`), so the
   classifier can only return cataloged types. Failure/low-confidence → `unknown` at zero
   confidence → `NEEDS_REVIEW` (classification.py:12-30).
2. **Tier routing** (`app/tasks/document_processing.py:195-207`) — after classification, the
   catalog's tier decides handling:
   - **Tier 1** → `EXTRACTORS.get(type)`; if present, run the extractor; **if absent →
     `_complete_classified_only`** (COMPLETED, no fields — document_processing.py:200-203).
   - **Tier 2** → `_tier2_summarize` — a 1–2 sentence summary, no structured fields (:227).
   - **Tier 3** (uncataloged long-tail) → `_tier3_analyze` — generic analyzer (:206).

**No-extractor fallback = silent-but-terminal.** A type with no registered extractor produces
**no structured fields** and is marked COMPLETED as "classified-only" (document_processing.py:200-203,
and the reprocess path :396-399). It does not crash and does not error — so a rule waiting on
that type's fields simply never receives them. **This is exactly the "blocked-on-a-missing-schema"
case**: the document is filed and recognized, but yields nothing for deterministic rules.

---

## 3. The extraction registry — "what we extract today" field map

All 18 extractors share the LP-39a shape (`app/ai/extraction/shape.py`): a **typed core**
(`TypedField[T]`: coerced value + `{page, snippet}` source — feeds deterministic rules) plus a
free-text **catch-all** (`additional_sections: list[CatchAllSection]` — strings, not coerced;
read only by the AI cross-source pass, never by deterministic rules). **Every typed field is
AI-extracted** (no deterministic parsing in these modules).

| Type (Tier 1) | Category | Typed-core fields (name: type) | Structured lists | Notes |
|---|---|---|---|---|
| `pay_stub` | Income | employer_name:str, employee_name:str, pay_period_start:date, pay_period_end:date, pay_date:date, gross_pay:Decimal, net_pay:Decimal, **ytd_gross:Decimal**, pay_frequency:str, hours:Decimal, rate:Decimal | — | 8192 tok; LP-102 truncation class |
| `w2` | Income | tax_year:int, employee_name:str, **employee_ssn:str**, employer_name:str, employer_ein:str, wages_tips_other_comp:Decimal, federal_income_tax_withheld:Decimal, social_security_wages:Decimal, ss_tax_withheld:Decimal, medicare_wages:Decimal, medicare_tax_withheld:Decimal | — | SSN sensitive, masked display |
| `1099` | Income | form_subtype:str, payer_name:str, payer_tin:str, recipient_name:str, **recipient_tin:str**, tax_year:int, income_amount:Decimal | — | TIN sensitive |
| `voe` | Income | employer_name:str, employee_name:str, position_title:str, employment_status:str, start_date:date, end_date:date, current_income_amount:Decimal, income_frequency:str, **ytd_income:Decimal**, hours:Decimal, probability_of_continued_employment:str | — | employer-verified income |
| `profit_and_loss` | Income | business_name:str, period_start:date, period_end:date, total_revenue:Decimal, total_expenses:Decimal, **net_profit:Decimal** | — | 8192 tok; LP-102 class |
| `tax_return` | Income | tax_year:int, filing_status:str, taxpayer_names:str, **taxpayer_ssn_masked:str**, total_income:Decimal, adjusted_gross_income:Decimal, wages:Decimal, taxable_income:Decimal | **schedule_c[]** (business_name, gross_receipts, total_expenses, net_profit); **schedule_e** (properties[]: address, rents_received, total_expenses, net_income; total_net_rental_income, depreciation); **k1s[]** (entity_name, ownership_pct, ordinary_income) | 16384 tok (largest); nested bundle; accuracy unproven |
| `bank_statement` | Assets | account_holder_name:str, bank_name:str, account_number_masked:str, account_type:str, statement_period_start:date, statement_period_end:date, **beginning_balance:Decimal, ending_balance:Decimal**, total_deposits:Decimal, total_withdrawals:Decimal | **transactions[]** (date, description, amount, transaction_type, running_balance) | 8192 tok; hardest type; LP-102 class |
| `investment_account` | Assets | institution_name:str, account_holder:str, account_number_masked:str, account_type:str, statement_period_start:date, statement_period_end:date, **total_value:Decimal** | — (holdings→catch-all) | 8192 tok; **LF-6T3N silent-truncation incident** (understated reserves) |
| `retirement_account` | Assets | institution_name:str, account_holder:str, account_number_masked:str, account_type:str, statement_period_start:date, statement_period_end:date, **vested_balance:Decimal, total_balance:Decimal** | — (holdings→catch-all) | 8192 tok; LP-102 class |
| `gift_letter` | Assets | donor_name:str, donor_relationship:str, recipient_name:str, **gift_amount:Decimal**, property_address:str, no_repayment_attestation:str | — | attestation-oriented |
| `purchase_agreement` | Property | buyer_name:str, seller_name:str, property_address:str, **sales_price:Decimal**, closing_date:date, earnest_money_amount:Decimal | — | 8192 tok; LTV/price basis |
| `homeowners_insurance` | Property | carrier_name:str, policy_number:str, property_address:str, **coverage_amount:Decimal** (=dwelling), **annual_premium:Decimal**, effective_date:date, expiration_date:date | — | **mortgagee-clause & deductible ONLY in catch-all** |
| `mortgage_statement` | Property | lender_name:str, property_address:str, **monthly_payment:Decimal**, unpaid_balance:Decimal, escrow_amount:Decimal, due_date:date | — | DTI obligation |
| `property_tax_bill` | Property | property_address:str, assessed_value:Decimal, **annual_tax_amount:Decimal**, due_dates:str, taxing_authority:str | — | due_dates kept as str (two installments) |
| `hoa_statement` | Property | association_name:str, property_address:str, **dues_amount:Decimal**, dues_frequency:str, balance:Decimal, due_date:date | — | obligation |
| `drivers_license` | Borrower | full_name:str, **date_of_birth:date**, **address:str**, id_number_masked:str, issuing_state:str, issuing_authority:str, expiration_date:date | — | **NO SSN, NO issue_date**; DOB+address present |
| `divorce_decree` | Borrower | party_1_name:str, party_2_name:str, effective_date:date | **support_obligations[]** (obligation_type, amount, frequency, payer); **property_awards[]** (description, awarded_to) | obligations captured, not yet surfaced as findings |
| `letter_of_explanation` | Borrower | subject:str, explanation_summary:str, referenced_employer:str, referenced_date:date, referenced_amount:Decimal | — | deliberately light core |

**Deterministic-vs-AI note (Step 3):** within the document-extraction path, **every typed field
above is AI-extracted** — there is no lxml/XPath in `app/ai/extraction`. The
"deterministic-owns-financial-data" principle refers to the **MISMO import** (`app/mismo/parser.py`,
lxml/XPath, no AI), which populates the **stated** side: `Borrower.ssn` (encrypted),
`Borrower.date_of_birth`, `StatedEmployer.employer_name`, `StatedIncomeItem.monthly_amount`,
`StatedLiability.{holder_name, monthly_payment, unpaid_balance}`, `StatedAsset.{value, holder_name,
asset_type}` (incl. `GiftOfCash`), `Property.{address, purchase_price, occupancy_type,
estimated_value}`, `LoanFile.{base_loan_amount, note_rate_percent, loan_purpose, …}`. **Known
stated-side gap:** the borrower's current residential address is *parsed but not persisted* (no
column on `Borrower`) — see §5.

---

## 4. The 6-blocker deep-dive (build vs. extend, with missing fields)

Because **no `verification_rule_playbook.xlsx` and no `blocker_extraction_schemas.md` are
committed** (`find . -iname '*playbook*' -o -iname '*blocker*'` empty), "missing fields" below
are judged against the standard mortgage-QC field-set for each doc, not a committed spec —
flagged so a later ticket can tighten against Priya's real target lists.

1. **Homeowners insurance — PARTIAL → EXTEND.** Present (typed): `carrier_name`, `policy_number`,
   `property_address`, `coverage_amount` (dwelling), `annual_premium`, `effective_date`,
   `expiration_date` (homeowners_insurance.py:46, `_CORE_SPEC` :89-97). **Missing as typed
   fields (currently catch-all only):** **mortgagee / lender clause** (needed for IH-2), **deductible**
   (IH-1 adequacy), replacement-cost vs. dwelling breakout, other/liability/contents coverages,
   loan number. **Extend = promote mortgagee-clause + deductible (+ maybe replacement-cost) from
   catch-all into the typed core.** This confirms the suspicion: **insurance already has a schema;
   the insurance rules tagged NOW are feedable for premium/coverage/dates, blocked only for
   mortgagee/deductible.**
2. **Credit report — NONE → BUILD.** Tier 2, classify-only. No liabilities, no scores, no
   tradelines are produced. Blocks every `CR-*` rule and the two `xsrc.liability.*` rules
   (undisclosed-debt / stated-not-on-report). Target fields: representative/mid score per
   bureau, tradelines[] (creditor, balance, monthly payment, status), derogatory events
   (BK/FC/CO dates), inquiries.
3. **Appraisal (URAR) — NONE → BUILD.** Tier 2, classify-only. Blocks appraised-value,
   MPR/condition, occupancy-evidence, subject-address-from-appraisal. Target: appraised value,
   subject address, GLA, condition/C-rating, subject-to-repairs, comps.
4. **Flood determination (SFHDF) — NONE → BUILD.** Tier 2, classify-only. Target: flood zone,
   SFHA in/out, panel/community number, determination date, life-of-loan indicator.
5. **Title commitment (ALTA) — NONE → BUILD.** Tier 2, classify-only. Target: vesting/owner,
   Schedule B exceptions, liens, legal description, effective date, policy amount.
6. **AUS / DU findings — NONE → BUILD + CATALOG.** Not in the catalog at all → any such upload
   classifies as `unknown` or lands in Tier 3 generic analysis. Needs a catalog entry **and** a
   schema. Target: recommendation (Approve/Eligible), findings/conditions[], DTI/LTV as
   calculated by DU, required-docs list.

**Answers to the two named questions:**
- **Insurance:** schema **EXISTS** (Tier-1, 7 typed fields) → **EXTEND** (add mortgagee-clause +
  deductible), do not build from scratch.
- **Tax returns:** schema **EXISTS** and is the richest in the codebase (1040 + Schedule C/E/K1
  nested, tax_return.py:112-137) → **present; extend/validate**, do not build. Caveat: accuracy
  is unproven — the tests exercise the nesting mechanism/shape, not correctness against real
  returns (tax_return.py docstring; §7).

---

## 5. Seed-rule field coverage — extractor-gap vs. fact-builder-gap (Epic C input)

For each LP-115 fact-starved cross-source rule, this states whether the data already exists on
**both** sides (documented extractor + stated MISMO) and therefore whether the fix is a
**fact-builder gap** (data flows, just not wired into `CrossSourceFacts` by
`build_cross_source_facts`) or an **extractor gap** (a document schema genuinely doesn't produce
the field). The fact-builder currently wires only doc `name`/`address`(DL-only)/`employer` fields
(`services/cross_source.py` `_verified_documents`/`_typed_fields`; `build_cross_source_facts`,
cross_source_deterministic.py:181-262).

| Fact-starved rule (fact field) | Documented side extracted? | Stated side present? | **Gap type** |
|---|---|---|---|
| `ssn_consistency` (`ssns`) | ✅ w2.employee_ssn, 1099.recipient_tin, tax_return.taxpayer_ssn_masked | ✅ Borrower.ssn | **FACT-BUILDER** |
| `dob_consistency` (`dobs`) | ✅ drivers_license.date_of_birth | ✅ Borrower.date_of_birth | **FACT-BUILDER** |
| `current_address_consistency` (`current_addresses`) | ✅ drivers_license.address (+ property_address on many docs) | ⚠️ parsed-not-persisted (Borrower address, §3) | **FACT-BUILDER** (doc side) **+ stated persistence gap** |
| `price_vs_contract` (`stated_/contract_purchase_price`) | ✅ purchase_agreement.sales_price | ✅ Property.purchase_price | **FACT-BUILDER** (both sides exist — fastest win) |
| `subject_address_consistency` (`subject_addresses_across_docs`) | ✅ property_address on purchase_agreement / homeowners_insurance / mortgage_statement / property_tax_bill / hoa_statement | ✅ Property.address | **FACT-BUILDER** |
| `income_variance` (`documented_income_monthly`) | ✅-ish pay_stub.ytd_gross/gross_pay, voe.ytd_income/current_income_amount | ✅ StatedIncomeItem.monthly_amount | **FACT-BUILDER + light computation** (YTD/period → monthly) |
| `large_deposit_unsourced` (`unsourced_large_deposits`) | ✅-raw bank_statement.transactions[] | — | **FACT-BUILDER + logic** (scan transactions) |
| `stated_asset_missing_doc` (`stated_assets_missing_doc`) | ✅ asset docs exist (bank/investment/retirement) | ✅ StatedAsset | **FACT-BUILDER + matching logic** |
| `employer_equals_subject` (`employer_addresses`) | ⚠️ employer **address** is catch-all, not typed | n/a (subject persisted) | **EXTRACTOR** (promote employer address to typed core on pay_stub/w2/voe) |
| `undisclosed_debt` (`credit_report_liabilities`) | ❌ credit_report has no extractor | ✅ StatedLiability | **EXTRACTOR** (blocker: credit report) |
| `stated_not_on_report` (`credit_report_liabilities`) | ❌ same | ✅ StatedLiability | **EXTRACTOR** (blocker: credit report) |
| `loan_vs_documented` (`documented_loan_amount`) | ❌ note/closing-disclosure not extracted | ✅ LoanFile.base_loan_amount | **EXTRACTOR** (blocker: CD/note) |
| `occupancy_vs_evidence` (`stated_/occupancy_evidence`) | ⚠️ stated ✅ (Property.occupancy_type); evidence ❌ (needs appraisal/lease/utility) | ✅ (stated) | **EXTRACTOR** (evidence side — appraisal/lease) |

**Key takeaway for Epic C:** of the 13 fact-starved rules, **~8 are fact-builder gaps** (the
data already flows or is a small transform away — `ssn`, `dob`, `current_address`,
`price_vs_contract`, `subject_address`, `income_variance`, `large_deposit`, `asset_missing_doc`)
and only **~5 are true extractor gaps** blocked on a missing schema (`credit_report` ×2,
`documented_loan_amount`, `occupancy_evidence`, and the employer-address promotion). The
fact-builder gaps are the fast wins; the extractor gaps map onto the §4 blockers.

---

## 6. Rule → required-docs → schema-present → feedable/blocked cross-reference

Live/near-live cross-source rules (from LP-115) against the schemas that feed them. "Feedable"
means the required document's schema produces the needed field today.

| Rule | Required doc(s) | Schema present? | Feedable / Blocked |
|---|---|---|---|
| `xsrc.identity.name_consistency` | any name-bearing doc + MISMO | ✅ (pay_stub/w2/DL name; MISMO) | **feedable (fires today)** |
| `xsrc.income.employer_name_consistency` | pay_stub/w2/voe + MISMO employers | ✅ | **feedable (fires today)** |
| `xsrc.income.employer_count_matches_items` | MISMO employers + income items | ✅ (MISMO) | **feedable (fires today)** |
| `xsrc.asset.gift_without_letter` | gift_letter + MISMO gift asset | ✅ | **feedable (fires today)** |
| `xsrc.address.dl_equals_subject` | drivers_license + Property | ✅ | **feedable (fires today)** |
| `xsrc.identity.ssn_consistency` | w2/tax_return + MISMO | ✅ present, **not wired** | feedable — **fact-builder gap** |
| `xsrc.identity.dob_consistency` | drivers_license + MISMO | ✅ present, not wired | feedable — **fact-builder gap** |
| `xsrc.terms.price_vs_contract` | purchase_agreement + Property | ✅ present, not wired | feedable — **fact-builder gap** |
| `xsrc.property.subject_address_consistency` | property-bearing docs + Property | ✅ present, not wired | feedable — **fact-builder gap** |
| `xsrc.income.stated_vs_documented` | pay_stub/voe + MISMO income | ✅-ish, not wired | feedable — **fact-builder + compute** |
| `xsrc.asset.large_deposit_unsourced` | bank_statement transactions | ✅-raw, not wired | feedable — **fact-builder + logic** |
| `xsrc.asset.stated_missing_document` | asset docs + MISMO assets | ✅, not wired | feedable — **fact-builder + matching** |
| `xsrc.liability.undisclosed_debt` | **credit_report** + MISMO liabilities | ❌ no credit schema | **BLOCKED (build credit report)** |
| `xsrc.liability.stated_not_on_report` | **credit_report** | ❌ | **BLOCKED (build credit report)** |
| `xsrc.terms.loan_vs_documented` | **closing_disclosure / note** | ❌ | **BLOCKED (build CD/note)** |
| `xsrc.property.occupancy_vs_evidence` | **appraisal / lease** (evidence) | ❌ | **BLOCKED (build appraisal)** |
| `xsrc.address.employer_equals_subject` | pay_stub/w2 employer **address** | ⚠️ catch-all only | **BLOCKED (extend: promote employer address)** |

Insurance/DTI-adjacent planned rules (phase3_5_1.md:229-233): `MI-1` PMI / `MI-4` FHA MIP are
calculator-surfaced (LP-115 §7), `IH-1`/`IH-2`/`DT-5` need the insurance schema — **premium +
coverage + dates are feedable now; mortgagee-clause + deductible are blocked pending the EXTEND.**

---

## 7. Extraction reliability concerns (noted, NOT fixed)

1. **LP-102 silent-truncation class.** List-bearing extractors emit long JSON; an undersized
   `_MAX_TOKENS` truncates mid-JSON → silent parse-fail → empty `NEEDS_REVIEW`/classified-only.
   Concrete past incident: **`investment_account` on LF-6T3N** — a 4096 cap silently truncated a
   dense portfolio and **understated reserves** (investment_account.py docstring). Mitigated by
   bumping caps to 8192/16384 + the shared `model_call` truncation guard, but the failure mode is
   structural and un-evaluated. Highest-risk types: `bank_statement`, `tax_return`,
   `investment_account`, `retirement_account`, `profit_and_loss`, `purchase_agreement`.
2. **Accuracy unproven across the board.** Every typed core is a "V1 starter — refine with Priya"
   and untested against real labeled documents (catalog.py & per-extractor docstrings).
   `tax_return` explicitly: tests verify the nested *shape*, not correctness against real returns.
3. **No plausibility check.** Extraction "reads, doesn't judge" (pay_stub.py:19-21) — a
   misread `gross_pay` or `net_profit` is stored verbatim and flows into DTI/reserves with no
   sanity gate. A future eval-set ticket owns this.
4. **Stated borrower-address persistence gap.** MISMO parses the borrower's current address but
   no column persists it (import_service.py:27-29) — so `current_address_consistency` is missing
   *one side* even after the fact-builder is wired.
5. **`property_tax_bill.due_dates` and `pay_stub.pay_frequency` are free strings**, not
   normalized — fine for display, but a rule keying on them needs its own parsing.
6. **AUS/DU not cataloged** — a common, high-value document silently degrades to Tier-3 generic
   analysis; it should at minimum be cataloged so it is recognized.

---

## Appendix — evidence file map

| area | files |
|---|---|
| Catalog (88 types, tiers) | `app/documents/catalog.py` |
| Classifier | `app/ai/classification.py`, `app/ai/classification_prompt.py` |
| Extractor registry (18) | `app/ai/extraction/__init__.py` |
| Extraction shape (typed core + catch-all) | `app/ai/extraction/shape.py` |
| Per-type extractors | `app/ai/extraction/{pay_stub,w2,bank_statement,form_1099,voe,profit_and_loss,tax_return,investment_account,retirement_account,gift_letter,purchase_agreement,homeowners_insurance,mortgage_statement,property_tax_bill,hoa_statement,drivers_license,divorce_decree,letter_of_explanation}.py` |
| Tier routing + no-extractor fallback | `app/tasks/document_processing.py:195-207, 227, 388-399` |
| Deterministic stated side (MISMO) | `app/mismo/{parser,schema,import_service}.py`, `app/models/{borrower,stated_financials,property,loan_file}.py` |
| Fact-builder wiring (doc fields → CrossSourceFacts) | `app/services/cross_source.py` (`_verified_documents`, `_typed_fields`), `app/services/cross_source_deterministic.py:181-262` |
| Plan / blocker references | `docs/phases/phase3_5_1.md` |
