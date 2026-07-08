# Fact-Namespace Structure — path reference (LP-118.6)

**Type:** read-only reference · **Source of truth:** `backend/app/verification/fact_namespace/`
**Date:** 2026-07-07 · **Schema version:** 1 (`snapshot.py:37`)

> The exact, addressable structure of the per-run fact namespace assembled by LP-118.6 — every
> entity, field, type, full path, and how ABSENT surfaces — so applicability (LP-119) and
> evaluators (LP-120) author against **real** paths. Every field name is quoted verbatim from
> `snapshot.py` with its line; the source/absent behaviour is quoted from `builder.py`. **No code
> was read into this doc that isn't cited.**

Root model: `FactNamespace` (`snapshot.py:236-256`). Built by
`assemble_fact_namespace(db, loan_file)` (`builder.py`). Persisted verbatim as
`verifications.fact_snapshot` (JSON).

---

## 0. The `Fact[T]` wrapper — how every wrapped value works

Most leaf values are wrapped in `Fact[T]` (`snapshot.py:55-84`). A `Fact` has four attributes:

| attr | type | meaning |
|---|---|---|
| `.value` | `T \| None` | the typed value (Decimal / str / date / list…), or `None` |
| `.absent` | `bool` | **True = KNOWN-MISSING** (no data source, dropped at import, or uncomputable) |
| `.source` | `FactSource \| None` | provenance / WHY (see below) |
| `.confidence` | `float \| None` | set only for AI-canonicalized values (`CANONICAL_AI`) |

`.is_present` (`snapshot.py:82-84`) ≡ `value is not None and not absent`.

**The tri-state (this is the crux for awaiting-data):**
- **present** — `value` set, `absent=False`.
- **empty** — `value is None` (scalar) or `[]` (list), `absent=False` — *the source exists but
  yielded nothing* (e.g. a file with no assets; an unset enum column).
- **ABSENT** — `absent=True` — *known to be missing*; `.source` names why. **Never** zero/empty.

**`FactSource` enum values** (`snapshot.py:40-52`) — the value strings:

| value | meaning |
|---|---|
| `enum` | a normalized enum column (program/purpose/occupancy/type) |
| `stated` | a stated-entity row (MISMO import or manual) |
| `extraction` | materialized from a document's extraction JSON |
| `computed` | a calculator output (compute-once) |
| `canonical_map` | canonicalized deterministically via the curated map |
| `canonical_ai` | canonicalized via the AI fallback (carries `.confidence`; silent-misread risk) |
| `unmapped` | canonicalization **miss** — the fallback produced no answer (`value=None`, **not** absent) |
| `absent_no_schema` | no extractor/schema produces this yet |
| `absent_not_persisted` | parsed at MISMO import but dropped (store-everything gap) |
| `absent_uncomputable` | a calculator's inputs are missing |

> **`_scalar` helper behaviour** (`builder.py:60-64`): a plain scalar fact is `Fact.present(value,
> source=…)` when the value is set, else `Fact(value=None, source=None)` — i.e. when a stated/enum
> scalar is **unset it becomes an EMPTY fact with `source=None`** (not absent, and the `stated`/`enum`
> source is dropped). Only the explicitly-`Fact.missing(...)` fields carry `absent=True`.

**Not every field is wrapped.** Plain (unwrapped) fields are noted as such in the tables — they are
`str | None`, `bool | None`, `int`, or `list[...]` directly.

---

## 1. Tree view (paths + types)

`[]` = collection. `Fact[X]` = wrapped (has value/absent/source). Everything else is a plain value.

```
FactNamespace                                    (snapshot.py:236)
├─ schema_version: int  (=1)                     :246
├─ loan_file_id: str                             :247
├─ file: FileFacts                               :248
│   ├─ file.program:            Fact[str]        :228   enum: conventional|fha
│   ├─ file.loan_purpose:       Fact[str]        :229   enum: purchase|refinance
│   ├─ file.refinance_type:     Fact[str]        :230   enum: rate_term|cash_out  (separate cash-out axis)
│   ├─ file.loan_amount:        Fact[Decimal]    :231
│   ├─ file.note_amount:        Fact[Decimal]    :232
│   └─ file.note_rate_percent:  Fact[Decimal]    :233
├─ borrowers[]: BorrowerFacts                    :249   (per-file list, ordered by position)
│   ├─ borrowers[].borrower_id:    str           :130
│   ├─ borrowers[].position:       int           :131
│   ├─ borrowers[].is_primary:     bool          :132
│   ├─ borrowers[].first_name:     str|None      :133
│   ├─ borrowers[].last_name:      str|None      :134
│   ├─ borrowers[].full_name:      str|None      :135
│   ├─ borrowers[].ssn_masked:     Fact[str]     :136   MASKED last-4 only (PII)
│   ├─ borrowers[].date_of_birth:  Fact[date]    :137
│   ├─ borrowers[].current_address: Fact[str]    :138   ⚠ ALWAYS ABSENT today (see §6)
│   ├─ borrowers[].income_items[]: IncomeItemFacts   :139  (PER-BORROWER)
│   │   ├─ …income_items[].monthly_amount:         Fact[Decimal]  :98
│   │   ├─ …income_items[].income_type_raw:        str|None       :99   (RAW)
│   │   ├─ …income_items[].income_type_canonical:  Fact[str]      :100  (CANONICAL)
│   │   └─ …income_items[].employment_income:      bool|None      :101
│   ├─ borrowers[].employers[]: EmployerFacts     :140  (PER-BORROWER)
│   │   ├─ …employers[].name:        str|None     :107
│   │   └─ …employers[].is_current:  bool|None    :108
│   └─ borrowers[].documents[]: DocumentRef       :142  ⚠ ALWAYS EMPTY today (LP-118.8; shape only)
├─ property: PropertyFacts | None                :250   (SINGLE; None if no property)
│   ├─ property.address:          Fact[str]       :148
│   ├─ property.county:           Fact[str]       :149   ⚠ ALWAYS ABSENT today (see §6)
│   ├─ property.occupancy:        Fact[str]       :150   enum: primary_residence|second_home|investment
│   ├─ property.property_type:    Fact[str]       :151   enum: single_family|condo|townhouse|multi_family|manufactured|other
│   ├─ property.estimated_value:  Fact[Decimal]   :152
│   ├─ property.purchase_price:   Fact[Decimal]   :153
│   └─ property.valuation_amount: Fact[Decimal]   :154
├─ liabilities[]: LiabilityFacts                  :251   (FILE-LEVEL list)
│   ├─ liabilities[].liability_type_raw:        str|None    :162  (RAW)
│   ├─ liabilities[].liability_type_canonical:  Fact[str]   :163  (CANONICAL)
│   ├─ liabilities[].monthly_payment:           Fact[Decimal] :164
│   ├─ liabilities[].unpaid_balance:            Fact[Decimal] :165
│   └─ liabilities[].holder_name:               str|None    :166
├─ assets[]: AssetFacts                           :252   (FILE-LEVEL list)
│   ├─ assets[].asset_type_raw:        str|None   :174  (RAW)
│   ├─ assets[].asset_type_canonical:  Fact[str]  :175  (CANONICAL)
│   ├─ assets[].is_gift:               bool       :176  (plain bool; derived — see §4)
│   ├─ assets[].value:                 Fact[Decimal] :177
│   └─ assets[].holder_name:           str|None   :178
├─ documents[]: DocumentRef                       :253   (FILE-LEVEL list)
│   ├─ documents[].document_id:            str          :117
│   ├─ documents[].document_type:          str|None     :118
│   ├─ documents[].present:                bool         :119   (a current extraction exists)
│   ├─ documents[].current_extraction_id:  str|None     :120
│   ├─ documents[].fields:                 dict[str,str] :123  (typed-core extraction values, value-only)
│   └─ documents[].borrower_id:            str|None      :124   ⚠ ALWAYS None today (LP-118.8)
├─ transactions[]: TransactionFacts               :254   (FILE-LEVEL list; materialized from bank statements)
│   ├─ transactions[].source_document_id:  str          :186
│   ├─ transactions[].date:                Fact[date]   :187
│   ├─ transactions[].amount:              Fact[Decimal] :188
│   ├─ transactions[].description:         str|None     :189
│   └─ transactions[].transaction_type:    str|None     :190
├─ computed: ComputedFacts                        :255   (SINGLE object; compute-once)
│   ├─ computed.ltv:            Fact[Decimal]     :199
│   ├─ computed.cltv:           Fact[Decimal]     :200
│   ├─ computed.hcltv:          Fact[Decimal]     :201
│   ├─ computed.front_end_dti:  Fact[Decimal]     :202
│   ├─ computed.back_end_dti:   Fact[Decimal]     :203
│   ├─ computed.mi_monthly:     Fact[Decimal]     :204   (value None + not-absent = "MI not required")
│   └─ computed.reserves_months: Fact[Decimal]    :205
└─ documented: DocumentedFacts                    :256   (SINGLE object; documented-side aggregates)
    ├─ documented.documented_employers:      Fact[list[str]]  :215
    ├─ documented.documented_income_monthly: Fact[Decimal]    :216  ⚠ ALWAYS ABSENT today (see §6)
    ├─ documented.credit_tradelines:         Fact[list[str]]  :218  ⚠ ALWAYS ABSENT (no schema)
    ├─ documented.documented_loan_amount:    Fact[Decimal]    :219  ⚠ ALWAYS ABSENT (no schema)
    └─ documented.occupancy_evidence:        Fact[str]        :220  ⚠ ALWAYS ABSENT (no schema)
```

---

## 2. Per-entity field tables

Legend: **W** = wrapped `Fact[...]`; **P** = plain value. "Absent/source" = what the builder emits.

### `FileFacts` — path prefix `file.` (`snapshot.py:223-233`, built `builder.py:103-116`)

| field | path | type | W/P | allowed values | absent/source |
|---|---|---|---|---|---|
| program | `file.program` | Fact[str] | W | `conventional`, `fha` | present `enum`; unset → empty (`value=None, source=None`) |
| loan_purpose | `file.loan_purpose` | Fact[str] | W | `purchase`, `refinance` | present `enum`; unset → empty |
| refinance_type | `file.refinance_type` | Fact[str] | W | `rate_term`, `cash_out` | present `enum`; unset → empty (null on a purchase) |
| loan_amount | `file.loan_amount` | Fact[Decimal] | W | — | present `stated`; unset → empty |
| note_amount | `file.note_amount` | Fact[Decimal] | W | — | present `stated`; unset → empty |
| note_rate_percent | `file.note_rate_percent` | Fact[Decimal] | W | — | present `stated`; unset → empty |

### `BorrowerFacts` — path prefix `borrowers[].` (`snapshot.py:127-142`, built `builder.py:119-156`)

| field | path | type | W/P | notes | absent/source |
|---|---|---|---|---|---|
| borrower_id | `borrowers[].borrower_id` | str | P | UUID string | — |
| position | `borrowers[].position` | int | P | `borrower_position` (1-based) | — |
| is_primary | `borrowers[].is_primary` | bool | P | | — |
| first_name | `borrowers[].first_name` | str\|None | P | | — |
| last_name | `borrowers[].last_name` | str\|None | P | | — |
| full_name | `borrowers[].full_name` | str\|None | P | `"first last"` or None | — |
| ssn_masked | `borrowers[].ssn_masked` | Fact[str] | W | **MASKED last-4 only** (PII) | present `stated`; unset → empty |
| date_of_birth | `borrowers[].date_of_birth` | Fact[date] | W | | present `stated`; unset → empty |
| current_address | `borrowers[].current_address` | Fact[str] | W | **⚠ always ABSENT** | `Fact.missing(absent_not_persisted)` (`builder.py:150`) |
| income_items | `borrowers[].income_items[]` | list[IncomeItemFacts] | P(list) | per-borrower | empty list if none |
| employers | `borrowers[].employers[]` | list[EmployerFacts] | P(list) | per-borrower | empty list if none |
| documents | `borrowers[].documents[]` | list[DocumentRef] | P(list) | **⚠ always `[]`** (LP-118.8) | `builder.py:153` sets `[]` |

### `IncomeItemFacts` — path prefix `borrowers[].income_items[].` (`snapshot.py:92-101`, built `builder.py:123-129`)

| field | path | type | W/P | canonical/raw | allowed values | absent/source |
|---|---|---|---|---|---|---|
| monthly_amount | `…income_items[].monthly_amount` | Fact[Decimal] | W | — | — | present `stated`; unset → empty |
| income_type_raw | `…income_items[].income_type_raw` | str\|None | P | **RAW** | free string | — |
| income_type_canonical | `…income_items[].income_type_canonical` | Fact[str] | W | **CANONICAL** | `employment`, `self_employment`, `rental`, `fixed`, `other` (§3) | map hit → `canonical_map`; AI → `canonical_ai`(+conf); miss → `value=None, source=unmapped`; raw None → `value=None, source=None` |
| employment_income | `…income_items[].employment_income` | bool\|None | P | — | — | — |

### `EmployerFacts` — path prefix `borrowers[].employers[].` (`snapshot.py:104-108`, built `builder.py:133-136`)

| field | path | type | W/P | absent/source |
|---|---|---|---|---|
| name | `…employers[].name` | str\|None | P | — |
| is_current | `…employers[].is_current` | bool\|None | P | — |

### `PropertyFacts` — path prefix `property.` (single; `snapshot.py:145-154`, built `builder.py:159-175`)

| field | path | type | W/P | allowed values | absent/source |
|---|---|---|---|---|---|
| address | `property.address` | Fact[str] | W | joined `line, city, state, postal` | present `stated`; unset → empty |
| county | `property.county` | Fact[str] | W | **⚠ always ABSENT** | `Fact.missing(absent_not_persisted)` (`builder.py:167`) |
| occupancy | `property.occupancy` | Fact[str] | W | `primary_residence`, `second_home`, `investment` | present `stated`; unset → empty |
| property_type | `property.property_type` | Fact[str] | W | `single_family`, `condo`, `townhouse`, `multi_family`, `manufactured`, `other` | present `enum`; unset → empty |
| estimated_value | `property.estimated_value` | Fact[Decimal] | W | — | present `stated`; unset → empty |
| purchase_price | `property.purchase_price` | Fact[Decimal] | W | — | present `stated`; unset → empty |
| valuation_amount | `property.valuation_amount` | Fact[Decimal] | W | — | present `stated`; unset → empty |

> `property` itself is `PropertyFacts | None` — **`None` when the file has no property row** (`snapshot.py:250`).

### `LiabilityFacts` — path prefix `liabilities[].` (FILE-LEVEL; `snapshot.py:157-166`, built `builder.py:178-188`)

| field | path | type | W/P | canonical/raw | allowed values | absent/source |
|---|---|---|---|---|---|---|
| liability_type_raw | `liabilities[].liability_type_raw` | str\|None | P | **RAW** | free string | — |
| liability_type_canonical | `liabilities[].liability_type_canonical` | Fact[str] | W | **CANONICAL** | `installment`, `revolving`, `mortgage`, `lease`, `open`, `other` (§3) | map/AI/unmapped as income_type_canonical |
| monthly_payment | `liabilities[].monthly_payment` | Fact[Decimal] | W | — | — | present `stated`; unset → empty |
| unpaid_balance | `liabilities[].unpaid_balance` | Fact[Decimal] | W | — | — | present `stated`; unset → empty |
| holder_name | `liabilities[].holder_name` | str\|None | P | — | — | — |

### `AssetFacts` — path prefix `assets[].` (FILE-LEVEL; `snapshot.py:169-178`, built `builder.py:191-204`)

| field | path | type | W/P | canonical/raw | allowed values | absent/source |
|---|---|---|---|---|---|---|
| asset_type_raw | `assets[].asset_type_raw` | str\|None | P | **RAW** | free string | — |
| asset_type_canonical | `assets[].asset_type_canonical` | Fact[str] | W | **CANONICAL** | `depository`, `retirement`, `investment`, `gift`, `life_insurance`, `other` (§3) | map/AI/unmapped |
| is_gift | `assets[].is_gift` | bool | P | derived | — | `"gift" in asset_type_raw.lower()` (`builder.py:200`) — legacy-parity, NOT the canonical value |
| value | `assets[].value` | Fact[Decimal] | W | — | — | present `stated`; unset → empty |
| holder_name | `assets[].holder_name` | str\|None | P | — | — | — |

### `DocumentRef` — path prefix `documents[].` (FILE-LEVEL; also the `borrowers[].documents[]` shape) (`snapshot.py:111-124`, built `builder.py` `_build_documents_and_transactions`)

| field | path | type | W/P | notes |
|---|---|---|---|---|
| document_id | `documents[].document_id` | str | P | UUID string |
| document_type | `documents[].document_type` | str\|None | P | e.g. `w2`, `bank_statement`, `gift_letter` |
| present | `documents[].present` | bool | P | a current extraction exists |
| current_extraction_id | `documents[].current_extraction_id` | str\|None | P | |
| fields | `documents[].fields` | dict[str,str] | P | typed-core extraction values, value-only (`{}` if none) |
| borrower_id | `documents[].borrower_id` | str\|None | P | **⚠ always None** (LP-118.8) |

### `TransactionFacts` — path prefix `transactions[].` (FILE-LEVEL; materialized from `bank_statement`) (`snapshot.py:181-190`, built `builder.py:243-254`)

| field | path | type | W/P | absent/source |
|---|---|---|---|---|
| source_document_id | `transactions[].source_document_id` | str | P | the bank-statement document id |
| date | `transactions[].date` | Fact[date] | W | present `extraction`; unparseable → empty |
| amount | `transactions[].amount` | Fact[Decimal] | W | present `extraction`; unparseable → empty |
| description | `transactions[].description` | str\|None | P | — |
| transaction_type | `transactions[].transaction_type` | str\|None | P | e.g. `deposit` |

### `ComputedFacts` — path prefix `computed.` (single; compute-once) (`snapshot.py:193-205`, built `builder.py:294-323`)

| field | path | type | W/P | source | uncomputable → |
|---|---|---|---|---|---|
| ltv | `computed.ltv` | Fact[Decimal] | W | `computed` | `Fact.missing(absent_uncomputable)` |
| cltv | `computed.cltv` | Fact[Decimal] | W | `computed` | absent_uncomputable |
| hcltv | `computed.hcltv` | Fact[Decimal] | W | `computed` | absent_uncomputable |
| front_end_dti | `computed.front_end_dti` | Fact[Decimal] | W | `computed` | absent_uncomputable |
| back_end_dti | `computed.back_end_dti` | Fact[Decimal] | W | `computed` | absent_uncomputable |
| mi_monthly | `computed.mi_monthly` | Fact[Decimal] | W | `computed` | **value None + not-absent = "MI not required"** (`builder.py:310-312`) — a real answer, NOT absent |
| reserves_months | `computed.reserves_months` | Fact[Decimal] | W | `computed` | `Fact.missing(absent_uncomputable)` (`builder.py:326-338`) |

> Source calculators (compute-once): `build_ltv_calculation` → `ltv/cltv/hcltv`;
> `build_dti_calculation` → `front_end_dti/back_end_dti`; `compute_loan_mi` → `mi_monthly`;
> `build_reserves_view` (headline parsed) → `reserves_months`.

### `DocumentedFacts` — path prefix `documented.` (single) (`snapshot.py:208-220`, built `builder.py:271-290`)

| field | path | type | W/P | absent/source |
|---|---|---|---|---|
| documented_employers | `documented.documented_employers` | Fact[list[str]] | W | present `extraction` if any; else `Fact(value=[], source=extraction)` (EMPTY, not absent) |
| documented_income_monthly | `documented.documented_income_monthly` | Fact[Decimal] | W | **⚠ always ABSENT** — `Fact.missing(absent_uncomputable)` (needs YTD→monthly, LP-120) |
| credit_tradelines | `documented.credit_tradelines` | Fact[list[str]] | W | **⚠ always ABSENT** — `Fact.missing(absent_no_schema)` (credit_report has no schema) |
| documented_loan_amount | `documented.documented_loan_amount` | Fact[Decimal] | W | **⚠ always ABSENT** — `Fact.missing(absent_no_schema)` (note/CD not extracted) |
| occupancy_evidence | `documented.occupancy_evidence` | Fact[str] | W | **⚠ always ABSENT** — `Fact.missing(absent_no_schema)` (appraisal/lease not extracted) |

---

## 3. Canonical vocabularies (`canonicalization_map.json`)

Applicability triggers should reference the **canonical** value (the `Fact[str].value` of a
`*_canonical` field), which is always one of these — or `None` with `source=unmapped` on a miss.
Raw lookup keys are lowercased/trimmed/whitespace-collapsed (`canonicalize.py`).

**`income_type_canonical` vocab** (`income_type.vocab`): `employment`, `self_employment`, `rental`,
`fixed`, `other`.
Sample raw→canonical: `base pay`/`salary`/`w2`/`bonus`/`commission`→`employment`;
`self employment`/`business`/`1099`/`k1`→`self_employment`; `rental income`→`rental`;
`social security`/`pension`/`retirement`/`disability`→`fixed`; `child support`/`alimony`→`other`.

**`asset_type_canonical` vocab** (`asset_type.vocab`): `depository`, `retirement`, `investment`,
`gift`, `life_insurance`, `other`.
Sample: `checking`/`savings`/`money market`/`cash`→`depository`; `401k`/`ira`/`retirement`→`retirement`;
`brokerage`/`stocks`/`crypto`→`investment`; `gift`/`gift of cash`/`giftofcash`/`gift funds`→`gift`;
`life insurance`→`life_insurance`.

**`liability_type_canonical` vocab** (`liability_type.vocab`): `installment`, `revolving`,
`mortgage`, `lease`, `open`, `other`.
Sample: `auto loan`/`student loan`/`personal loan`→`installment`; `credit card`/`heloc`→`revolving`;
`mortgage`/`first mortgage`→`mortgage`; `auto lease`→`lease`; `open 30-day`→`open`.

> **Miss handling:** a raw string not in the map goes to the AI-fallback seam. The default seam
> (`NoFallback`) returns nothing → the canonical `Fact` is `value=None, source=unmapped` (recorded
> in `Canonicalizer.misses`), **never silently coerced**. A wired AI seam (LP-120) returns a vocab
> value with `source=canonical_ai` + `.confidence`.

**Enum vocabularies (not from the map — from the model enums):**
- `file.program` — `LoanProgram` (`lender.py:37-38`): `conventional`, `fha`.
- `file.loan_purpose` — `LoanPurpose` (`loan_file.py:81-82`): `purchase`, `refinance`.
- `file.refinance_type` — `RefinanceType` (`loan_file.py:94-95`): `rate_term`, `cash_out`.
- `property.occupancy` — `OccupancyType` (`property.py:50-52`): `primary_residence`, `second_home`, `investment`.
- `property.property_type` — `PropertyType` (`property.py:35-40`): `single_family`, `condo`, `townhouse`, `multi_family`, `manufactured`, `other`.

---

## 4. Canonical-vs-raw & derived fields

- **Raw + canonical pairs** (author against the canonical): `income_type_raw` / `income_type_canonical`;
  `asset_type_raw` / `asset_type_canonical`; `liability_type_raw` / `liability_type_canonical`.
- **`assets[].is_gift`** is a **plain bool derived from the RAW string** (`"gift" in raw.lower()`,
  `builder.py:200`) — deliberately legacy-parity, **not** `asset_type_canonical == "gift"`. Use
  `is_gift` for gift detection; use `asset_type_canonical` for the broader category.
- **Names** (`first_name`, `last_name`, `full_name`) are plain, unwrapped.
- **`ssn_masked`** is the masked last-4 only — full SSN is never in the namespace.

---

## 5. Cardinality / addressing (reflects the real model relationships)

| collection / object | path | cardinality | scope | notes |
|---|---|---|---|---|
| borrowers | `borrowers[]` | 0..N | per-file | ordered by `position` (`borrower_position`) |
| income items | `borrowers[].income_items[]` | 0..N | **per-borrower** | nested under each borrower |
| employers | `borrowers[].employers[]` | 0..N | **per-borrower** | nested under each borrower |
| borrower documents | `borrowers[].documents[]` | 0 | per-borrower (shape) | **always empty** until LP-118.8 |
| property | `property` | 0..1 | **single** | `PropertyFacts \| None` (`uselist=False`) |
| liabilities | `liabilities[]` | 0..N | **FILE-level** | NOT attributable to a borrower |
| assets | `assets[]` | 0..N | **FILE-level** | includes gift assets (`is_gift`) |
| documents | `documents[]` | 0..N | **FILE-level** | `borrower_id` always None (LP-118.8) |
| transactions | `transactions[]` | 0..N | **FILE-level** | each carries `source_document_id`; only `bank_statement` docs contribute |
| computed | `computed` | 1 | file | single object |
| documented | `documented` | 1 | file | single object |

**Key addressing consequences for applicability:**
- Iterate income/employers **within a borrower**; iterate liabilities/assets/transactions/documents
  **at the file level** (no borrower attribution today).
- There is exactly one `property` (or none); do not assume multi-property.

---

## 6. Fields that are ABSENT / EMPTY by default TODAY (author accordingly)

These paths **exist structurally** but currently carry no data on any run — an applicability
`required_input` on them yields **awaiting-data** (or, for the empties, "present but empty"):

**Always ABSENT (`absent=True`)** — a `required_input` here ⇒ awaiting-data:

| path | source | why | unblocked by |
|---|---|---|---|
| `borrowers[].current_address` | `absent_not_persisted` | builder hardcodes `Fact.missing` (`builder.py:150`) — **even though LP-118.7 added the column**, the fact-builder is not yet wired to read it | fact-builder update (post-LP-118.7) |
| `property.county` | `absent_not_persisted` | builder hardcodes `Fact.missing` (`builder.py:167`) — same as above (LP-118.7 column not yet read) | fact-builder update |
| `documented.documented_income_monthly` | `absent_uncomputable` | needs YTD→monthly derivation | LP-120 |
| `documented.credit_tradelines` | `absent_no_schema` | credit_report has no extraction schema | blocker-schema build |
| `documented.documented_loan_amount` | `absent_no_schema` | note / closing disclosure not extracted | blocker-schema build |
| `documented.occupancy_evidence` | `absent_no_schema` | appraisal / lease not extracted | blocker-schema build |

> **⚠ Accuracy note for LP-119:** `borrowers[].current_address` and `property.county` are **stored
> in the DB** as of LP-118.7 but the **fact-builder still emits them as ABSENT** (it was scoped not
> to change the fact namespace). So today they read as awaiting-data; they become present only once
> the builder is updated to read the new columns. Treat them as absent until then.

**Conditionally ABSENT (uncomputable inputs):** `computed.ltv`, `computed.cltv`, `computed.hcltv`,
`computed.front_end_dti`, `computed.back_end_dti`, `computed.reserves_months` → `absent_uncomputable`
when the calculator lacks inputs (e.g. no appraised value → LTV absent). `computed.mi_monthly` is
**never absent**: a `None` value with `absent=False` means "MI not required".

**Always EMPTY (not absent):** `borrowers[].documents[]` = `[]` (LP-118.8); `documents[].borrower_id`
= None (LP-118.8).

**Canonical misses:** any `*_canonical` field can be `value=None, source=unmapped` when the raw
string isn't in the map and no AI seam is wired — distinct from absent (the raw exists; only the
canonical mapping is missing).

---

## Appendix — file map

| file | role |
|---|---|
| `backend/app/verification/fact_namespace/snapshot.py` | the models (field names + types) |
| `backend/app/verification/fact_namespace/builder.py` | assembly (per-field source/absent) |
| `backend/app/verification/fact_namespace/canonicalize.py` | map + fallback seam + learn |
| `backend/app/verification/fact_namespace/canonicalization_map.json` | canonical vocabularies |
| `backend/app/models/{lender,loan_file,property}.py` | enum vocabularies |
