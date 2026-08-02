# Extraction schema spec — JSON format

_One `NNN-<slug>.json` per document type. The spec is the single source of truth; the Pydantic model,
`_CORE_SPEC`, prompt scaffold and `_PII_FIELDS` registration are all generated from it._

## Top level

```jsonc
{
  "document_type": "bank_statement",      // the extractor slug / registry key
  "slug": "bank-statements",              // the design-doc slug (Cowork's naming)
  "tier": 1,                              // 1 = deep (>=8 rules) · 2 = standard (2-7) · 3 = thin (0-1)
  "rules_served": ["AS-1", "AS-6"],       // every rule that reads this document
  "summary_hint": "institution, account type, period, ending balance",
  "existing_extractor": "app/ai/extraction/bank_statement.py",   // or null
  "catalog_coverage": "full",             // full | partial | none  (none = no v2 catalog entry)

  "typed_core":  [ /* Field */ ],
  "nested_lists": [ /* NestedList */ ],

  // ── review metadata: kept in the spec, NEVER emitted into the Pydantic model ──
  "rejected":            [ /* Rejection */ ],
  "encoding_variations": [ "..." ],
  "open_questions":      [ /* OpenQuestion */ ],
  "notes":               [ "..." ]
}
```

## `Field`

```jsonc
{
  "name": "declared_page_count",
  "type": "int",                    // str | Decimal | date | int   (the five coercers; `page` is wrapper-internal)
  "why": "AS-9 — compare the printed count to the actual page count",
  "rules": ["AS-9"],                // [] when the reason is PII / identity / disambiguator / processor
  "reason_class": "rule",           // rule | pii | identity | disambiguator | processor
  "rule_floor": true,               // true = a rule needs it AND the v2 catalog omits it
  "degraded_from": null,            // "bool" | "enum" | "percent" | "address" — records the type loss
  "pii": null,                      // or {"kind": "SSN"|"ACCOUNT"|..., "pre_masked": true|false}
  "exists_today": true,             // already in the shipping extractor
  "prompt_hint": "The count printed on the statement ('Page 1 of 4'), NOT the PDF page count"
}
```

**`reason_class` is the enforcement point.** Every field must carry one — it is the "why" column made
machine-checkable. A field with no defensible class does not go in.

## `NestedList`

Since **LP-437** a nested list is a **declaration** the generator turns into a `ListSpec`, not ~5 bespoke
files. Three optional helper declarations drive the LP-437 mechanism:

```jsonc
{
  "name": "transactions",
  "shape": "flat_row",              // flat_row (bare scalars + one source per row — the light shape) | per_field_wrapped
  "shape_reason": "200+ items on a 4-month statement; per-field wrapping risks the 16,384-token ceiling",
  "expected_item_count": "200+",
  "rules": ["AS-1", "AS-2", "AS-5"],
  "exists_today": true,
  "fields": [
    {"name": "amount", "type": "Decimal", "why": "AS-1 large-deposit sweep"},
    {"name": "description", "type": "str", "why": "AS-5 gift detection",
     "pii_note": "incidental PII — use `redact` below, not _PII_FIELDS"}
  ],

  // ── the three LP-437 helper declarations (all optional) ──
  "derived": [                      // a value-map producing a NEW row field
    {"field": "direction", "from": "transaction_type",
     "map": {"deposit": "credit", "withdrawal": "debit"}}
  ],
  "redact": ["description"],        // run the shared _DESC_REDACT (\d(?:[\s-]?\d){8,}) over these fields
  "stable_row_id": true             // content-derived row_id — ONLY where a rule enumerates rows as subjects
}
```

- **`derived`** — a value-map producing a new row field. ⚠️ **An UNMAPPED source value produces an ABSENT
  field, never a fabricated one** — this is the forged-deposit discipline (`_direction`'s absent-on-unknown):
  a guessed `direction` on an unlabelled row would trip a large-deposit rule on every unclassified withdrawal.
- **`redact`** — the row fields to scrub with the shared `_DESC_REDACT` (a 9+-digit run → `[redacted]`), so a
  free-text row field never carries a raw account/SSN at rest. The row-redactor path, not `_PII_FIELDS`.
- **`stable_row_id`** — assign a content-derived `row_id` per row (`assign_content_ids`), **only** where a
  rule enumerates the rows as finding subjects (like `transactions`/AS-1). A list read only in aggregate by a
  derived recipe needs no per-row id and omits this.

**`plumbing_sites` is deprecated (LP-438)** — it was ~5 per list under the bespoke path; under LP-437 the cost
is ≈ one declaration + the per-rule consumer. Drop it from new/updated list entries.

## `Rejection` / `OpenQuestion`

```jsonc
{"name": "large_deposit_candidates", "reason": "a judgment, not a fact — AS-1's job. Tags describe; rules judge"}

{"id": 1,
 "q": "Flat holder fields vs person[]?",
 "options": ["flat + raw string", "person[] nested list"],
 "recommendation": "flat until a rule needs >2 owners individually",
 "blocks_implementation": false}
```

`blocks_implementation: true` means the answer changes the **shape** of what gets built — those must be
resolved before code generation.

## Generation rules

| spec | generates |
|---|---|
| `typed_core[].name` + `.type` | the `TypedField[T]` declaration and its `_CORE_SPEC` coercer pair |
| `typed_core[].pii` | the `_PII_FIELDS` entry |
| `typed_core[].prompt_hint` | a per-field line in the prompt |
| `nested_lists[]` | a LP-437 `ListSpec` + its `_LIST_SPECS` registration snippet + the prompt's flat-row block |
| `nested_lists[].derived` / `.redact` / `.stable_row_id` | the `ListSpec`'s three helper declarations |
| a `<list>_count` field beside a matching list | the count cross-check (count ≠ rows → PARTIAL, guide §8) |
| `exists_today: false` | the additions a diff-style implementation must make |
| `rejected` / `open_questions` / `encoding_variations` | **review only — never emitted into code** |

## Invariants

1. **Every field has a `reason_class`.** No exceptions.
2. **Types are limited to the five coercers.** Anything else records `degraded_from`.
3. **PII must be typed-core or a nested field with a row redactor** — never left to the catch-all,
   which is stored unmasked.
4. **`rule_floor: true`** marks a field a rule needs that the catalog omits — each is a rule that would
   otherwise be dead on arrival.
5. **A nested list is a declaration (LP-437), not ~5 plumbing sites.** The STORAGE side is generic (a
   `ListSpec` the generator emits); the CONSUMER (a rule enumerator or a derived recipe) is still per-list,
   but that is the rule's own logic, not plumbing. Still prefer a flat field for a genuinely single value.
