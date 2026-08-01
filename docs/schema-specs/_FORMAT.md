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

```jsonc
{
  "name": "transactions",
  "shape": "flat_row",              // flat_row | per_field_wrapped
  "shape_reason": "200+ items on a 4-month statement; per-field wrapping risks the 16,384-token ceiling",
  "expected_item_count": "200+",
  "rules": ["AS-1", "AS-2", "AS-5"],
  "exists_today": true,
  "plumbing_sites": 5,              // ~5 per list: parser · snapshot Record · DocumentEntry attr · reshaper · consumer
  "fields": [
    {"name": "amount", "type": "Decimal", "why": "AS-1 large-deposit sweep"},
    {"name": "description", "type": "str", "why": "AS-5 gift detection",
     "pii_note": "incidental PII — needs a row redactor, not _PII_FIELDS"}
  ]
}
```

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
| `nested_lists[].shape` | flat-row vs per-field-wrapped parser + prompt JSON block |
| `exists_today: false` | the additions a diff-style implementation must make |
| `rejected` / `open_questions` / `encoding_variations` | **review only — never emitted into code** |

## Invariants

1. **Every field has a `reason_class`.** No exceptions.
2. **Types are limited to the five coercers.** Anything else records `degraded_from`.
3. **PII must be typed-core or a nested field with a row redactor** — never left to the catch-all,
   which is stored unmasked.
4. **`rule_floor: true`** marks a field a rule needs that the catalog omits — each is a rule that would
   otherwise be dead on arrival.
5. **A nested list costs ~5 plumbing sites.** Prefer flat fields; nest only for genuinely repeating items.
