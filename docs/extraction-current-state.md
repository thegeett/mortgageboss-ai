# Extraction pipeline — current state (A2 recon, READ-ONLY)

**Branch:** `bedrock_integration` · **Date:** 2026-07-31 · **Method:** repo read + read-only
`SELECT` against `mbai-bedrock-postgres` (seeded from the main worktree in A1).

Facts with `file:line` in §1–§9. §10 is assessment, clearly separated. **NOT FOUND** marks
genuine absence, never inference.

---

## 1. Document type registry

**Where types are defined.** One Python dict — `backend/app/documents/catalog.py:55`
(`CATALOG: dict[str, tuple[Tier, DocumentCategory]]`). Not an enum, not a DB table, not seed
data. `Document.document_type` is a plain nullable `String(SHORT_STRING)`
(`backend/app/models/document.py:158-160`), deliberately not a DB enum (ADR-053, cited at
`backend/app/models/document.py:14-17`).

The catalog is also the source of the classifier's type list — the classification prompt is
built from these slugs (`backend/app/documents/catalog.py:31-34`,
`backend/app/ai/classification_prompt.py`), so the two cannot drift.

**Counts** (measured from `catalog.py`): **88 types** — **18 Tier 1**, **70 Tier 2**.
Per category: income/employment 20, assets 13, property 18, credit 10, disclosures 10,
borrower_info 13, misc 5.

**Category grouping** — `DocumentCategory`, an 8-value `StrEnum` at
`backend/app/models/document.py:46-60`: `assets`, `borrower_info`, `credit`, `disclosures`,
`income_employment`, `property`, `misc`, `custom`. This one *is* DB-enforced (VARCHAR +
CHECK). Note `custom` is defined in the enum but **no catalog entry uses it** — every
catalog row maps to one of the other seven, and the uncataloged default is `misc`
(`backend/app/documents/catalog.py:172`).

**Three-tier model — yes, implemented.** `Tier` StrEnum at
`backend/app/models/document.py:63-84` (`tier_1` / `tier_2` / `tier_3`), persisted on
`Document.tier` (`backend/app/models/document.py:167`, nullable until classified) as a
VARCHAR + CHECK enum. The **type → tier mapping is not in the DB** — it is catalog-only
(`backend/app/models/document.py:77-79`), so a retier needs no migration. Tier is written
during classification at `backend/app/tasks/document_processing.py:124` and drives routing at
`backend/app/tasks/document_processing.py:196-208`.

**The 18 Tier-1 types** (`backend/app/documents/catalog.py:59-147`):

| Category | Tier-1 slugs |
|---|---|
| income_employment | `pay_stub`, `w2`, `1099`, `tax_return`, `voe`, `profit_and_loss` |
| assets | `bank_statement`, `investment_account`, `retirement_account`, `gift_letter` |
| property | `purchase_agreement`, `homeowners_insurance`, `mortgage_statement`, `property_tax_bill`, `hoa_statement` |
| borrower_info | `drivers_license`, `divorce_decree`, `letter_of_explanation` |

All 18 have a registered extractor — `EXTRACTORS` at
`backend/app/ai/extraction/__init__.py:61-88` has exactly these 18 keys. Tier 1 is complete
(`backend/app/ai/extraction/__init__.py:85-87`).

**Catch-all / "other" type.** Two distinct mechanisms, and they are *not* the same thing:

1. **Tier-3 default for an uncataloged type** — `_DEFAULT = (Tier.TIER_3,
   DocumentCategory.MISC)` at `backend/app/documents/catalog.py:172`, returned by
   `get_tier_and_category()` for any type not in `CATALOG`
   (`backend/app/documents/catalog.py:181-183`). It never raises; every document gets a tier.
2. **The `"unknown"` slug** — the classifier's graceful fallback,
   `ClassificationResult.unknown()` at `backend/app/ai/classification.py:67-70`, returning
   `document_type="unknown"` at **zero** confidence.

How assignment works (`backend/app/tasks/document_processing.py:141-162`): the gate is
**confidence, not the slug**. `confidence < 0.5` (`_CONFIDENCE_THRESHOLD`,
`backend/app/tasks/document_processing.py:75`) → `NEEDS_REVIEW`. A **high-confidence
`"unknown"`** falls through to tier routing, where the catalog maps it to Tier 3 → the
generic analyzer. This distinction is deliberate and documented at
`backend/app/tasks/document_processing.py:142-147`.

There is no `DocumentCategory.CUSTOM` assignment path and no per-company custom type table —
**NOT FOUND**.

### The three blocker documents — exactly what exists

| Document | Status |
|---|---|
| **Credit report** | Type **exists**: `"credit_report": (Tier.TIER_2, DocumentCategory.CREDIT)` at `backend/app/documents/catalog.py:119`. Classifier indicator at `backend/app/ai/classification_prompt.py:102`. **Tier 2 → summary only, no extractor.** Not in `EXTRACTORS`. Related credit types are also all Tier 2 (`catalog.py:119-128`). |
| **Appraisal** | Type **exists**: `"appraisal": (Tier.TIER_2, DocumentCategory.PROPERTY)` at `backend/app/documents/catalog.py:103`. **Tier 2 → summary only, no extractor.** `docs/document-model.md:290-291` flags this explicitly: *"The appraisal also feeds LTV but is **Tier 2** in the catalog today — a candidate for Tier-1 promotion later, flagged for Priya."* |
| **AUS / DU findings** | **NOT FOUND as a document type.** No `aus`, `du_findings`, `desktop_underwriter`, or `loan_prospector` slug exists in `CATALOG`. The closest cataloged type is `"underwriting_approval": (Tier.TIER_2, DocumentCategory.MISC)` (`backend/app/documents/catalog.py:163`) — a different artifact. |

**AUS is a live contradiction, recorded not reconciled.** Phase 3 defines four AUS *rules* and
four AUS *fact tags* that have no document to read from:

- Rules `AU-1`…`AU-4` — `backend/app/verification/rules/rule_kinds.csv:109-112`
- Tags `aus.recommendation`, `aus.data_matches_docs`, `aus.conditions`, `aus.rerun_needed` —
  `backend/app/verification/rules/fact_tags.csv:109-112`
- Rule→tag bindings — `backend/app/verification/rules/rule_tags.csv:42-45`
- `aus.recommendation` is declared `parsed` provenance (`fact_tags.csv:109`) — i.e. it expects
  to come out of a parsed document — but nothing parses an AUS document.

The glossary describes DU output as *"the structured starting point"* (`docs/glossary.md:54`).
So the verification layer assumes AUS data; the document layer cannot produce it.

---

## 2. Extraction storage

**One table.** `__tablename__ = "extractions"` — `backend/app/models/extraction.py:94`, model
file `backend/app/models/extraction.py`. No separate transactions/fields/EAV table:
bank-statement transactions live *inside* `extracted_data` as a nested list
(`backend/app/models/extraction.py:20-21`, ADR-059).

Related storage on the document itself (not the extraction table):
`Document.generic_analysis` JSON (Tier 3) at `backend/app/models/document.py:178`,
`Document.full_text` Text at `backend/app/models/document.py:181`, `Document.summary` Text
(Tier 2) at `backend/app/models/document.py:174`.

**Full column list** — verified against the live DB
(`docker exec mbai-bedrock-postgres psql … "\d+ extractions"`):

| Column | Type | Nullable | Default | Model line |
|---|---|---|---|---|
| `id` | uuid | not null | — (PK, `pk_extractions`) | `UUIDMixin` |
| `document_id` | uuid | not null | — | `extraction.py:109-113` |
| `version` | integer | not null | — | `extraction.py:118` |
| `is_current` | boolean | not null | — (ORM-side `default=True`) | `extraction.py:119` |
| `extracted_data` | **json** | not null | — (ORM-side `default=dict`) | `extraction.py:124` |
| `extraction_status` | varchar(32) | not null | — | `extraction.py:127-129` |
| `model_used` | varchar(64) | null | — | `extraction.py:130` |
| `tokens_used` | integer | null | — | `extraction.py:131` |
| `cost_estimate` | double precision | null | — | `extraction.py:135` |
| `error_detail` | text | null | — | `extraction.py:136` |
| `confidence` | double precision | null | — | `extraction.py:145` |
| `confidence_source` | varchar(64) | null | — | `extraction.py:146-148` |
| `created_at` | timestamptz | not null | — | `TimestampMixin` |
| `updated_at` | timestamptz | not null | — | `TimestampMixin` |
| `deleted_at` | timestamptz | null | — | `SoftDeleteMixin` |

No column carries a database-side `DEFAULT`; every default (`is_current`, `extracted_data`)
is applied by SQLAlchemy at insert time.

**Indexes and constraints** (live DB):

- `pk_extractions` PRIMARY KEY btree (id)
- `ix_extractions_document_id` btree (document_id)
- `uq_extractions_document_id_current` **UNIQUE btree (document_id) WHERE is_current** — the
  partial unique index (`backend/app/models/extraction.py:100-105`)
- `ck_extractions_extractionstatus` CHECK IN (`succeeded`, `failed`, `partial`)
- `ck_extractions_confidencesource` CHECK IN (`model_self_reported`, `not_provided`)
- `fk_extractions_document_id_documents` FK → `documents(id)` **ON DELETE CASCADE**

**Typed columns, JSONB, or EAV?** **None of the three, strictly.** Extracted fields are stored
as **one `json` column** (`extracted_data`) whose *structure* is governed by per-type Pydantic
models at the application layer, not by the DB (`backend/app/models/extraction.py:5-10`,
ADR-057). It is explicitly *not* the POC's generic `ExtractedField` EAV shape
(`backend/app/models/extraction.py:7-10`).

**Note: the column is `json`, not `jsonb`.** Declared `JSON` at
`backend/app/models/extraction.py:124` (imported from `sqlalchemy` at
`backend/app/models/extraction.py:33`, the generic type — not
`sqlalchemy.dialects.postgresql.JSONB`), and the live DB confirms `json`. No GIN index exists
on it. Consequence: no indexed containment/path querying on extracted values.

**Confidence — stored at two levels, plus a provenance tag.**

- **Document level (persisted column):** `Extraction.confidence` float, nullable
  (`backend/app/models/extraction.py:145`), added by LP-201. Paired with
  `confidence_source` (`backend/app/models/extraction.py:146-148`), a CHECK-constrained enum
  `ConfidenceSource` = `model_self_reported` | `not_provided`
  (`backend/app/models/extraction.py:66-88`).
- **Per field (inside the JSON):** every typed-core field is a `TypedField` carrying a
  nullable `confidence: float | None` (`backend/app/ai/extraction/shape.py:37-53`). It rides
  inside `extracted_data`; there is no per-field confidence column.

**Where the confidence value originates — model output, honestly gated.**

- Per field: from a top-level `field_confidence` map the model returns, read at
  `backend/app/ai/extraction/parsing.py:169-171` and applied at
  `backend/app/ai/extraction/parsing.py:192`. A missing/garbage/out-of-range number becomes
  `None` — **never a fabricated default** (`backend/app/ai/extraction/parsing.py:158-163`).
  The prompt asks for it explicitly (`backend/app/ai/prompts/extraction/pay_stub.txt`,
  "PER-FIELD CONFIDENCE" block).
- Document level: the model's `"confidence"` field, clamped to `[0,1]` by
  `coerce_confidence` (`backend/app/ai/extraction/pay_stub.py:181`), then passed through
  `document_confidence_provenance()` (`backend/app/ai/extraction/parsing.py:23-34`) which
  stores a **non-positive value as `NULL` / `not_provided`** rather than as a real `0.0`
  rating. Applied in the pipeline at `backend/app/tasks/document_processing.py:324`.
- The provenance tag is **derived, never stored beside the number**
  (`ConfidenceSource.for_confidence`, `backend/app/models/extraction.py:80-88`) so the two
  cannot disagree.

Confidence is **not computed** from logprobs, field counts, or any structural signal —
`ConfidenceSource` deliberately reserves no value for that
(`backend/app/models/extraction.py:71-75`).

**Per-field source location — yes.** `SourceLocation` at
`backend/app/ai/extraction/shape.py:30-34`: `page: int | None` and `snippet: str | None` (the
verbatim text the value was read from). Carried on **both** typed-core fields
(`shape.py:52`) and catch-all fields (`shape.py:61`). Parsed at
`backend/app/ai/extraction/parsing.py:137-144`. The prompt requires it for every field
(`backend/app/ai/prompts/extraction/pay_stub.txt`, "FOR EVERY FIELD … include WHERE you read
it").

**No bounding boxes.** Page number + verbatim snippet only — **NOT FOUND** for any geometric
citation.

**Versioning — implemented, two independent schemes.**

1. **Extraction versioning** (ADR-058): `version` int + `is_current` bool
   (`backend/app/models/extraction.py:118-119`), enforced by the partial unique index
   (`extraction.py:100-105`). Supersession is represented by **demoting the old current to
   `is_current = False`, never deleting it** — history is retained for audit. The ordering
   (demote → flush → insert) is encapsulated in
   `create_extraction_version()`, `backend/app/services/extractions.py:21-83`; the demote+flush
   is at `backend/app/services/extractions.py:48-59`, and version numbers are never reused
   because `max()` spans soft-deleted rows too (`backend/app/services/extractions.py:63-66`).
2. **Document versioning** ("Model C", LP-71): `Document.version`, `is_current`,
   `version_group_id`, `supersedes_document_id` at
   `backend/app/models/document.py:202-207`. New uploads are **current + standalone with no
   replacement assumption** (multiple pay stubs are normal, not replacements —
   `backend/app/models/document.py:194-196`); an *explicit* replace forms a version group and
   keeps both rows. `supersedes_document_id` is `ondelete="SET NULL"` so the audit chain
   degrades rather than breaks (`backend/app/models/document.py:200-207`).

**Alembic revisions, in order:**

| Order | Revision | File |
|---|---|---|
| 1 | `aa3e537ea73f` | `backend/alembic/versions/20260611_0911_aa3e537ea73f_create_extractions.py:31` — creates the table |
| 2 | `a7c2e5f9d1b4` | `backend/alembic/versions/20260709_1400_a7c2e5f9d1b4_lp_201_extraction_confidence.py:23` — adds `confidence` + `confidence_source` (LP-201) |

Those are the only two revisions that touch `extractions`. Live head on both databases:
`9f0a5f88b6f8` (A1 result doc).

---

## 3. Per-document extraction schemas

**The core question — how does the system know which fields to extract from a pay stub vs a
W-2?** Three artifacts per type, bound by a naming/registry convention:

1. **A Pydantic model** defining the typed core — e.g. `PayStubExtraction`
   (`backend/app/ai/extraction/pay_stub.py:75-104`) vs `W2Extraction`
   (`backend/app/ai/extraction/w2.py:56-89`).
2. **A `_CORE_SPEC` tuple** of `(field_name, coercer)` pairs driving parsing — e.g.
   `backend/app/ai/extraction/pay_stub.py:139-151`.
3. **A prompt text file** naming the fields to the model — e.g.
   `backend/app/ai/prompts/extraction/pay_stub.txt`, loaded by path constant
   `_PROMPT_PATH` (`backend/app/ai/extraction/pay_stub.py:64`) via `load_prompt`
   (`backend/app/ai/prompt_loader.py`).

There is **no JSON Schema file and no DB-stored schema**. The contract is expressed three
times — in the Pydantic model, in the `_CORE_SPEC`, and in the prompt's literal JSON
skeleton — and kept consistent by convention, not by generation.

**The shared shape** all 18 types use — `backend/app/ai/extraction/shape.py`:

- `TypedField[T]` — `value: T | None`, `source: SourceLocation | None`,
  `confidence: float | None` (`shape.py:37-53`)
- `SourceLocation` — `page`, `snippet` (`shape.py:30-34`)
- `CatchAllField` / `CatchAllSection` — `additional_sections`, values stay **strings**,
  never coerced (`shape.py:56-68`)

### One complete Tier-1 example, verbatim

**`PayStubExtraction`** — `backend/app/ai/extraction/pay_stub.py:75-104`:

```python
class PayStubExtraction(BaseModel):
    # --- Typed core (value + source) ---------------------------------------- #
    employer_name: TypedField[str] = Field(default_factory=TypedField)
    employee_name: TypedField[str] = Field(default_factory=TypedField)
    pay_period_start: TypedField[date] = Field(default_factory=TypedField)
    pay_period_end: TypedField[date] = Field(default_factory=TypedField)
    pay_date: TypedField[date] = Field(default_factory=TypedField)
    gross_pay: TypedField[Decimal] = Field(default_factory=TypedField)  # period gross
    net_pay: TypedField[Decimal] = Field(default_factory=TypedField)
    ytd_gross: TypedField[Decimal] = Field(default_factory=TypedField)
    pay_frequency: TypedField[str] = Field(default_factory=TypedField)
    hours: TypedField[Decimal] = Field(default_factory=TypedField)
    rate: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else, by section -------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)
```

Its `_CORE_SPEC` — `backend/app/ai/extraction/pay_stub.py:139-151`:

```python
_CORE_SPEC: CoreSpec = (
    ("employer_name", coerce_str),
    ("employee_name", coerce_str),
    ("pay_period_start", coerce_date),
    ("pay_period_end", coerce_date),
    ("pay_date", coerce_date),
    ("gross_pay", coerce_decimal),
    ("net_pay", coerce_decimal),
    ("ytd_gross", coerce_decimal),
    ("pay_frequency", coerce_str),
    ("hours", coerce_decimal),
    ("rate", coerce_decimal),
)
```

The JSON contract the prompt demands — `backend/app/ai/prompts/extraction/pay_stub.txt`,
verbatim:

```
Respond with ONLY a single JSON object, no markdown fences and no prose, exactly:
{
  "typed_core": {
    "employer_name":    {"value": <string|null>, "page": <int|null>, "snippet": <string|null>},
    ...
    "rate":             {"value": <number|null>, "page": <int|null>, "snippet": <string|null>}
  },
  "additional_sections": [
    {"section": "<section name>", "fields": [
      {"label": "<field label>", "value": <string|null>, "page": <int|null>, "snippet": <string|null>}
    ]}
  ],
  "field_confidence": {"<typed_core field name>": <0.0-1.0|null>, "...": <0.0-1.0|null>},
  "confidence": <number 0.0-1.0>,
  "reasoning": "<one short sentence; do NOT quote SSNs or account numbers>"
}
```

**Worth flagging:** this prompt file opens with
`STARTER PROMPT — REPLACE WITH / MERGE INTO THE POC PAY STUB EXTRACTION PROMPT.`
(`backend/app/ai/prompts/extraction/pay_stub.txt:1`) — it is self-declared a placeholder, and
the typed-core field set is self-declared *"a V1 STARTER to refine with Priya"*
(same file, line 4; echoed at `backend/app/ai/extraction/pay_stub.py:82-83`).

**How a schema binds to its type — a dispatch dict, not naming magic.**
`EXTRACTORS: dict[str, Extractor]` at `backend/app/ai/extraction/__init__.py:61-88` maps
`document_type` slug → `async (bytes, str) -> ExtractionResult`
(`backend/app/ai/extraction/__init__.py:56`). The keys **must** match the catalog's Tier-1
slugs (`backend/app/ai/extraction/__init__.py:58-60`). Dispatch happens at
`backend/app/tasks/document_processing.py:197`
(`EXTRACTORS.get(document.document_type or "")`); a Tier-1 type with no registry entry is
handled as classified-only, not a crash
(`backend/app/tasks/document_processing.py:200-204`).

Results are unified structurally, not nominally: `ExtractionResult` is a **`Protocol`**
(`backend/app/ai/extraction/__init__.py:41-52`), so the pipeline stores any extractor's
output uniformly.

**Does the schema constrain the model? — NO.** The schema is **validation-after-the-fact
only**. There is no tool use, no `response_format`, no structured-output/JSON mode anywhere:
`complete()` passes only `model`, `messages`, `max_tokens`, and optionally `system` /
`temperature` (`backend/app/ai/client.py:203-207`). The model is asked in **prose** to emit
JSON, and the response text is parsed defensively afterwards.

**What happens when validation fails — a tolerant cascade, not a retry:**

1. **No JSON object found** → `extract_json_object()` returns `None` →
   `_parse_pay_stub_json` returns `None` (`backend/app/ai/extraction/pay_stub.py:162-163`) →
   `failed("could not parse extraction")` (`pay_stub.py:224-226`).
2. **JSON decode error / non-dict payload** → same path
   (`backend/app/ai/extraction/pay_stub.py:165-170`).
3. **Per-field coercion failure** → the field is set to `None` **but its `source` is kept**,
   and `coercion_lost` is flagged (`backend/app/ai/extraction/parsing.py:184-187`). This is a
   **partial store**: status becomes `PARTIAL` via `derive_status`
   (`backend/app/ai/extraction/parsing.py:230-236`).
4. **Pydantic `ValidationError` on the assembled model** → discard the whole result
   (`backend/app/ai/extraction/pay_stub.py:175-178`).
5. **Zero non-null typed-core fields** → `FAILED`
   (`backend/app/ai/extraction/parsing.py:232-233`).
6. **Bad catch-all sections/fields** → silently skipped, never fatal
   (`backend/app/ai/extraction/parsing.py:197-227`).

**There is no validation-failure retry.** The only retry in the extraction path is the
**truncation guard** (§4), and it fires *exclusively* on `stop_reason == "max_tokens"` —
never on a parse failure, because more budget cannot fix bad JSON
(`backend/app/ai/extraction/model_call.py:21-22`).

A `FAILED` extraction is still **persisted** (a row with empty `extracted_data` and
`error_detail`) — `backend/app/tasks/document_processing.py:325-336` runs before the
status branch at `:338`.

---

## 4. The AI client seam

**`backend/app/ai/client.py` — full public interface** (259 lines):

| Symbol | Line | Signature | Callers |
|---|---|---|---|
| `AIClientError` | `client.py:57` | `Exception` subclass | caught in ~15 modules; wraps the SDK exception as `__cause__` |
| `AICompletion` | `client.py:65-80` | frozen dataclass: `text`, `input_tokens`, `output_tokens`, `model`, `stop_reason` | returned by `complete`; consumed by `model_call.py:83` |
| `build_document_block` | `client.py:99` | `(*, content: bytes, media_type: str) -> dict[str, Any]` | `build_document_message` only (internal) |
| `build_document_message` | `client.py:126` | `(*, content: bytes, media_type: str, instruction: str \| None = None) -> dict[str, Any]` | all 18 extractors, `classification.py:39`, `summarization.py:25`, `generic_analyzer.py:34` |
| `get_anthropic_client` | `client.py:142-153` | `() -> AsyncAnthropic`, `@lru_cache(maxsize=1)` | **only** `complete()` at `client.py:199` (plus tests) |
| `complete` | `client.py:183-190` | `(*, model: str, messages: list[dict], max_tokens: int, system: str \| None = None, temperature: float \| None = None) -> AICompletion` | see below |

Private: `_normalize_media_type` (`:93`), `_is_transient` (`:156`), `_backoff_delay` (`:173`).

**`complete()` callers — 13 modules** (`from app.ai.client import … complete`):

`app/ai/classification.py:143` · `app/ai/cross_source.py:154` ·
`app/ai/extraction/model_call.py:86` (the funnel for all 18 extractors) ·
`app/ai/generic_analyzer.py:187` · `app/ai/observation.py` · `app/ai/rule_judgment.py:65` ·
`app/ai/summarization.py:61` · `app/ai/tag_correlation.py:124` ·
`app/ai/tag_production.py:159` · `app/services/needs_ai.py:345` ·
`app/services/needs_dedup.py:372` · `app/verification/finding_guidance.py:315` ·
`app/verification/tag_materialization/ai.py:106`.

Individual extractors never call `complete` directly — they import only
`build_document_message` and route the call through `run_extraction_completion`
(`backend/app/ai/extraction/model_call.py:97`).

### Is `client.py:153` the only `AsyncAnthropic` construction site? — YES

Grep of the entire backend for `AsyncAnthropic` / `from anthropic` / `import anthropic`:

```
backend/app/ai/client.py:7     (docstring)
backend/app/ai/client.py:40    from anthropic import (
backend/app/ai/client.py:43        AsyncAnthropic,
backend/app/ai/client.py:143   def get_anthropic_client() -> AsyncAnthropic:
backend/app/ai/client.py:153   return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)
backend/tests/ai/test_client.py:18   from anthropic import (   [exception classes only, for tests]
```

**`backend/app/ai/client.py:153` is the sole construction site in application code.** The
only other `anthropic` import in the repo is `backend/tests/ai/test_client.py:18`, importing
exception classes. This is the single narrowest seam for a Bedrock swap.

### Request shape

**Message assembly** — `build_document_message` (`client.py:126-139`) returns:

```python
{"role": "user", "content": [<document|image block>, {"type": "text", "text": instruction}]}
```

The text block is omitted when `instruction` is empty/None (`client.py:137-138`). In practice
**every** classification and extraction call omits it — the instruction goes in `system`
instead.

**Classification call** — `backend/app/ai/classification.py:143-148`:

```python
result = await complete(
    model=settings.anthropic_model_classification,   # claude-haiku-4-5
    system=system_prompt,                            # render_classification_prompt(), all ~88 types
    messages=[message],                              # [{"role":"user","content":[{document block}]}]
    max_tokens=512,                                  # classification.py:49
)
```

**Extraction call** — `backend/app/ai/extraction/model_call.py:86-91`:

```python
return await complete(
    model=settings.anthropic_model_extraction,       # claude-sonnet-4-5
    system=system,                                   # load_prompt("extraction/pay_stub.txt")
    messages=[message],                              # same single-user-message shape
    max_tokens=max_tokens,                           # per-type budget, e.g. 8192 for pay_stub
)
```

Both are **single-turn, single-user-message, non-streaming**
(`backend/app/ai/client.py:191`). No assistant prefill, no multi-turn history, no `stream=True`
anywhere.

### Content-block types

**Base64 blobs of the original file — no OCR, no pre-extracted text, no rasterizing.**
`build_document_block` (`client.py:99-123`) emits exactly two block types:

```python
{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": <b64>}}
{"type": "image",    "source": {"type": "base64", "media_type": "image/jpeg"|"image/png", "data": <b64>}}
```

Accepted media types: `application/pdf` (`client.py:87`) and
`{"image/jpeg", "image/png"}` (`client.py:90`); `image/jpg` folds to `image/jpeg`
(`client.py:93-96`). Anything else raises `ValueError` (`client.py:123`). The block shape is
noted as verified against **anthropic SDK 0.109.1** (`client.py:102`).

Third block type in use: `{"type": "text", ...}` (`client.py:138`) — available but unused by
the document paths. **No `tool_use`, no `tool_result`, no citations blocks.**

### Retry and backoff — with `max_retries=0` on the SDK

The SDK's own retries are **disabled** (`client.py:153`) so there is one observable retry
authority (`client.py:19-20`). The wrapper implements it:

- `max_attempts = max(1, settings.ai_max_retries)` — `client.py:200`, from
  `ai_max_retries: int = 3` (`backend/app/core/config.py:64`)
- `base_delay = settings.ai_base_retry_delay_seconds` — `client.py:201`, from
  `ai_base_retry_delay_seconds: float = 1.0` (`backend/app/core/config.py:65`)
- Loop `for attempt in range(1, max_attempts + 1)` — `client.py:210`
- Transient classification — `_is_transient` (`client.py:156-170`): `APIConnectionError`
  (includes `APITimeoutError`) always; `APIStatusError` only for **429** or **≥500**
  (`client.py:53-54`, `:169`). Every other 4xx fails fast.
- Backoff — `_backoff_delay` (`client.py:173-180`):
  `base_delay * 2**(attempt-1) * random.uniform(0.5, 1.5)` — exponential with **full jitter**.
- Sleep then continue — `client.py:230-231`; non-transient **or** last attempt → raise
  `AIClientError` wrapping the cause (`client.py:228-229`).

**Semantics note:** `ai_max_retries` is used as **total attempts**, not retries-in-addition-to
-the-first (`client.py:200`, `:210`). The default `3` means 3 calls / 2 retries.

**A second, independent retry sits above this** for extraction only — the truncation guard,
`run_extraction_completion` (`backend/app/ai/extraction/model_call.py:97-145`): if
`stop_reason == "max_tokens"` (`model_call.py:116`), retry **exactly once** at
`RETRY_MAX_TOKENS = 16384` (`model_call.py:56`, `:126-132`). Still truncated → surface
`TRUNCATED_REASON` (`model_call.py:60`, `:142-144`), deliberately never the misleading
"could not parse". Worst case for one extraction: 2 truncation attempts × 3 transient
attempts = **6 API calls**.

**Timeouts.** `ai_request_timeout_seconds: float = 60.0` exists
(`backend/app/core/config.py:69`) but is **not applied inside `client.py`** — it is applied by
*callers* via `asyncio.wait_for`, and only in Phase-3 verification modules:
`app/ai/rule_judgment.py:72`, `app/ai/tag_production.py:165`,
`app/ai/tag_correlation.py:130`, `app/ai/observation.py:104`,
`app/verification/tag_materialization/ai.py:112`. **Classification and extraction apply no
timeout at all** — they rely on the SDK's default.

### Model selection

Two settings — `backend/app/core/config.py:60-61`:

```python
anthropic_model_classification: str = "claude-haiku-4-5"
anthropic_model_extraction: str = "claude-sonnet-4-5"
```

There are **16 call sites** selecting a model, all reading one of these two — no third
setting, no hardcoded model string in a request:

| Setting | Sites |
|---|---|
| `anthropic_model_classification` | `ai/classification.py:144`, `ai/summarization.py:62`, `services/needs_dedup.py:373` |
| `anthropic_model_extraction` | `ai/extraction/model_call.py:87`, `ai/cross_source.py:155`, `ai/generic_analyzer.py:188`, `ai/observation.py:98`, `ai/rule_judgment.py:66`, `ai/tag_correlation.py:124`, `ai/tag_production.py:159`, `services/needs_ai.py:346`, `verification/finding_guidance.py:315`, `verification/tag_materialization/ai.py:106` |

Two further sites reference `anthropic_model_extraction` for **metadata, not a request**:
`app/tasks/document_processing.py:317` + `:330` (cost estimate and the persisted `model_used`)
and `app/services/verification_run.py:580` / `app/services/tag_correlation.py:468` (run
metadata / cost).

So there is effectively **one "cheap" tier and one "capable" tier**, and Tier-2 summarization
shares the classification model.

### Token usage — logged *and* stored

- **Logged** (metadata only): `ai_call_succeeded` with `input_tokens`, `output_tokens`,
  `latency_ms`, `attempt`, `stop_reason` — `client.py:241-249`. Failure path logs
  `ai_call_failed` with `error_type` + `transient` (`client.py:218-226`). Prompt/response
  **content is never logged**, stated at `client.py:12-15` and `:217`, `:240`.
- **Surfaced** on `AICompletion` (`client.py:77-78`), read from `resp.usage.input_tokens` /
  `.output_tokens` (`client.py:237-238`).
- **Stored**: `Extraction.tokens_used` (input+output summed) and `Extraction.cost_estimate` —
  `backend/app/tasks/document_processing.py:312-320`, persisted at
  `backend/app/services/extractions.py:70-71`.
- **Costed**: `estimate_cost()` against a hardcoded per-model price table
  (`backend/app/ai/cost.py:20-28`). An unknown model contributes **$0.00** plus an
  `ai_cost_unknown_model` warning (`backend/app/ai/cost.py:43-46`). The table carries a
  `TODO(pricing): VERIFY against current Anthropic pricing` (`backend/app/ai/cost.py:15`).

Classification, summarization, and generic-analysis token usage is **logged but not persisted**
— only the extraction path writes tokens/cost to a row.

### Prompt caching, Citations, tool use — none

Grep across `backend/app` for `cache_control`, `ephemeral`, `citations`, `tools=`,
`tool_choice`, `tool_use`, `response_format`: **zero hits in AI request code.** (The only
"citations" hits are Fannie/HUD *regulatory* citations in rule metadata, e.g.
`backend/app/verification/rules/conventional/__init__.py:6` — unrelated.)

- **Prompt caching: NOT FOUND.** Notable given every classification call resends the same
  ~88-type system prompt.
- **Citations: NOT FOUND.** Source attribution is done by *asking the model for a
  `page`+`snippet` in JSON* (§2), not by the API's citations feature.
- **Tool use / structured output: NOT FOUND.** JSON is requested in prose and parsed
  defensively.
- **Streaming: NOT FOUND** — `complete` is explicitly non-streaming (`client.py:191`).
- **Batch API, beta headers, extended thinking: NOT FOUND.**

---

## 5. Pipeline flow

Both tasks live in `backend/app/tasks/document_processing.py`, registered on the Celery app
(`backend/app/tasks/celery_app.py`).

| Task name | Entry point |
|---|---|
| `documents.process_document` | `backend/app/tasks/document_processing.py:445-460` → `process_document()` |
| `documents.reprocess_document` | `backend/app/tasks/document_processing.py:463-478` → `reprocess_document()` |

Both are **sync Celery tasks bridging to async** via `run_async` + `task_session`
(`backend/app/tasks/base.py`), wrapped in `retry_or_terminal`
(`backend/app/tasks/retry.py`) with `max_retries=MAX_RETRIES`.

### `documents.process_document` — ordered steps

| # | Step | file:line |
|---|---|---|
| 0 | Upload: read capped at 50 MB, validate size + declared type + **magic bytes** | `app/api/documents.py:140-141`; `app/services/documents.py:82-107` |
| 0b | Persist bytes → `{company_id}/{file_id}/{document_id}.{ext}` | `app/api/documents.py:318`; `app/storage/base.py:52-66` |
| 0c | Enqueue the task | `app/api/documents.py` (upload route) |
| 1 | Bounded-retry wrapper | `app/tasks/document_processing.py:455-460` |
| 2 | Open worker async session | `app/tasks/document_processing.py:419-422` |
| 3 | Load active document (soft-delete filtered); missing → return | `app/tasks/document_processing.py:78-86`, `:108-112` |
| 4 | **Read bytes** from storage | `app/tasks/document_processing.py:115` |
| 5 | status → `CLASSIFYING`, commit | `app/tasks/document_processing.py:118-119` |
| 6 | **Classify** (Haiku, full document) | `app/tasks/document_processing.py:120` → `app/ai/classification.py:119-166` |
| 7 | Write `document_type`, catalog `tier` + `category`, `classification_confidence`; status → `CLASSIFIED`, commit | `app/tasks/document_processing.py:121-128` |
| 8 | Activity log `DOCUMENT_PROCESSED` | `app/tasks/document_processing.py:129-139` |
| 9 | **Low-confidence gate** (`< 0.5`) → `NEEDS_REVIEW`, return | `app/tasks/document_processing.py:148-156` |
| 10 | **Route by tier** | `app/tasks/document_processing.py:162` → `:178-208` |
| 10a | Tier 1 → `EXTRACTORS.get(type)`; found → `_extract_branch`, else classified-only `COMPLETED` | `app/tasks/document_processing.py:196-204` |
| 10b | Tier 2 → summarize (Haiku, 256 tok) → `COMPLETED` | `app/tasks/document_processing.py:228-251` |
| 10c | Tier 3 → generic analyzer (Sonnet, 8192 tok) → store analysis + `full_text` + findings → `COMPLETED` | `app/tasks/document_processing.py:254-295` |
| 11 | (Tier 1) status → `EXTRACTING`, commit | `app/tasks/document_processing.py:307-308` |
| 12 | (Tier 1) run extractor → truncation-guarded model call | `app/tasks/document_processing.py:310` → `app/ai/extraction/model_call.py:97-145` |
| 13 | (Tier 1) tokens + cost estimate | `app/tasks/document_processing.py:312-320` |
| 14 | (Tier 1) confidence provenance gate | `app/tasks/document_processing.py:324` |
| 15 | (Tier 1) **persist versioned extraction** | `app/tasks/document_processing.py:325-336` → `app/services/extractions.py:21-83` |
| 16 | (Tier 1) `FAILED` **or** confidence `< 0.5` → `NEEDS_REVIEW` + `processing_error`, return | `app/tasks/document_processing.py:338-343` |
| 17 | (Tier 1) status → `COMPLETED`; record findings from extraction; commit | `app/tasks/document_processing.py:345-351` |
| 18 | Enqueue per-loan-file-serialized needs update (fire-and-forget) | `app/tasks/document_processing.py:167` → `:89-99` |
| E | Any unexpected exception → `_mark_failed` (safe message, no PII) | `app/tasks/document_processing.py:168-175`, `:362-387` |

### `documents.reprocess_document` — ordered steps

| # | Step | file:line |
|---|---|---|
| 1 | Bounded-retry wrapper | `app/tasks/document_processing.py:473-477` |
| 2 | Open session, load document; missing → return | `app/tasks/document_processing.py:425-432` |
| 3 | `EXTRACTORS.get(document.document_type)`; **none → `COMPLETED` (classified-only), return** | `app/tasks/document_processing.py:402-406` |
| 4 | Re-read bytes from storage | `app/tasks/document_processing.py:408` |
| 5 | Same `_extract_branch` as steps 11-17 above | `app/tasks/document_processing.py:409` |
| E | Unexpected exception → `_mark_failed` | `app/tasks/document_processing.py:410-416` |

**Reprocess skips classification entirely** (`app/tasks/document_processing.py:390-400`) — it
exists for the manual type-override flow (LP-44), so the *human's* corrected type is trusted.
It also does **not** enqueue the needs update.

### Classification vs extraction — two separate calls

**Two calls, always, and always in that order.** Classification is a distinct Haiku call at
`app/ai/classification.py:143` producing only `{document_type, confidence, reasoning,
category}`; extraction is a separate Sonnet call at `app/ai/extraction/model_call.py:86`.
Extraction cannot run first because the type selects the extractor
(`app/ai/classification.py:7-9`). The **same document bytes are therefore base64-encoded and
uploaded twice** for every Tier-1 document.

Tier 2 also makes 2 calls (classify + summarize); Tier 3 makes 2 (classify + analyze).

### Pre-processing — nearly none

| Candidate | State |
|---|---|
| Size check | **Yes** — 50 MB hard cap, `app/services/documents.py:46`, `:90-94`; streamed/capped read at `app/api/documents.py:102`, `:140` |
| Content-type allowlist | **Yes** — `{application/pdf, image/jpeg, image/png}`, `app/services/documents.py:48` |
| Magic-byte verification | **Yes** — `%PDF`, PNG, JPEG signatures must match the declared type, `app/services/documents.py:53-58`, `:104-109` |
| **PDF page count** | **Yes, but one type only** — `pdf_page_count()` (`app/services/pdf_utils.py:90-94`, PyMuPDF) is called by the **bank-statement extractor only**, *after* the model call, at `app/ai/extraction/bank_statement.py:255-258`, to set `page_count_present` deterministically so a model miscount cannot fabricate completeness (LP-381 / AS-9) |
| Text-layer extraction | **Exists but is NOT a pipeline step** — `extract_text_from_pdf()` at `app/services/pdf_utils.py:97-113` is explicitly *"a DEV-ONLY tool"* (`app/services/pdf_utils.py:1-8`) behind a dev-gated endpoint (`app/api/dev.py:22`, `:74`) for comparing deterministic text against the AI's reading |
| Page splitting / chunking | **NOT FOUND** |
| Rasterizing / image conversion | **NOT FOUND** |
| OCR | **NOT FOUND** — and explicitly rejected: *"no OCR, no pre-extracted text"* (`app/ai/client.py:22-24`, `app/ai/classification.py:4-6`) |
| PDF form-field (AcroForm) handling | **NOT FOUND** |
| Encryption/password detection | Only inside the dev-only tool (`app/services/pdf_utils.py:61-62`); the pipeline does not check |
| Deskew / image enhancement | **NOT FOUND** |

`pypdf>=5.1.0` is declared in `backend/pyproject.toml:21` but has **no import anywhere** in
`backend/app` or `backend/tests` — an unused dependency. Only `pymupdf`
(`backend/pyproject.toml:27`) is actually used, and only in `app/services/pdf_utils.py:19`.

### Multi-page / multi-document handling

**Multi-page: implicit only.** The whole PDF goes to the model as one base64 block
(`app/ai/client.py:113-117`); the model reads all pages natively. The system's only explicit
page awareness is (a) the per-field `page` number the model self-reports
(`app/ai/extraction/shape.py:33`) and (b) the deterministic bank-statement page count above.
There is no page-window, no chunking, and no reassembly.

**Multi-document-per-file (a merged/stapled PDF): NOT FOUND.** One uploaded file = one
`Document` row = one `document_type` = one extraction. Nothing splits a combined PDF, and
classification returns a single type. Multiple *files* are handled as independent documents
(`app/api/documents.py:146-166` stages a list) and, per
`app/models/document.py:194-196`, multiple same-type documents are explicitly **normal, not
replacements**.

### Failure recording

Status field: `Document.status` (`app/models/document.py:184-189`), indexed, non-null,
default `PENDING`. `DocumentStatus` values (`app/models/document.py:87-103`):

`pending` → `classifying` → `classified` → `extracting` → `completed`, plus terminal
`failed` and `needs_review`. **Transitions are not enforced by a state machine** — tasks set
the status directly (`app/models/document.py:93-94`).

Free-text reason: `Document.processing_error` (`app/models/document.py:191`), always a **safe**
constant, never raw PII — `"processing error"` (`app/tasks/document_processing.py:373`) or
`"extraction failed or low confidence"` (`app/tasks/document_processing.py:340`).

Extraction-level: `Extraction.extraction_status` ∈ {`succeeded`, `failed`, `partial`}
(`app/models/extraction.py:53-63`) and `Extraction.error_detail`, populated with the
extractor's reasoning only on `FAILED` (`app/tasks/document_processing.py:333`).

How failures map:

| Failure | Recorded as |
|---|---|
| Classification AI error / unparseable | `unknown` @ 0.0 conf → `NEEDS_REVIEW` (`app/ai/classification.py:149-156`; `app/tasks/document_processing.py:148-156`) |
| Low classification confidence | `NEEDS_REVIEW`, reason `low_confidence` (`app/tasks/document_processing.py:148-155`) |
| Extraction AI error / parse failure | `Extraction` row with `FAILED` + `error_detail`; document → `NEEDS_REVIEW` (`app/tasks/document_processing.py:338-343`) |
| Persistent truncation | `TRUNCATED_REASON` in `error_detail` — honest, not "could not parse" (`app/ai/extraction/model_call.py:60`, `:142-144`) |
| Coercion loss | `PARTIAL` — row stored, document still `COMPLETED` (`app/ai/extraction/parsing.py:234-235`) |
| Tier-1 type with no extractor | `COMPLETED`, reason `tier1_extractor_pending` (`app/tasks/document_processing.py:200-204`, `:211-225`) |
| Tier-2 summary failure | `COMPLETED` with null summary — forgiving (`app/tasks/document_processing.py:238-244`) |
| Tier-3 analysis failure | `COMPLETED` with null analysis (`app/tasks/document_processing.py:265-267`) |
| Storage / DB / unexpected | `FAILED` + `"processing error"` (`app/tasks/document_processing.py:168-175`, `:362-387`) |
| Infra retry exhaustion | `FAILED` via `_mark_document_failed` (`app/tasks/document_processing.py:435-442`) |

Every handled path reaches a terminal status; nothing is left stuck in `CLASSIFYING` /
`EXTRACTING` (`app/tasks/document_processing.py:24-25`). `_mark_failed` has a
rollback-and-retry-once fallback for a poisoned session
(`app/tasks/document_processing.py:379-387`).

---

## 6. Loan-file scoping

**The FK chain — extractions are scoped transitively, not directly.**

```
companies.id
   ↑ company_id (loan_files.company_id)
loan_files.id
   ↑ loan_file_id  FK ondelete=CASCADE     app/models/document.py:140-144
documents.id
   ↑ document_id   FK ondelete=CASCADE     app/models/extraction.py:109-113
extractions
```

Live DB confirms: `fk_extractions_document_id_documents FOREIGN KEY (document_id) REFERENCES
documents(id) ON DELETE CASCADE`.

**`Extraction` has no `loan_file_id` and no `company_id`** — deliberate (ADR-052), stated at
`app/models/extraction.py:23-25`: *"an extraction is an **owned child** … and has no
`company_id` — it is company-scoped transitively through `document -> loan_file`."* Same for
`Document` (`app/models/document.py:24-26`).

**DB constraints preventing cross-loan-file association?** The FK guarantees an extraction
belongs to exactly one document, and that document to exactly one loan file — so
cross-loan-file association is **structurally impossible** for an extraction. But that is the
*only* database-level protection: there is **no CHECK, no trigger, and no composite FK**
enforcing tenant consistency, and **no row-level security**.

**Row-level security: NOT FOUND.** Grep for `ROW LEVEL SECURITY` / `CREATE POLICY` / `rls`
across `backend/**/*.py` and `backend/alembic/versions/*` returns nothing. Tenant isolation is
**application-level only** — every route resolves the document via the caller's
`current_user.company_id`, e.g. `app/api/documents.py:204`, `:217`, `:245`, `:296`, `:362`,
`:389`, `:406`, and uploads stamp `company_id` at `app/api/documents.py:154`, `:319`. The
storage path is likewise tenant-prefixed (`app/storage/base.py:14`).

Soft-delete filtering is **explicit, not global** (`app/models/helpers.py:22-31`) — callers
must opt in per query with `only_active()`.

### Do extraction queries always filter by `loan_file_id`? — No, and by design

There are **three** query paths that read `Extraction`:

| # | Path | Filters | Assessment |
|---|---|---|---|
| 1 | `app/verification/snapshot/documents_section.py:534-547` | `Document.loan_file_id == loan_file.id` **and** `Document.is_current` **and** `only_active(Document)`, with `selectinload(Document.extractions.and_(Extraction.is_current))` | Fully scoped |
| 2 | `app/services/dti.py:189-208` | joins `Document`, filters `Document.loan_file_id`, `Document.document_type`, `Extraction.is_current`, `only_active(Document)`; `ORDER BY Document.created_at DESC LIMIT 1` | Fully scoped |
| 3 | `app/services/document_borrower_links.py:34-43` | **`Extraction.document_id == <id>` and `Extraction.is_current` only** — no `loan_file_id`, no `only_active` | See below |

**Path 3 is the one that does not filter by `loan_file_id`.** It is safe *in context* — it is
keyed on a single `document_id` the caller already resolved and authorized
(`app/services/document_borrower_links.py:81`), and the FK guarantees that document belongs to
exactly one loan file, so no cross-file data can be returned. It is worth naming because it is
the pattern that would break if a future caller passed an unvalidated id: the scoping lives
entirely in the caller, not in the query.

Two further notes on path 3: it also omits `only_active(Extraction, …)`, so a **soft-deleted
extraction would still be read**; and unlike paths 1 and 2, it does not filter
`Document.is_current`.

Also note **path 1 filters `Document.is_current` but paths 2 and 3 do not** — the DTI reader
(path 2) will happily read a *historical* document's current extraction if it is the newest by
`created_at`.

---

## 7. Downstream consumption

**Consumers of extraction results** (`extracted_data` / `current_extraction`):

| # | Consumer | file:line | Reads via |
|---|---|---|---|
| 1 | **Stage 1 snapshot builder** | `app/verification/snapshot/documents_section.py:556-557` | Direct query + ORM relationship |
| 2 | DTI calculator | `app/services/dti.py:239`, `:283` | Direct query (`_current_extracted_data`) |
| 3 | Document↔borrower name matching | `app/services/document_borrower_links.py:81` | Direct query (`_current_extracted_data`) |
| 4 | Findings recorder (divorce decree → obligations) | `app/services/document_findings.py:89-100`, `:103-119` | In-memory Pydantic object, pre-persistence |
| 5 | Document detail API | `app/services/documents.py:278-283` → `ExtractionPublic` (`app/schemas/document.py:119-127`), route `app/api/documents.py:198-201` | ORM property `Document.current_extraction` |
| 6 | Derived tag recipes (read the snapshot, not the table) | `app/verification/tag_materialization/derived.py:455-478` | Via the snapshot |

There is **no repository or service abstraction** over extractions for reading — V1 has no
generic repository by decision (`app/models/helpers.py:3-5`, ADR-040). Every consumer writes
its own query. The only shared service is for **writing**
(`app/services/extractions.py:21`).

### How the Stage 1 snapshot builder reads them

**A direct SQLAlchemy query, not a service.** `app/verification/snapshot/documents_section.py`:

- Query at `:530-547`: `select(Document)` filtered by `loan_file_id` + `is_current` +
  `only_active`, ordered `document_type, created_at, id`, with
  `.options(selectinload(Document.extractions.and_(Extraction.is_current.is_(True))))` — a
  deliberate narrowing so historical versions and their JSON are not over-fetched
  (`:539-541`).
- Read at `:556-557`:
  ```python
  extraction = document.current_extraction
  extracted = extraction.extracted_data if extraction and extraction.extracted_data else {}
  ```
  using the ORM property `Document.current_extraction`
  (`app/models/document.py:247-259`), which scans the loaded collection for `is_current`.
- Reshape at `:558`: `build_document_fields(extracted, document.document_type,
  loan_file_id=...)` (defined `:176`).

**The expected shape** — the interface the snapshot assumes of `extracted_data`:

- A dict whose typed-core entries are `{"value": ..., "source": {...}, "confidence": ...}`;
  only JSON **scalars** are surfaced, nested structures are skipped
  (`app/verification/snapshot/documents_section.py:167-173`, `_scalar`).
- A `"transactions"` list, only for `bank_statement` — `_TRANSACTION_DOC_TYPES`
  (`:86`), `_TRANSACTIONS_KEY` (`:87`).
- `"schedule_c"` / `"schedule_e"` nested keys, only for `tax_return` — `_SCHEDULE_DOC_TYPES`
  (`:90-93`).
- `"additional_sections"` — the catch-all, `_CATCH_ALL_KEY` (`:144`).
- Output: `dict[str, SnapshotField]` with `FieldSource.EXTRACTED` (`:83`), plus
  `DocumentEntry` / `TransactionRecord` / `ScheduleCRecord` / `ScheduleERecord`
  (`app/verification/snapshot/model.py`), each stamped with a stable content-derived id
  (`assign_content_ids`, `:567-576`).

Note the **document-type coupling is by literal slug** in frozensets at `:86` and `:90`, i.e.
a second registry of type knowledge outside `catalog.py` and `EXTRACTORS`.

### PII masking (Architecture v2 §3B: display last-4 + salted `match_hash`) — IMPLEMENTED

Located in `backend/app/verification/snapshot/pii.py` (LP-203, ADR-240).

- **Masked display**: `mask(value, kind)` at `pii.py:89`; `PiiKind` at `pii.py:74-78` —
  `SSN` → `***-**-1234`, `ACCOUNT` → `****3312`. A validator **rejects an unmasked display**
  using the `_MASK_PREFIXES` guard (`pii.py:70-71`, `pii.py:174-178`).
- **Salted match hash**: `match_hash()` at `pii.py:137`. Construction, documented at
  `pii.py:10-11`:
  `match_hash = f"{V}:" + HMAC-SHA256(key=K, msg=f"{kind}:{loan_file_id}:{value}")`
  with `K = derive_key(b"snapshot-pii-match-hash-v1")` (`pii.py:62-63`, `pii.py:132`), keyed
  off the application Fernet `encryption_key` via `app/core/encryption.py`.
- **The salt is per loan file** — `loan_file_id` is in the HMAC message, so the same SSN in
  two files hashes differently (`pii.py:19-26`). Canonicalized, and an empty id is **rejected**
  (`pii.py:116-128`).
- **Kind-bound** so an SSN and an account sharing a digit string do not collide
  (`pii.py:15-18`).
- **Non-matchable below `_MIN_MATCH_LEN = 4`** normalized chars → `None`, never a real hash,
  so two absent values can never "match" (`pii.py:65-67`, `pii.py:27-30`).
- **Versioned** — output carries `v1:` so a construction bump is detectable (`pii.py:39-43`,
  `pii.py:60-61`).
- `PiiField` states: `from_raw` (`pii.py:193`), `pre_masked` (`pii.py:211`), `missing`
  (`pii.py:244`); `is_matchable` (`pii.py:254`), `matches` (`pii.py:263`).

**Which extracted fields route through it** —
`app/verification/snapshot/documents_section.py:156-164` (`_PII_FIELDS`):

| Field | Kind | Pre-masked by extractor? |
|---|---|---|
| `account_number_masked` | ACCOUNT | yes |
| `id_number_masked` | ACCOUNT | yes |
| `taxpayer_ssn_masked` | SSN | yes |
| `employee_ssn` (W-2) | SSN | **no — stored RAW** |
| `recipient_tin` (1099) | SSN | **no — stored RAW** |
| `employer_ein` (W-2) | ACCOUNT | no |
| `payer_tin` (1099) | ACCOUNT | no |

**Important boundary:** masking happens **at snapshot build time, not at extraction time**.
`employee_ssn` and `recipient_tin` are extracted and persisted **raw** in
`extractions.extracted_data` (see `app/ai/extraction/w2.py:76` — `# SENSITIVE`, and
`documents_section.py:154-155` — *"stored RAW ('SSN as written')"*). The masking guarantee
covers the *snapshot*; the extraction table holds the raw value. This is a stated design point
(the values are needed for cross-source matching), not an oversight, but it is the fact that
matters for anything reading `extractions` directly.

The list is explicit rather than pattern-matched so a dollar figure like
`social_security_wages` is never caught (`documents_section.py:150-151`), and a test guards
against drift (`documents_section.py:151-152`, `backend/tests/verification/snapshot/test_documents_section.py`).

Separately, transaction descriptions are scrubbed of 9+-digit identifiers before surfacing —
`_DESC_REDACT` at `documents_section.py:140-141` (ADR-248).

---

## 8. Storage backend

**The interface** — `StorageBackend(ABC)` at `backend/app/storage/base.py:69-109`. Four
abstract methods:

```python
async def save(self, *, company_id: UUID, file_id: UUID, document_id: UUID,
               filename: str, content: bytes) -> str          # base.py:77-92
async def read(self, storage_path: str) -> bytes              # base.py:94-96
async def delete(self, storage_path: str) -> None             # base.py:98-100
async def get_url(self, storage_path: str) -> str | None      # base.py:102-109
```

An ABC, not a `Protocol`. Module-level helpers: `build_storage_path()` (`base.py:52-66`),
`_sanitize_extension()` (`base.py:37-49`), `SAFE_DEFAULT_EXT = "bin"` (`base.py:24`),
`ALLOWED_EXTENSIONS` (`base.py:30`), `StorageError` (`base.py:33-34`).

**`LocalStorageBackend`** — `backend/app/storage/local.py:22-87`. Implements all four:

| Method | Line | Notes |
|---|---|---|
| `__init__(self, root: str \| Path)` | `local.py:25-29` | resolves root once, `mkdir(parents=True, exist_ok=True)` |
| `_resolve_within_root(self, storage_path: str) -> Path` | `local.py:31-44` | traversal defense, runs **before** any I/O |
| `save(...) -> str` | `local.py:46-63` | `asyncio.to_thread` |
| `read(self, storage_path) -> bytes` | `local.py:65-73` | raises `StorageError` if not a file |
| `delete(self, storage_path) -> None` | `local.py:75-82` | idempotent (`unlink(missing_ok=True)`) |
| `get_url(self, storage_path) -> str \| None` | `local.py:84-87` | always `None` — local files have no direct URL |

All blocking I/O is wrapped in `asyncio.to_thread` (`local.py:62`, `:73`, `:82`).

**Every call site of the storage interface:**

| Site | file:line | Op |
|---|---|---|
| Pipeline — read bytes for classify/extract | `app/tasks/document_processing.py:115` | `read` |
| Pipeline — reprocess re-read | `app/tasks/document_processing.py:408` | `read` |
| Upload (bulk) | `app/api/documents.py:149` | factory (`get_storage_backend()`) |
| Upload (single) | `app/api/documents.py:318` | `save` |
| Download endpoint | `app/api/documents.py:393` | factory, then read/serve |
| Dev text-layer endpoint | `app/api/dev.py:74` | `read` |
| MISMO raw-file storage | `app/mismo/import_service.py:241` | `save` |
| Dev seed script | `app/scripts/seed_dev_data.py:389` | `save` |

**`delete()` is implemented but has no application call site** — grep finds no
`.delete(` on a storage backend outside `local.py` and tests. Consistent with soft-delete
everywhere: bytes are never removed.

**What is stored — original uploads only.** Every `save()` call passes the uploaded bytes
verbatim (`app/api/documents.py:318`, `app/mismo/import_service.py:241`,
`app/scripts/seed_dev_data.py:389`). **No derived artifacts** — no rendered page images, no
extracted text files, no thumbnails, no normalized PDFs. Derived output lives in Postgres
instead: `extractions.extracted_data`, `documents.full_text`, `documents.generic_analysis`,
`documents.summary`.

**Path construction — `loan_file_id` IS in the path.** `build_storage_path()`
(`backend/app/storage/base.py:52-66`) returns:

```
{company_id}/{file_id}/{document_id}.{ext}
```

where `file_id` is the loan file id. Every component is a **server-controlled UUID**; only the
extension derives from the (sanitized) user filename (`base.py:59-63`, `:65-66`). The
extension is lowercased, stripped to alphanumerics, and allowlisted to
`{pdf, jpg, jpeg, png, tif, tiff, heic, bin}` with `bin` as the fallback — so it can never
carry a path separator or `..` (`base.py:37-49`). The tenant prefix is deliberate, *"leaves
room for future per-tenant storage controls"* (`base.py:16-17`).

### The `"s3"` branch — a commented-out stub

`backend/app/storage/__init__.py:26-39`:

```python
@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.storage_local_path)
    # Future (Phase 7):
    #     if settings.storage_backend == "s3":
    #         return S3StorageBackend(...)
    raise ValueError(f"Unknown storage backend: {settings.storage_backend!r}")
```

**Confirmed state: the `"s3"` branch is commented out (`__init__.py:36-38`).** Setting
`STORAGE_BACKEND=s3` today raises `ValueError` at first use — a clear failure, not a silent
one. Note the config type already permits it: `storage_backend: Literal["local", "s3"]` at
`backend/app/core/config.py:113`, so Pydantic accepts `"s3"` at startup and the app fails
only when storage is first touched.

**What would have to exist for it to work:**

1. An `S3StorageBackend(StorageBackend)` class (no such file — `backend/app/storage/` contains
   only `__init__.py`, `base.py`, `local.py`) implementing all four abstract methods.
2. Uncomment `__init__.py:36-38` and pass real construction args.
3. An S3 client dependency — **`boto3`/`aioboto3` is NOT in `backend/pyproject.toml`**.
4. Settings for bucket/region/credentials — **NOT FOUND** in `backend/app/core/config.py`;
   only `storage_backend` and `storage_local_path` (`config.py:113-114`) exist.
5. A real `get_url()` returning a short-lived presigned URL — the interface already reserves
   this (`base.py:102-109`, `local.py:86`).
6. **The compose storage mount would become unnecessary** — the host API and containerised
   worker currently share bytes only through `./backend/storage:/app/storage`
   (`docker-compose.yml`, the SHARED STORAGE comment). Object storage is named there as *"the
   robust long-term answer"*.

---

## 9. Tests

**Test files covering extraction, classification, and the AI client** (all under
`backend/tests/`):

| Area | Files |
|---|---|
| **AI client** | `ai/test_client.py`, `ai/test_cost.py` |
| **Classification** | `ai/test_classification.py`, `ai/test_classification_prompt.py` |
| **Per-type extractors (18)** | `ai/test_pay_stub_extraction.py`, `test_w2_extraction.py`, `test_bank_statement_extraction.py`, `test_form_1099_extraction.py`, `test_voe_extraction.py`, `test_profit_and_loss_extraction.py`, `test_letter_of_explanation_extraction.py`, `test_investment_account_extraction.py`, `test_retirement_account_extraction.py`, `test_gift_letter_extraction.py`, `test_purchase_agreement_extraction.py`, `test_homeowners_insurance_extraction.py`, `test_mortgage_statement_extraction.py`, `test_property_tax_bill_extraction.py`, `test_hoa_statement_extraction.py`, `test_drivers_license_extraction.py`, `test_divorce_decree_extraction.py`, `test_tax_return_extraction.py` |
| **Cross-cutting extraction** | `ai/test_extraction_truncation_guard.py`, `ai/test_extraction_budget_sizing.py`, `ai/test_field_confidence.py`, `ai/test_page_counts_lp381.py`, `ai/test_prompt_loader.py` |
| **Other AI paths** | `ai/test_generic_analyzer.py`, `ai/test_summarization.py`, `ai/test_cross_source.py`, `ai/test_tag_production.py`, `ai/test_tag_correlation.py` |
| **Pipeline** | `tasks/test_document_processing.py`, `integration/test_document_flow.py` |
| **Storage** | `storage/test_local_storage.py`, `storage/test_factory.py` |
| **Model / service** | `models/test_extraction.py`, `models/test_document.py`, `services/test_extractions.py`, `services/test_extraction_confidence.py`, `services/test_documents.py`, `services/test_document_borrower_links.py`, `services/test_document_findings.py` |
| **Catalog** | `documents/test_catalog.py` |
| **Snapshot consumption** | `verification/snapshot/test_documents_section.py` |
| **API** | `api/test_documents_endpoints.py`, `api/test_document_versioning_endpoints.py` |
| **PDF utils** | `services/test_pdf_utils.py` |

**AI calls are mocked — always. No test makes a network call and none needs a key**
(`backend/tests/ai/test_client.py:1-8`). Two distinct patterns:

**(a) Replace the SDK client** — used to test the wrapper's own policy.
`backend/tests/ai/test_client.py:70-73`:

```python
def _install_fake_client(monkeypatch, create: AsyncMock) -> AsyncMock:
    """Replace the singleton client so ``complete`` uses our AsyncMock ``create``."""
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    monkeypatch.setattr(client_module, "get_anthropic_client", lambda: fake)
    return create
```

with a hand-built response stand-in (`test_client.py:46-53`):

```python
return SimpleNamespace(
    content=[SimpleNamespace(type="text", text=text)],
    usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
)
```

and real SDK exception classes constructed over `httpx.Response` objects
(`test_client.py:56-65`) so transient/non-transient classification is exercised against the
genuine hierarchy. Backoff sleep is patched out and recorded
(`test_client.py:76-86`).

**(b) Replace `complete` itself** — used by every extractor test.
`backend/tests/ai/test_pay_stub_extraction.py:74-86`:

```python
mock = AsyncMock(return_value=SimpleNamespace(
    text=text, input_tokens=200, output_tokens=80, model="m", stop_reason="end_turn"))
monkeypatch.setattr(model_call, "complete", mock)
```

Note it patches `model_call.complete` — the shared funnel — not each extractor.

**Fixtures with real or de-identified documents — essentially none.**

- `backend/tests/fixtures/` contains **only** `mismo/` (MISMO XML). There are **no PDF or
  image document fixtures** anywhere under `backend/tests/`.
- Extractor tests feed **JSON strings** representing the model's *response*, not documents —
  e.g. `FULL_PAYLOAD` / `FULL_JSON` at `backend/tests/ai/test_pay_stub_extraction.py:70-71`.
  The document input is arbitrary bytes; the model is mocked.
- Tests needing a real PDF **synthesize one at runtime with PyMuPDF**:
  `backend/tests/ai/test_page_counts_lp381.py:15`, `backend/tests/services/test_pdf_utils.py:9`,
  `backend/tests/api/test_dev_endpoints.py:14`.
- The 4562 PDFs under `backend/storage/` are **dev-database uploads**, not test fixtures (and
  gitignored — `.gitignore`, `/backend/storage/`).

**Consequence: no test exercises a real document end-to-end.** Every test proves the
*plumbing* (parsing, coercion, retry, status transitions), never extraction *accuracy*.

**Golden-file / eval harness — YES, but for Phase-3 verification, not extraction accuracy.**
`backend/app/verification/eval/` (16 modules):

- `harness.py:1-15` — *"the two-level scoring engine (LP-317 Phase 1) — runs the real
  pipeline, scores vs labels"*; scores at **TAG level** (`is_money_in`, `apparent_category`,
  `has_identified_source`, `source_strength`) and **FINDING level** (AS-1 outcome per
  subject). Runs with either keyless stub reasoners (deterministic CI) or the live model
  (calibration).
- `calibration.py:1-14` — abstention metrics: **unknown rate** and **accuracy when
  concrete**, explicitly to catch fabrication.
- Supporting: `cases.py`, `stubs.py`, `lf6t3n_fixture.py`, `worksheet.py`,
  `db_worksheet.py`, `live_calibration.py`, `income_scenario_scoring.py`, `dormant_probe.py`,
  `fire_path_scenarios.py`, `owner_match_scenarios.py`.

**A golden/eval harness for extraction field accuracy — NOT FOUND.** The existing harness
starts from a snapshot (built or frozen) and scores tags and findings. Nothing scores
"did the extractor read `gross_pay` correctly off this pay stub". The fixture
`lf6t3n_fixture.py` supplies *invented* snapshot data (`lf6t3n_fixture.py:554-555`), not
documents.

---

## 10. Gaps and risks — assessment

> Everything below is my judgment, not a repo fact. §1–§9 are the facts.

### What would have to change for extraction to run through Bedrock

The seam is unusually clean. Concretely:

1. **`backend/app/ai/client.py:153`** — the sole `AsyncAnthropic(...)` construction. Swap to
   `AsyncAnthropicBedrock(aws_region=..., aws_access_key=...)`. This is the whole
   client change; nothing else in `app/` touches the SDK.
2. **Model identifiers, `backend/app/core/config.py:60-61`.** Bedrock uses inference-profile
   ARNs / ids (`us.anthropic.claude-*-v1:0`), not bare aliases like `claude-haiku-4-5`. Both
   settings feed straight into `complete(model=...)`, so the values change but no code does.
3. **`backend/app/ai/cost.py:20-28`** — `PRICING` is keyed on the *exact* model string. New
   Bedrock ids miss every key, so `estimate_cost` silently returns **$0.00** with only a
   warning log (`cost.py:43-46`). Every `Extraction.cost_estimate` would quietly become 0
   while looking healthy. This is the most likely silent regression in the whole swap.
4. **New settings + validation** — region, credential mode (env / profile / IRSA), optional
   inference-profile id. `anthropic_api_key` is currently `Field(description=...)` with **no
   default** (`config.py:49`) so it is a **required** setting; the app refuses to start without
   it, and `get_anthropic_client` also hard-fails on a falsy key (`client.py:151-152`). Both
   need rethinking, or Bedrock deployments must carry a dummy key.
5. **`Extraction.model_used` is `varchar(64)`** (`app/models/extraction.py:130`, live DB
   confirms). A Bedrock **inference-profile ARN is longer than 64 characters** —
   `arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-...` — so
   `app/tasks/document_processing.py:330` would raise a `StringDataRightTruncation` on insert.
   **This needs a migration.** It is the one change that is not a config edit.
6. **Retry classification, `client.py:156-170`** — `_is_transient` keys on
   `APIStatusError.status_code`. Bedrock surfaces throttling as `ThrottlingException` and
   capacity errors as `ModelNotReadyException` / `ServiceUnavailableException`. The SDK maps
   these onto its own status-error hierarchy, but the mapping must be verified — if a
   Bedrock throttle arrives as anything other than 429/5xx, it is treated as
   **non-retryable and fails fast** (`client.py:170`). Worth an explicit test.
7. **Document-block support.** The base64 `document` block for PDFs (`client.py:113-117`) must
   be confirmed on the target Bedrock model/region. If PDF blocks are unsupported there, the
   entire "native full-document reading, no OCR" premise
   (`client.py:22-24`) collapses and a rasterize-to-images pre-processing step would be
   needed — which does not exist today (§5).
8. **Test doubles** — `backend/tests/ai/test_client.py:18` imports the exception classes
   directly. If the swap changes which exceptions arrive, these tests pass while production
   misclassifies retries.
9. **Nothing else.** No prompt changes, no schema changes, no pipeline changes. The 18
   extractors, the catalog, the parsing layer, and every consumer are provider-agnostic.

### Tightly coupled to the Anthropic SDK's specific response shape

Concentrated in `complete()`, `backend/app/ai/client.py:234-239` — four assumptions:

- `resp.content` is an iterable of blocks each with `.type` and `.text`
  (`client.py:234-236`)
- `resp.usage.input_tokens` / `resp.usage.output_tokens` exist (`client.py:237-238`)
- `resp.stop_reason` is a string, and specifically `"max_tokens"` for truncation
  (`client.py:239`; the literal is compared at `app/ai/extraction/model_call.py:116` and
  `:135`)
- request kwargs `model` / `messages` / `max_tokens` / `system` / `temperature`
  (`client.py:203-207`)

Plus the exception hierarchy at `client.py:40-44` / `:166-169`.

Everything downstream consumes `AICompletion` (`client.py:65-80`), a plain frozen dataclass —
**no SDK object escapes the module** (`client.py:72-73`). That is the single design decision
that makes this swap tractable.

### Would break under a different provider

- **The `"max_tokens"` string literal** (`model_call.py:116`, `:135`). OpenAI says
  `"length"`, Gemini `"MAX_TOKENS"`. A provider using a different token silently disables the
  truncation guard — and the failure mode is exactly the one LP-102 was written to fix: a
  cut-off response misreported as *"could not parse extraction"* → empty `NEEDS_REVIEW`. The
  guard would fail *silently and invisibly*.
- **The base64 `document`/`image` block shape** (`client.py:113-122`) — Anthropic-specific.
- **`system` as a top-level parameter** (`client.py:205`) — most other providers use a system
  *message*.
- **Prose-requested JSON with no structured-output enforcement** (§3). This is provider-
  independent in mechanism but strongly provider-dependent in *reliability*: the entire
  extraction contract rests on the model's instruction-following. A weaker model raises the
  parse-failure rate with no schema-level backstop.
- **The cost table** (`cost.py:20-28`) is Anthropic-priced and Anthropic-keyed.

### Surprising, inconsistent, or apparently unfinished

Ranked by what I would want to know before designing against this:

1. **AUS/DU has rules and tags but no document type** (§1). Four rules (`AU-1`…`AU-4`) and
   four tags — one declared `parsed` provenance — reference AUS data that no document type,
   classifier slug, or extractor can produce. This is the clearest contradiction between the
   verification layer and the document layer, and it makes AUS a from-scratch build, not a
   promotion.
2. **All three blocker documents are unextractable today** — and for two different reasons.
   Credit report and appraisal exist as Tier-2 types, so they get a 1-2 sentence summary and
   nothing more; AUS does not exist at all. Promoting credit report / appraisal is the
   established "write an extractor + register it" path; AUS needs a catalog entry, a
   classifier indicator, a prompt, a schema, and an extractor.
3. **`extracted_data` is `json`, not `jsonb`, with no GIN index** (§2). Every consumer
   therefore loads whole documents and filters in Python — visible at
   `app/services/dti.py:189-208` (join + `ORDER BY created_at DESC LIMIT 1` to find one
   field). At 28 loan files this is invisible; it is a real ceiling later, and converting
   `json` → `jsonb` is a rewriting migration.
4. **The pay-stub prompt declares itself a placeholder** — `STARTER PROMPT — REPLACE WITH /
   MERGE INTO THE POC PAY STUB EXTRACTION PROMPT` (`prompts/extraction/pay_stub.txt:1`) — and
   the typed-core field sets are self-described *"V1 STARTER — refine with Priya"*
   (`pay_stub.py:82-83`, `w2.py:62-63`). Extraction quality is measured against prompts
   nobody has claimed are final.
5. **No extraction-accuracy evaluation exists** (§9). The eval harness scores Phase-3 tags and
   findings from snapshots; nothing scores whether a field was read correctly off a document.
   Combined with (4) and with zero document fixtures, there is **no baseline to regress
   against** — which means a Bedrock swap cannot be proven non-regressive on accuracy, only
   on plumbing. I would build a small labeled-document harness *before* the swap, not after.
6. **The document is uploaded to the model twice per Tier-1 file** (§5) — once for
   classification, once for extraction, both as full base64. With no prompt caching (§4), a
   large scanned PDF is paid for twice on input tokens. Prompt caching on the ~88-type
   classification system prompt is the other obvious unclaimed saving.
7. **Classification and extraction have no request timeout** (§4). `ai_request_timeout_seconds`
   exists and is applied in five Phase-3 modules but in **neither document path**. A hung
   extraction call blocks a Celery worker slot indefinitely, subject only to the SDK default.
8. **Raw SSNs and TINs are persisted in `extracted_data`** (§7). The §3B masking guarantee is
   real but applies at *snapshot build*, not at rest. Anything new that reads `extractions`
   directly — a Bedrock re-extraction comparison tool, an export, a debug endpoint — bypasses
   masking by default. The A1 seed script copying this database between worktrees is
   precisely such a path.
9. **Three type registries that must agree** — `CATALOG` (`catalog.py:55`), `EXTRACTORS`
   (`ai/extraction/__init__.py:61`), and the classifier's indicator map
   (`classification_prompt.py`) — plus two more slug frozensets in the snapshot builder
   (`documents_section.py:86`, `:90`). Tests guard some pairs (`documents/test_catalog.py`,
   `ai/test_classification_prompt.py`); the snapshot frozensets look unguarded.
10. **`ai_max_retries` means total attempts, not retries** (`client.py:200`). The name will
    mislead someone tuning it. Nested with the truncation guard, worst case is 6 calls for
    one extraction — worth knowing before setting Bedrock throttling budgets.
11. **`DocumentCategory.CUSTOM` is defined but unused** (`document.py:60`) — no catalog entry
    and no assignment path. Either dead or an unfinished feature.
12. **`pypdf>=5.1.0` is declared but never imported** (`pyproject.toml:21`) — dead dependency.
13. **`StorageBackend.delete()` is implemented but never called** (§8) — consistent with
    soft-delete everywhere, but it means bytes accumulate permanently.
14. **`storage_backend: Literal["local", "s3"]`** (`config.py:114`) accepts `"s3"` at startup
    but the branch is commented out (`storage/__init__.py:36-38`), so the failure is deferred
    to first use rather than caught at boot. Minor, but it defeats the
    "required vars missing → app refuses to start" convention in `CLAUDE.md`.
15. **`_current_extracted_data` in `document_borrower_links.py:34-43`** (§6) filters on
    `document_id` only — no `loan_file_id`, no `only_active`, no `Document.is_current`. Safe
    as called today; the weakest of the three read paths if reused.

### Contradictions with Verification Architecture v2 / the V1 Build Plan

Per the ticket's Stop-and-report rule, recorded not reconciled:

1. **AUS/DU** — item 1 above. Phase-3 rule and tag catalogs assume an AUS document the
   document layer cannot produce.
2. **Appraisal tiering** — the build-plan expectation that the appraisal feeds LTV vs. the
   catalog's Tier-2 placement. The repo already flags this against itself:
   `docs/document-model.md:290-291`.
3. **§3B PII masking** — no contradiction. Implemented as specified (masked display + salted,
   keyed, versioned `match_hash`), with the at-rest boundary noted in §7.

`docs/verification-architecture-v2.docx` is a **binary `.docx` and was not read**; the §3B
assessment above is made against the implementing code (`app/verification/snapshot/pii.py`) and
its ADR references (LP-203 / ADR-240), not against the document text.

---

## Recon summary — what could not be answered from the repo

Written as **NOT FOUND** in place and listed here per the ticket's Stop-and-report rule:

| § | Item | Status |
|---|---|---|
| 1 | AUS / DU findings document type | **NOT FOUND** — no slug, no indicator, no extractor (rules/tags exist — contradiction, §10) |
| 1 | Per-company custom document types; any `DocumentCategory.CUSTOM` assignment path | **NOT FOUND** |
| 2 | Bounding boxes / geometric citations | **NOT FOUND** — page + verbatim snippet only |
| 3 | JSON Schema files or DB-stored extraction schemas | **NOT FOUND** — Pydantic + `_CORE_SPEC` + prompt text only |
| 4 | Prompt caching, Citations, tool use, structured output, streaming, batch API | **NOT FOUND** — none used |
| 5 | Page splitting, rasterizing, OCR, form-field handling, multi-document-per-PDF | **NOT FOUND** |
| 6 | Row-level security / DB-enforced tenant scoping on extractions | **NOT FOUND** — application-level only |
| 8 | `S3StorageBackend`, boto3 dependency, S3 settings | **NOT FOUND** — branch commented out at `storage/__init__.py:36-38` |
| 9 | Real or de-identified document fixtures | **NOT FOUND** — only MISMO XML; PDFs synthesized at runtime |
| 9 | Golden-file / eval harness for **extraction accuracy** | **NOT FOUND** — the LP-317 harness scores Phase-3 tags and findings, not extracted fields |
| 10 | `docs/verification-architecture-v2.docx` | Binary `.docx`, **not read** — §3B assessed against code, not the document |

Everything else in §1–§9 is answered with a `file:line` reference or live-DB output.
