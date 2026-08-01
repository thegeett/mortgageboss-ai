# Generation guide — JSON spec → working extractor

_How a `NNN-<slug>.json` spec becomes code. Read with `_FORMAT.md` (what the spec contains) and
`README.md` (why the specs exist). Mechanics verified against the codebase 2026-08-01._

---

## 0. Before generating anything — the stop conditions

**STOP and report rather than generating if any of these is true:**

| condition | why |
|---|---|
| An `open_questions` entry has **`blocks_implementation: true`** and is unanswered | it changes the *shape* of what gets built |
| A field's `type` has **no coercer** (`degraded_from` is set to `bool`/`enum`/`percent`/`time` with no `str` fallback recorded) | a new coercer in `parsing.py` is a code decision, not generation |
| A `pii.kind` **does not exist** in the `PiiKind` enum (notably **DOB** and **ADDRESS**) | a new kind needs a mask strategy — not scriptable |
| The spec has a **nested list** | ~5 bespoke files each; see §4. Generate the flat part, then treat the list as its own ticket |
| A field has **no `reason_class`** | the spec is incomplete; a field with no recorded reason does not go in |

**Everything else is mechanical.**

---

## 1. What gets generated, and what does not

**Generated from the spec:**
- the extractor module — everything except the field list is near-identical across all 18 existing types
- the `_CORE_SPEC` tuple
- the prompt scaffold (banner, two-bucket framing, JSON contract, confidence block — byte-identical today)
- the registration edits
- the test skeleton

**Never emitted into code** (review metadata only): `rejected`, `encoding_variations`, `open_questions`,
`notes`, `why`, `reason_class`, `rule_floor`, `plumbing_sites`.

**Requires a human even after generation:** the prompt's per-field descriptions, the classifier indicator,
`_MAX_TOKENS` sizing, PII registration, any nested list, and accuracy tuning against real documents.

---

## 2. The five (or six) sites

**A type already in the catalog** (a Tier-2 → Tier-1 promotion) — 5 sites:

1. `app/ai/extraction/<type>.py` (~175 lines)
2. `app/ai/prompts/extraction/<type>.txt` (~55 lines)
3. `tests/ai/test_<type>_extraction.py` (~110–135 lines)
4. `app/ai/extraction/__init__.py` — the import **and** the `EXTRACTORS` entry
5. `tests/tasks/test_document_processing.py` — pipeline test updates

**A genuinely new type not yet cataloged** — also:

6. `app/documents/catalog.py` (slug → tier/category) **and** `classification_prompt.py` (the recognition
   indicator, **CI-enforced**)

**Check the catalog first.** Most of the ~108 are already cataloged as Tier-2, so they are 5-site promotions.

---

## 3. Field generation

### Types → coercers

| spec `type` | coercer | import |
|---|---|---|
| `str` | `coerce_str` | `app.ai.extraction.parsing` |
| `Decimal` | `coerce_decimal` | same |
| `date` | `coerce_date` | same |
| `int` | `coerce_int` | same |

**No coercer exists for `bool`, `enum`, `percent`, `time`, or structured `address`.** The spec records these
in `degraded_from` and types them `str`. **Generate the `str` field; do not invent a coercer.**

### The model + spec

Each `typed_core` entry becomes one `TypedField[T]` declaration and one `_CORE_SPEC` tuple pair:

```python
field_name: TypedField[Decimal] = Field(default_factory=TypedField)
```
```python
_CORE_SPEC: CoreSpec = (
    ("field_name", coerce_decimal),
    ...
)
```

**Order matters for readability only** — keep the spec's order so the module reads like the design.

### Prompt hints

`typed_core[].prompt_hint` becomes a line in the prompt's typed-core section, against its field.
A field with `prompt_hint: null` gets its name and type only.

**The prompt scaffold is byte-identical across types** — copy it and substitute the field block, the
document name, and the `reasoning` hint.

---

## 4. Nested lists — bespoke, ~5 files each

**There is no generic mechanism.** A generator must **not** attempt these. Each is its own ticket.

| # | file | what |
|---|---|---|
| 1 | `app/ai/extraction/<type>.py` | the nested Pydantic class, its list parser (`_parse_<name>`), and the `list[X]` attribute |
| 2 | `app/verification/snapshot/model.py` | a `…Record` class + the `DocumentEntry` attribute (`tuple[XRecord, ...] \| None = None`) |
| 3 | `documents_section.py` | a `build_<name>(...)` reshaper, **registered in `build_documents_section`** |
| 4 | the consumer | a rule `snapshot_path` (e.g. `documents.entries[document_type=="bank_statement"].transactions[direction=="credit"]`) or a `derived.py` recipe |
| 5 | (if the list carries PII) | a bespoke per-row redactor — `_redact_description` is the precedent |

⚠️ **Two caveats on the `plumbing_sites: 5` estimate:**

- **It is more if the consumer is a NEW fact-tag + rule** — add `vocabulary_extra.yaml`,
  `tag_production.yaml`, the rule spec, `rule_kinds.csv`, `activation_bars.yaml` (**~5 more**).
- **Site #4 varies enormously.** `build_schedule_c` is ~15 lines; `build_transactions` drags in
  `TransactionRecord`, `_direction`, `_redact_description`, `_txn_field` and content-id assignment
  (**100+ lines**).

**The wiring is mechanical; four decisions are human:** the item shape (flat-row vs per-field-wrapped), any
derived attribute (e.g. `direction` = credit/debit), any redaction, and whether items need **stable
content_ids** for cross-run reconciliation.

**The spec already records the shape and its reason — honour it.** Flat-row was chosen wherever item counts
are high, because per-field wrapping risks the output ceiling.

---

## 5. PII

`typed_core[].pii` → a `_PII_FIELDS` entry: `field_name → (PiiKind.X, pre_masked)`.

- **`pre_masked: true`** — the extractor already masked it (last-4). The **prompt must instruct this.**
- **`pre_masked: false`** — stored raw in `extracted_data`; the **snapshot** masks it and adds a per-file
  salted match-hash.

⚠️ **Two hard limits:**

1. **`_PII_FIELDS` is typed-core only.** PII inside a nested list needs a **bespoke row redactor**
   (`_redact_description` is the precedent). **The registry cannot reach it.**
2. **`PiiKind` has no `DOB` or `ADDRESS` today.** The 1003 and credit-report specs both need them. **Adding a
   kind requires a mask strategy — STOP and treat it as its own ticket.**

**And the standing rule:** anything the model files into `additional_sections` is stored **unmasked**. That is
why every PII element must be a named typed field.

---

## 6. Diff mode — the 18 shipping extractors

When `existing_extractor` is set, **add only the `exists_today: false` fields. Never rewrite the module.**

**What a field addition affects:**

- **Stored extractions stay valid** — a missing field parses as `{value: null, source: null, confidence: null}`
- **`SNAPSHOT_VERSION`** — **do NOT bump for a backward-compatible additive change.** LP-421 established this:
  both new fields defaulted to `None`, and a committed golden fixture at v4 must still load under the reader.
  A bump caused 74 test failures. **Bump only for a breaking shape change.**
- **Expect fixture/trace updates** — legitimate where a previously-absent field now has a value; a **real
  regression** if an existing field's value moves.

---

## 7. `_MAX_TOKENS` — sized by output shape

The sizing rule, from `model_call.py`:

> _Unbounded catch-all output ("capture every X") → **8192**, or **16384** for the densest (tax_return).
> Bounded fixed-form output (W-2 boxes, a VOE, a driver's licence) → **2048–4096**._

Current values: **2048** (drivers_license) · **4096** (most flat) · **6144** (divorce_decree) ·
**8192** (pay_stub, bank_statement, investment, retirement, purchase, P&L) · **16384** (tax_return).

`tests/ai/test_extraction_budget_sizing.py` **asserts the sizing rule** — a value inconsistent with the output
shape will fail CI.

⚠️ **The credit report is the risk case.** 20+ tradelines plus inquiries plus public records can plausibly
exceed 16384 — and **`RETRY_MAX_TOKENS = 16384` is the hard ceiling.** Mitigations, in order: flat-row nesting
(already specified), then lifting `_MAX_TOKENS`.

---

## 8. Truncation — one guard exists, one gap remains

**Handled ✅:** attempt 1 at `_MAX_TOKENS`; `stop_reason == "max_tokens"` → log `extraction_truncated`, retry
at 16384. **If the retry also truncates**, the call returns `text=None` and the extractor returns
`.failed("response truncated - document too dense to extract in full")` → status **FAILED**.
**It never records `succeeded` and never keeps a partial JSON.**

⚠️ **NOT handled — model self-truncation.** If the model emits *fewer* rows without hitting the ceiling
(summarises, or stops early with valid JSON), it parses cleanly with a short list and status **SUCCEEDED**.
The guard cannot see it.

**The mitigation is in the specs — implement it.** Several carry a `*_count` field
(`tradeline_count`, `condition_count`, `comparable_count`), read from the document's own summary
**before** the list is written.

> **GENERATION RULE:** where a spec has a `*_count` field alongside a matching nested list, **emit a
> comparison**. Count ≠ row count → mark the extraction **PARTIAL**, never `succeeded`.

Also add the prompt instruction: _"Read the total count from the summary section FIRST, then list the items."_

---

## 9. Validation — what the pipeline already does

| case | behaviour |
|---|---|
| missing field | `{value: null, source: null, confidence: null}`; `non_null` not incremented |
| wrong-typed value | coercer returns `None` while a raw value was present → `coercion_lost=True`, status → **PARTIAL** |
| extra key | ignored — the parser reads only `_CORE_SPEC` keys |
| nothing read | **FAILED** |
| unparseable JSON | parser returns `None` → `.failed("could not parse extraction")` |

⚠️ **The snippet is never verified against the page.** Hallucination is not checked at this layer — the
prompt's _"NEVER guess"_ is the only defence.

---

## 10. Tests

**Per type:** `tests/ai/test_<type>_extraction.py` — the AI wrapper is **mocked**; build a `FULL_PAYLOAD`
dict, mock `complete`, assert the parse produces coerced typed fields and the right status.

> These are **shape/mechanism tests, not accuracy tests.** There are no real-document fixtures.

**Shared guards** (must keep passing): `tests/ai/test_extraction_budget_sizing.py` and
`tests/ai/test_extraction_truncation_guard.py`.

---

## 11. The honest ending for every generated extractor

Every one of the existing 18 ships with a **`STARTER PROMPT — REPLACE WITH…`** banner and a docstring noting
no real samples were available. **A generated extractor is in exactly the same position:** structurally
correct, mechanically tested, **accuracy unvalidated.**

**Say so in the module docstring.** Do not imply a generated schema is tuned.

Validation comes from Priya reviewing real extractions — which is the check that has actually been running,
and the one the demo will scale.

---

## 12. Sizing the ~108

> **Scripted generation for the flat, all-coercible, PII-declared majority · a bounded set of bespoke tickets
> for the nested / PII-heavy / new-coercer types · a Priya validation pass over all of them.**

Not 108 hand-written tickets. Not one script-and-done job either.

**Realistically:** a generator covering most of the ~98 thin types, plus **~15–20 real tickets** for the
nested and PII-heavy documents (the top ten carry 12 nested lists between them), plus prompt tuning.
