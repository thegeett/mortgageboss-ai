# Fact-Namespace Foundation — data-storage audit (read-only)

**Status:** complete · **Type:** read-only investigation · **Epic:** Phase 3.5 (pre-LP-119)
**Date:** 2026-07-07 · **Grounding:** [`LP-115`](LP-115-live-rule-inventory.md) (live rules),
[`LP-116`](LP-116-extractor-schema-registry.md) (extraction schemas)

> Maps how the data a verification rule might reference is actually stored today — enum vs
> raw string, queryable entity vs buried JSON, stored vs computed, per-borrower vs per-loan —
> to inform the design of a "fact namespace" (the addressable map of every field an
> applicability/evaluator rule can read). Every claim carries file:line evidence. **No code
> changed.** Paths are relative to `backend/` unless noted.

---

## 1. ENUM vs RAW STRING (program / purpose / occupancy / property type)

**Verdict: all four are NORMALIZED ENUMS on the model, stored as their lowercase string value.
Applicability can compare clean enums — the normalization already happens at MISMO-import time.
The one caveat is the import map is exact-match, so an unmapped MISMO code silently lands `None`.**

| Field | Model.column | Type | Stored values |
|---|---|---|---|
| Loan program | `LoanFile.loan_program` (`loan_file.py:155`) | `str_enum(LoanProgram)` | `"conventional"`, `"fha"` only (`lender.py:37-38`; VA/USDA/Jumbo deferred to V2, `lender.py:33-34`) |
| Loan purpose | `LoanFile.loan_purpose` (`loan_file.py:156`) | `str_enum(LoanPurpose)` | `"purchase"`, `"refinance"` (`loan_file.py:81-82`) |
| Refinance kind (cash-out) | `LoanFile.refinance_type` (`loan_file.py:159`) | `str_enum(RefinanceType)` | `"rate_term"`, `"cash_out"` (`loan_file.py:94-95`) — the cash-out axis is a **separate** field from purpose |
| Occupancy | `Property.occupancy_type` (`property.py:83`) | `str_enum(OccupancyType)` | `"primary_residence"`, `"second_home"`, `"investment"` (`property.py:50-52`) |
| Property type | `Property.property_type` (`property.py:80`) | `str_enum(PropertyType)` | `"single_family"`, `"condo"`, `"townhouse"`, `"multi_family"`, `"manufactured"`, `"other"` (`property.py:35-40`) |

- **`str_enum` stores the enum *value*, not the member name**, in a bounded `VARCHAR` + CHECK
  constraint (`enums.py` docstring; ADR-037) — so the DB holds `"fha"`, never `"FHA"`/`"Fha"`/a
  MISMO code. No case variance in storage.
- **The normalization layer is `app/mismo/import_service.py`** — explicit dicts map the raw MISMO
  category strings to the enums: `_PROGRAM = {"Conventional": …CONVENTIONAL, "FHA": …FHA}`
  (`import_service.py:71-73`), `_PURPOSE = {"Purchase": …, "Refinance": …}` (`:75-77`),
  `_OCCUPANCY = {"PrimaryResidence": …, "SecondHome": …, "Investment": …}` (`:110-113`).
  `refinance_type` is derived from MISMO's `RefinanceCashOutDeterminationType` via
  `_refinance_type_for` (`:92-107`, a "grounded starter — validate with Priya", `:79-91`).
- **The one sharp edge:** the maps are **exact-match**; an unknown/variant MISMO string maps to
  `None` (the field is left empty, the file still imports — `:63-64`, `:152`). So there is no
  fuzzy/case-insensitive normalization — a non-standard export loses the field silently rather
  than erroring. Applicability comparing the enum is clean; the risk is *absence*, not *variant
  values*.
- **Manual entry:** these columns are also editable via the API with the same enums (not raw
  strings), so a non-MISMO file still stores normalized values.

**Implication for the namespace:** program/purpose/refinance/occupancy/property_type are safe to
address as clean enum facts (`file.program`, `property.occupancy`). No normalization layer needed
in the engine — but the namespace must treat "unset/None" as a first-class state (a common case,
since the import drops unmapped codes).

---

## 2. EXTRACTION STORAGE — one JSON blob per document, NOT per-field-per-file queryable

**Verdict: document extraction output lives in a single `extractions.extracted_data` JSON column,
one current version per document. It is NOT addressable per-field-per-file by the database — you
cannot `SELECT` "all bank_statement transactions for loan file X" or "the credit_report
liabilities for file X"; you must find the documents, load each current extraction, and walk the
JSON in Python. Credit-report liabilities don't exist at all (no schema).**

- **Storage:** `Extraction.extracted_data: Mapped[dict] = mapped_column(JSON, …)`
  (`extraction.py:99`). Everything a document yields — the typed core AND the nested lists — is
  inside this one blob. Docstring: *"The data lives in a single `extracted_data` JSON column"*
  (`extraction.py:5`); *"Bank-statement transactions live inside `extracted_data` as a nested
  list"* (`extraction.py:20`).
- **Versioned, one current per document:** `version` + `is_current`, enforced by a partial unique
  index `UNIQUE(document_id) WHERE is_current` (`extraction.py:71-93`). `Document.current_extraction`
  is a Python property over the loaded `extractions` collection (`document.py:248-259`) — a
  Python filter, not a queryable column.
- **Access pattern today** (from `_verified_documents` / `_typed_fields`,
  `services/cross_source.py`): load `Document` rows for the file with `selectinload(extractions)`,
  take `current_extraction`, then read `extracted_data` dict keys in Python. Only the flat
  typed-core `{key: {value, source}}` is surfaced; the nested `transactions[]` and
  `additional_sections` catch-all are not lifted into any queryable shape.
- **So the two example queries:**
  - *"all bank_statement transactions for file X"* → find Documents where `document_type =
    'bank_statement'` and `loan_file_id = X` (that part IS a real query — `Document.loan_file_id`,
    `document.py:140`, and `document_type`), then for each load `current_extraction.extracted_data["transactions"]`
    and iterate in Python. The transactions themselves are **buried in JSON**, not rows (LP-116 §3:
    only `bank_statement` and `tax_return` even have nested structured lists).
  - *"credit_report liabilities for file X"* → **not possible at all**: `credit_report` is a Tier-2
    classify-only type with **no extraction schema** (LP-116 §1, §4) — no `extracted_data` fields
    are produced, so there is nothing to read, buried or otherwise.

**Implication for the namespace:** documented-side facts are NOT first-class queryable data. Any
rule that needs "documented income", "bank transactions", or "credit-report tradelines" must go
through a materialization step (load documents → parse the JSON blob → shape into facts) — exactly
the fact-builder role. The namespace should model these as *derived/materialized* facts with an
explicit source document, not as columns.

---

## 3. CrossSourceFacts — the right *seed*, the wrong *shape* for a general namespace

**Verdict: `CrossSourceFacts` is a good conceptual ancestor (it already is "the one fact object
per run, built once, read by pure rules"), but it is too narrow and wrong-shaped to be the fact
namespace as-is. It is a flat, comparison-oriented snapshot tailored to the current cross-source
checks — not an entity-addressable map. Build the namespace as an evolution of the *pattern*, not
a widening of the *class*.**

- **What it is:** a frozen dataclass, `app/verification/cross_source/facts.py:52-97` — ~24 flat
  fields, "every field defaults empty" (`facts.py:57-59`). Pure data, no DB/AI (deliberate,
  mirroring `FileFacts`, `facts.py:11-15`).
- **Where built:** `build_cross_source_facts(db, loan_file, context)` in
  `services/cross_source_deterministic.py:181-262` — once per run, from the assembled
  stated-vs-verified context.
- **Where consumed:** `evaluate_cross_source(facts, …)` in `verification/cross_source/engine.py:59`,
  which runs each rule's pure `check(facts, …)`.
- **Why it's the right *pattern*:** it already embodies "one immutable fact object per run that
  pure rules read" — precisely the engine contract LP-120/121 want.
- **Why it's the wrong *shape* for the namespace:**
  1. **Comparison-oriented, not entity-oriented.** Fields are pre-shaped as the *pairs the current
     checks diff* — `names`, `stated_income_monthly` vs `documented_income_monthly`,
     `stated_employers` vs `documented_employers`, `gift_amount`/`gift_letter_present`
     (`facts.py:62-97`). There is no `borrowers[]`, no `properties[]`, no `transactions[]` to
     address or iterate.
  2. **Narrow.** It carries only the ~11 facts the fact-builder populates and the ~13 Tier-2
     placeholders (LP-115 §3a) — nothing for program/purpose/occupancy, LTV/DTI, per-borrower
     identity, document presence, etc.
  3. **Flat and pre-aggregated.** `stated_income_monthly` is already a single summed Decimal
     (`cross_source_deterministic.py:226-235`); the namespace needs the income *items* addressable,
     not the sum.
  4. **Cross-source only.** It exists to feed the deterministic cross-source rules; the single-source
     threshold engine uses a *different* fact object (`verification/facts.py FileFacts`, LP-115 §3c)
     — so there are already **two** fact shapes, neither general.

**Recommendation:** design the fact namespace as a new, entity-addressable structure (borrowers,
property, loan, documents, transactions, computed values) and let `CrossSourceFacts` /`FileFacts`
become *projections* of it. Keep the winning property (immutable, built once, pure rules read it);
drop the flat comparison shape.

---

## 4. QUERYABLE ENTITIES vs BURIED

**Verdict: the STATED side is largely real, queryable rows; the DOCUMENTED side and anything
transaction-level is buried in extraction JSON. "Gift asset?" and "self-employment income?" are
answerable by querying stated rows (via raw-string type fields); "any large deposits?" is NOT —
deposits live inside the bank-statement JSON blob.**

**Queryable today (real rows you can filter/count):**

| Entity | Model / table | Scope | Notes |
|---|---|---|---|
| Borrowers | `Borrower` (`borrower.py:60`) | per-file (`loan_file_id`, `:75`) | identity: `ssn` (encrypted), `date_of_birth`, names |
| Stated income items | `StatedIncomeItem` (`stated_financials.py:44`) | **per-borrower** (`borrower_id`, `:49`) | `monthly_amount`, `income_type` (raw str), `employment_income` (bool) |
| Stated employers | `StatedEmployer` (`stated_financials.py:60`) | **per-borrower** (`borrower_id`, `:65`) | `employer_name`, `is_current` (often null) |
| Stated liabilities | `StatedLiability` (`stated_financials.py:76`) | **per-file** (`loan_file_id`, `:85`) | `holder_name`, `monthly_payment`, `unpaid_balance`, `liability_type` |
| Stated assets (incl. gifts) | `StatedAsset` (`stated_financials.py:97`) | **per-file** (`loan_file_id`, `:105`) | `asset_type`, `value`, `holder_name` |
| Property | `Property` (`property.py:55`) | per-file, **one** (`uselist=False`, `loan_file.py:232-236`) | value/price/occupancy/type |
| Documents | `Document` (`document.py`) | per-file (`loan_file_id`, `:140`) | `document_type` queryable; **no `borrower_id`** |
| Findings / Needs / Verifications | `Finding` / `NeedsItem` / `Verification` | per-file | |

**Buried (not queryable — inside `extracted_data` JSON, or no schema):**

| "Entity" | Where it lives | Why not queryable |
|---|---|---|
| Bank deposit transactions | `bank_statement` extraction `extracted_data["transactions"]` (`extraction.py:20`, LP-116 §3) | nested JSON list, not rows |
| Large deposits | derived by scanning those transactions | must parse the JSON + apply a threshold; no `unsourced_large_deposits` fact is populated (LP-115 §3a) |
| Documented income amounts | pay_stub/voe extraction blobs | JSON, not rows; not aggregated into a `documented_income_monthly` |
| Credit-report liabilities / tradelines | — | **no schema at all** (`credit_report` Tier-2, LP-116) — not even a blob |
| Tax-return schedules | `tax_return` `extracted_data` nested bundle | nested JSON (LP-116 §3) |

**The three example triggers, concretely:**
- *"Does this file have a gift asset?"* → **queryable.** `SELECT … FROM stated_assets WHERE
  loan_file_id = X AND lower(asset_type) LIKE '%gift%'` — matches how `_gift_facts` detects it
  (`cross_source_deterministic.py:271-272`, substring on `asset_type`). Caveat: `asset_type` is a
  **raw string**, so the filter is a string match, not an enum.
- *"Does it have self-employment income?"* → **queryable but string-typed.** Iterate
  `StatedIncomeItem` for the file's borrowers; `income_type` is a raw string (`stated_financials.py:54`;
  DTI reads it as free text, `dti.py:106`) and `employment_income` is a bool
  (`cross_source_deterministic.py:231`). There is **no self-employment enum/flag** — you match the
  `income_type` string, so reliability depends on the MISMO/AI value.
- *"Does it have any large deposits?"* → **NOT cleanly queryable.** Requires loading each
  bank-statement document's current extraction and scanning `transactions[]` in the JSON against a
  threshold — no row, no populated fact today.

**Implication for the namespace:** stated entities can back applicability triggers directly (with
the caveat that `asset_type`/`income_type`/`liability_type` are raw strings needing a
canonicalization map). Documented/transaction triggers need a materialization pass first.

---

## 5. COMPUTED vs STORED (LTV / DTI)

**Verdict: LTV and DTI are computed ON-DEMAND by calculator functions and are NOT persisted
anywhere. There is no stored `ltv`/`dti` column and no cache. A rule filter like "LTV > 80" must
either invoke `build_ltv_calculation` (a function call) or recompute the ratio inline from raw
inputs — it cannot read a stored value. The `*_override` tables store input OVERRIDES, never the
computed result.**

- **No stored column.** No `ltv`/`dti`/`cltv`/`hcltv` column exists on any model or migration
  (grep of `app/models` + migrations found none; `loan_file.py:86,157` mention them only in
  comments). The computed ratios exist only on in-memory Pydantic responses: `LtvCalculation.ltv`
  (`services/ltv.py:214-230`) and `DtiCalculation.{front,back}_end_pct` (`services/dti.py:306-321`),
  never written back.
- **Overrides ≠ results.** `ltv_overrides`/`dti_overrides`/`calculator_overrides` store a per-field
  `field_key` + a single `value` — an override of one **input line** (e.g. `"ltv.appraised_value"`,
  `"housing.taxes"`), not the ratio (`ltv_override.py:46-47`, `dti_override.py:53-55`,
  `calculator_override.py:46-50`). The ratio is recomputed from `(auto ?? override)` every call.
- **To get a current value you MUST call the builder**, which reads live inputs each time:
  - `build_ltv_calculation` (`services/ltv.py:177-230`): first lien from `loan_file.loan_amount or
    note_amount` (`ltv.py:94`), appraised value from `Property.valuation_amount or estimated_value`
    (`ltv.py:116`), purchase price from `Property.purchase_price` (`ltv.py:113`), then applies
    `LtvOverride` rows and calls pure `compute_ltv`.
  - `build_dti_calculation` (`services/dti.py:275-321`): income from `StatedIncomeItem.monthly_amount`
    (`dti.py:96-111`), debts from `StatedLiability.monthly_payment` (`dti.py:114-125`), housing P&I
    computed from note/rate/amortization + taxes/insurance/HOA pulled from current `Extraction`
    payloads (`dti.py:141-152`) + MI from `compute_loan_mi` (`dti.py:153`).
- **No cache.** Every write path re-invokes the builder (`ltv.py:346,374`; `dti.py:428,456`);
  there is no stored result to update or read.
- **The dormant threshold engine's own fact-builder** computes a `dti.back_end_pct` fact *inline*
  as a sample (`services/verification_engine.py:241-247`), directly summing liabilities/income — it
  does NOT call `build_dti_calculation` and produces **no `ltv.*` fact at all** (LP-115: engine
  dormant anyway).

**Implication for the namespace:** LTV/DTI (and MI/reserves/max-loan, same pattern — LP-115 §7)
must be modelled as **computed facts** the namespace resolves by calling a calculator during
fact-building, not as stored reads. Decide deliberately: compute-once-per-run into the fact object
(consistent, but pays the calc cost every run) vs lazy. There is no existing persisted value to
lean on.

---

## 6. PER-BORROWER vs PER-LOAN addressing

**Verdict: per-borrower iteration is supported for IDENTITY and INCOME (real `borrower_id` FKs),
but liabilities, assets, and the property are per-FILE (not attributable to a borrower), the
property is modelled as exactly ONE per file, transactions are not entities at all, and documents
are file-level (no `borrower_id`). So "for each borrower, their SSN/DOB/income/employer" works;
"for each borrower, their paystub / their liabilities" does NOT.**

| "For each …" | Supported? | Evidence |
|---|---|---|
| borrower → SSN / DOB / names | ✅ | `Borrower` per-file list (`loan_file.py:227`); `ssn`/`date_of_birth` columns (`borrower.py:88,94`); `borrower_position`, `is_primary` for ordering (`:108,111`) |
| borrower → income items | ✅ | `StatedIncomeItem.borrower_id` FK (`stated_financials.py:49`); `Borrower.stated_income_items` (`borrower.py:126`) |
| borrower → employers | ✅ | `StatedEmployer.borrower_id` FK (`stated_financials.py:65`) |
| borrower → liabilities | ❌ | `StatedLiability.loan_file_id` — **per-file, no `borrower_id`** (`stated_financials.py:85`) |
| borrower → assets | ❌ | `StatedAsset.loan_file_id` — **per-file** (`stated_financials.py:105`) |
| borrower → their documents (paystub, ID) | ❌ | `Document` has `loan_file_id` but **no `borrower_id`** (`document.py:140`; grep confirms none) |
| property (each) | ⚠️ one only | `LoanFile.property` is `uselist=False` (`loan_file.py:232-236`) — a single property per file; multi-property not modelled |
| transaction (each) | ❌ | transactions are JSON inside a bank-statement extraction (`extraction.py:20`), not rows/relationships |

- **Relationship graph:** `LoanFile` → `borrowers[]` (`:227`), `property` (one, `:232`),
  `documents[]` (`:238`), `stated_liabilities[]` (`:270`), `stated_assets[]` (`:274`);
  `Borrower` → `stated_income_items[]` / `stated_employers[]` (`borrower.py:126-130`). So the
  borrower sub-tree is income/employment + identity; debts/assets hang off the *file*, not the
  borrower.

**Implication for the namespace:** it can express `file.borrowers[i].{ssn, dob, income[], employers[]}`
and `file.property.*`, but must model liabilities/assets/documents as **file-level collections**
(not borrower-scoped), single-property as a scalar (revisit if multi-property is ever needed), and
transactions as a materialized sub-collection under a document. A rule that needs "this borrower's
paystub" has no borrower→document link to traverse — a real gap for per-borrower document rules.

---

## 7. STATED-SIDE PERSISTENCE GAPS (MISMO parses but the model drops)

**Verdict: three fields are parsed from MISMO but never persisted — and because the parser
*consumes* every leaf it reads, they are FULLY DROPPED, not even recoverable from the catch-all.
The borrower current address (LP-116) is confirmed; a NEW gap is the property `county`; a minor
one is borrower `full_name` (reconstructable).**

The parser's `ctx.text()` consumes each element it reads, removing it from the catch-all
(`app/mismo/parser.py:122-128`, `:362`) — so a parsed-but-unmapped field is genuinely lost, not
demoted to `MismoImport.catch_all` (`import_service.py:257`). The catch-all only holds leaves the
typed core never touched.

| Parsed field | Parsed at | Persisted? | Evidence |
|---|---|---|---|
| Borrower current address (`address_line`, `city`, `state`, `postal_code`, `address_type`) | `parser.py:218-222` | **NO** | no address column on `Borrower` (`borrower.py:81-121`); unused in `_build_borrower` (`import_service.py:333-347`); acknowledged gap (`import_service.py:27-29`). **Fully dropped.** (LP-116) |
| Property `county` | `parser.py:288` (IR `schema.py:88`) | **NO** — NEW | no `county` column on `Property` (`property.py:70-99`); never referenced in the property mapping (`import_service.py:183-200`). **Fully dropped.** |
| Borrower `full_name` | `parser.py:210` | **NO** — minor | `Borrower.full_name` is a computed property, not a column (`borrower.py:135-139`); not written in `_build_borrower`. **Dropped but reconstructable** from first+last. |

Everything else the parser reads **is** persisted (loan terms, income items, employers,
liabilities, assets, property value/price/occupancy/type, declarations) — verified field-by-field;
no other gaps. Note also that some raw strings *drive* a derived column without being stored
verbatim (e.g. `classification` → `is_primary`, `refinance_cash_out_type` → `refinance_type`,
`mortgage_type` → `loan_program`) — that's intentional normalization, not a gap.

**Implication for the namespace:** applicability cannot reference the borrower's current address
(needed for `current_address_consistency` and any residency rule) or property county (needed for
some jurisdiction/flood rules) until a column is added and the import wired — these are **model +
import gaps**, distinct from the LP-116 "extractor produces the field but the fact-builder doesn't
wire it" gaps. Closing them is a small model/migration + a one-line import map each.

---

## Cross-cutting takeaways for the fact namespace

1. **Two clean layers already exist to build on:** normalized enums (program/purpose/occupancy/
   type) and real stated-entity rows (borrowers, income, employers, liabilities, assets, property).
   These back applicability *triggers* directly.
2. **Three things need a materialization pass, not a column read:** documented-side fields
   (extraction JSON), transaction-level data (bank-statement JSON), and computed values (LTV/DTI
   via calculators). The namespace should mark these as *derived* facts with an explicit source.
3. **Raw-string type fields need a canonicalization map:** `asset_type`, `income_type`,
   `liability_type`, `document_type` are free strings — an applicability trigger keying on
   "gift"/"self-employment" is a string match today, so the namespace should own a small
   canonical-category map (a DET-FUZZY-adjacent concern, cf. LP-120).
4. **Entity addressing is uneven:** per-borrower works for identity/income/employers; liabilities/
   assets/documents are file-level; property is singular; transactions aren't entities. The
   namespace schema must reflect that shape rather than assume uniform per-borrower nesting.
5. **Known model+import gaps to close before rules can reference them:** borrower current address,
   property county (both parsed-but-dropped, §7).

**Ambiguities flagged (not guessed):** (a) whether multi-property will ever be needed —
`uselist=False` forecloses it today; (b) the exact canonical set for `income_type` self-employment
detection (raw MISMO/AI strings, unvalidated with Priya); (c) whether LTV/DTI should be
compute-once-per-run into the fact object or lazy — a deliberate cost/consistency call for LP-119/121.

---

## Appendix — evidence file map

| Area | Files |
|---|---|
| Enums (program/purpose/refinance/occupancy/type) | `app/models/loan_file.py`, `app/models/lender.py`, `app/models/property.py`, `app/models/enums.py` |
| MISMO normalization + gaps | `app/mismo/import_service.py`, `app/mismo/parser.py`, `app/mismo/schema.py` |
| Extraction storage | `app/models/extraction.py`, `app/models/document.py`, `app/services/cross_source.py` |
| Stated entities | `app/models/stated_financials.py`, `app/models/borrower.py` |
| CrossSourceFacts | `app/verification/cross_source/facts.py`, `app/services/cross_source_deterministic.py`, `app/verification/cross_source/engine.py` |
| Computed LTV/DTI | `app/services/ltv.py`, `app/services/dti.py`, `app/models/{ltv,dti,calculator}_override.py` |
