# Extraction Schema Design Standard

_v1 — 2026-07-28. Applies to all ~105 document types._

---

## Why this document exists

The first 18 extraction schemas were designed in Phase 1, **before the rules existed**, from the
heuristic _"what does a mortgage decision need from this document?"_ Fifteen of the eighteen carry a
code comment saying no sample document was available when they were built.

The consequence surfaced in LP-431. Rule **IH-1** needs the dwelling's loss-settlement basis. The AI
read it correctly on three different insurance documents — but the schema never asked for it, so the
value landed in the free-form catch-all, which is **discarded at the snapshot boundary** and reaches
no rule. The rule is dead, and nothing reported an error.

**The lesson: the AI's reading ability is not the ceiling. The field list is.**

This standard exists so the next ~100 schemas do not repeat that.

---

## 1. The envelope every schema follows

```json
{
  "document_type": "bank_statement",
  "summary": "<one sentence: what this document is and its headline value>",

  "typed_core": {
    "<field>": {"value": <typed|null>, "page": <int|null>, "snippet": "<verbatim>"}
  },

  "<repeating_list>": [ /* only where items genuinely repeat */ ],

  "additional_sections": [
    {"section": "<name>", "fields": [{"label": "...", "value": "...", "page": 1, "snippet": "..."}]}
  ],

  "field_confidence": {"<typed_core field>": 0.0-1.0},
  "confidence": 0.0-1.0,
  "reasoning": "<one short sentence>"
}
```

- `document_type` comes from **classification**, before extraction — it is not something the model returns.
- **`summary` is new.** Tier-2 documents get a summary today; Tier-1 extractions do not. A processor
  scanning a file wants _"BofA checking, Mar 2026, ending balance $34,230"_ without opening the PDF.
- The stored shape reshapes `page`/`snippet` under `source` — the parser does this. **Write schemas in
  prompt shape.**

---

## 2. What goes in `typed_core` — the six tests

A field earns a place only if it passes one of these. **Every field must have a recorded reason.**

| # | test | why |
|---|---|---|
| **1** | **A rule reads it** | The floor. Missing ⇒ the rule is dead (IH-1). |
| **2** | **It is PII** | `_PII_FIELDS` covers **typed-core only**. Anything left to the catch-all is stored **raw** — a real address and an SSN were found unmasked there. Promote PII to protect it. |
| **3** | **It identifies or attributes the document** | Whose document, which property, which period, which account. Needed to attach a document to a borrower and to distinguish two statements. |
| **4** | **A processor uses it** | Priya's review. Becomes a future rule cheaply instead of a schema change plus re-extraction. |
| **5** | **It disambiguates one of the above** | _The one most easily missed._ See §3. |
| **6** | **Nothing** | ⇒ **leave it out.** The catch-all captures it. Every field costs tokens and, if nested, ~5 sites of plumbing. |

---

## 3. The disambiguator rule

> **A field without its disambiguator is a field you can misread confidently.**

Three real homeowners policies state the dwelling's settlement basis three different ways:

| carrier | encoding |
|---|---|
| Universal | an explicit `Dwelling Replacement Cost: Y` flag — **with `Personal Property Replacement Cost: N` beside it** |
| Occidental | **only** the ISO form code `HO 00 03` — no words at all |
| (synthetic) | prose: _"Replacement cost settlement applies"_ |

An extractor searching for "replacement cost" finds it on all three — and on Universal it may read the
**personal-property** row and report the dwelling as ACV, inverting the answer.

**So the schema must carry enough context to trust the value:** the form code alongside the flag, the
coverage letter alongside the amount, the tax year alongside the wage figure.

---

## 4. Type constraints (hard)

Five coercers exist: **`str`, `Decimal`, `date`, `int`, `page`.**

There is **no** coercer for `bool`, validated `enum`, `percent`, `datetime`, or structured `address`.
Those degrade to `str` and are interpreted downstream, or a coercer is added deliberately.

**Money stays a string in `value`** (`"49460.31"`) and is coerced to `Decimal` on read.

---

## 5. Nesting — the expensive decision

### When to nest

**Only when items genuinely repeat.** Transactions, tradelines, comparables, tax schedules, properties.
**Never to express hierarchy** — `holder → accounts → savings → balance` should be flat fields.

### Which shape

Two ship today, and the choice is a **token budget decision**:

| shape | example | cost |
|---|---|---|
| **Flat row + one `source`** | `bank_statement.transactions` | light |
| **Per-field wrapped `{value, source}`** | `tax_return.schedule_c` | heavy |

**Output ceiling is 16,384 tokens (`RETRY_MAX_TOKENS`), hard.** A statement can carry 200+ transactions;
a credit report 20+ tradelines. **Use flat rows for anything with many items.**

### What nesting costs

There is **no generic mechanism** — every nested list is bespoke, ~5 sites:

1. Extractor: nested Pydantic model + `_SPEC` + `_parse_*_list` + the prompt block
2. `snapshot/model.py`: a `…Record` type + a `DocumentEntry` attribute
3. `documents_section.py`: register the doc type + a `build_*` reshaper + wire it in
4. A consumer: a derived recipe or a rule `snapshot_path`
5. If it feeds a tag: `vocabulary_extra.yaml`, `tag_production.yaml`, the spec, `rule_kinds.csv`, `activation_bars.yaml`

**Budget one nested list per document unless the rules demand more.**

### Absent ≠ empty

A missing field is `null`. A missing list is `[]`. A missing nested object is `null`.
**Never fabricated, never omitted.**

---

## 6. PII

`_PII_FIELDS` (in `documents_section.py`) maps `field_name → (PiiKind, pre_masked)`.

- `pre_masked=True` — the extractor already masked it (last-4 display)
- `pre_masked=False` — stored **raw** in `extracted_data`; the **snapshot** masks it and adds a
  per-file salted match-hash

⚠️ **The catch-all is not protected.** Any PII the model files into `additional_sections` is stored
unmasked. **Every PII element must be a named typed field registered in `_PII_FIELDS`**, or a nested
record with its own redactor (the transaction-description pattern).

---

## 7. Deriving a schema — the procedure

1. **Rule floor.** From `verification_rule_playbook.xlsx`: every rule whose `Required Documents` names
   this type → what `How the Engine Checks It` says it reads. **Mandatory.**
2. **Domain body.** From the v2 catalog's **CORE** set (median 13/doc) + published standards.
3. **Delete provenance.** The catalog's 8 `TECHNICAL` fields (`source_page_number`,
   `source_bounding_box`, `raw_field_label`, …) are already in the `TypedField` wrapper. **Never
   implement them.**
4. **Prune CONDITIONAL** to fields passing a §2 test.
5. **Flatten** `address`/`object`/`person` to `str` unless genuinely repeating.
6. **Choose the nested list(s)** and their shape (§5).
7. **Register PII** (§6).
8. **Record encoding variations and prompt hints** (§3).
9. **Priya reviews the field list** — _"what's missing, what's never filled in?"_ No PII, no file sharing.

**Target: ~20–25 typed-core fields**, every one with a recorded reason.

---

## 8. Worked example — `bank_statement`

**22 rules read this document** — the second-highest of any type.

### The rule floor (from the playbook)

| field | type | rules |
|---|---|---|
| `institution_name` | str | AS-8, AS-10 (account grouping) |
| `account_holder_names_raw` | str | **disambiguator** — see below |
| `account_owner_name` / `_2` / `_count` | str/str/int | AS-6 (ownership), ID-1 (name consistency) |
| `account_holder_address` | str | ID-4 (address consistency), OC-1 (occupancy) |
| `account_number_masked` | str | **PII (restricted)**; account grouping key |
| `account_type` | str | AS-4 (reserve eligibility), AS-3 (liquid vs not) |
| `statement_period_start` | date | AS-8 (continuity), AS-10 (enough months) |
| `statement_period_end` | date | AS-8, AS-10, recency |
| `beginning_balance` | Decimal | AS-8 — the chain's left side |
| `ending_balance` | Decimal | AS-8, AS-3 (cash to close), AS-4 (reserves) |
| **`declared_page_count`** | int | **AS-9** — _"extract the declared page count and compare to actual"_ |
| `total_deposits` | Decimal | AS-1, AS-12 — cross-check against the transaction sum |
| `total_withdrawals` | Decimal | AS-1, AS-12 |
| `nsf_fee_count` | int | **AS-7** (currently blocked — no producer) |
| `nsf_fee_total` | Decimal | AS-7 |

⚠️ **`declared_page_count` is absent from the v2 catalog's 53 fields.** AS-9 would be dead on arrival.
**This is precisely why the rule floor comes first.**

### Multi-party handling

`account_owner_names` is `person[]` in the catalog — correct in principle (a joint account has two
owners, and AS-6 must name a non-borrower co-holder). But a list costs ~5 sites of plumbing for a
1–3 element structure.

**Resolution — flat, with the raw string retained:**

```json
"account_holder_names_raw": {"value": "JORDAN A RIVERA AND ROBERT CHEN"},
"account_owner_name":       {"value": "Jordan A Rivera"},
"account_owner_name_2":     {"value": "Robert Chen"},
"account_owner_count":      {"value": 2}
```

The **raw string is the disambiguator** (§3): if the split is wrong — _"JORDAN AND ROBERT CHEN"_ may be
one person or two — the tag layer can see the original and judge. Without it, a bad split is invisible.

_Revisit as `person[]` only if a rule needs to address owners individually beyond two._

### Adopted from the catalog (domain body)

`available_balance`, `average_daily_balance`, `fees_total`, `holds_or_pledges`,
`minimum_balance_requirement` — a processor reads these, and reserve/liquidity rules may later.

### Rejected, with reasons

| field | why not |
|---|---|
| the 8 `TECHNICAL` provenance fields | already in the `TypedField` wrapper |
| `notary_block`, `signature_blocks` | a bank statement is not executed |
| `form_number`, `form_revision_date` | not a standardised form |
| `property_address`, `loan_number` | not on a bank statement |
| `expiration_date`, `effective_date` | duplicate the statement period |
| `large_deposit_candidates` | **a judgment, not a fact** — AS-1's job, from `transactions`. Tags describe; rules judge. |
| `check_images_or_check_numbers` | no consumer |

### The repeating list — one, flat

```json
"transactions": [
  {"date": "2026-04-03",
   "description": "Payroll – PPD Development",
   "amount": "2346.75",
   "transaction_type": "deposit",
   "running_balance": "34230.87",
   "source": {"page": 1, "snippet": "04/03 Payroll – PPD Development 2,346.75 34,230.87"}}
]
```

**Flat rows, one `source` each** — a 4-month statement carries 200+; per-field wrapping would risk the
16,384 ceiling. Serves AS-1, AS-2/PC-5, AS-5, AS-7, AS-12, FR-5.

### Result

**~24 typed-core fields + one nested list** — against 14 from the rules alone and 53 from the catalog.
Every field has a reason; every rejection has one too.

---

## 9. The per-document template

| section | content |
|---|---|
| **Document type** | the slug |
| **Summary line** | what the one-sentence summary should say |
| **Typed core** | field · type · **why (rule id / PII / identity / disambiguator / processor)** |
| **Repeating lists** | name · shape (flat-row \| wrapped) · **why that shape** — or _none_ |
| **PII** | which need `_PII_FIELDS`, pre-masked or raw |
| **Encoding variations** | how issuers state the same fact differently |
| **Prompt hints** | domain conventions the model must be told (ISO form codes, box numbers) |
| **Rejected** | field · why not |

The **why** column is the whole difference from the first 18. **A field with no entry there does not go in.**

---

## 10. Sequencing

Depth should follow rule count, not alphabetical order.

| tier | documents | treatment |
|---|---|---|
| **Deep** (~10) | 1003/URLA (26 rules), purchase agreement (17), bank statement (22), credit report (15), pay stub (13), title (14), appraisal (11), W-2 (8), tax return, condo questionnaire | full template + Priya review |
| **Standard** (~15) | 2–5 rules each | rule floor + catalog CORE |
| **Thin** (~75) | 1 rule each | minimal field list, written when the rule is built |

**75 of 99 document types serve exactly one rule.** The top 8 documents cover **70 of 133 rules (52%)**.
Deep research on all 105 would be badly misallocated.
