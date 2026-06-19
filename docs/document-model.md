# The three-tier document model

How mortgageboss-ai scales document handling from a handful of types to ~80-100
without giving every type full extraction. Introduced in **LP-58** (Phase 2);
see **ADR-167**.

## The problem

Phase 1 handled three document types — `pay_stub`, `w2`, `bank_statement` — each
with full structured extraction (a typed schema + a prompt + tests) via the
`EXTRACTORS` registry. A real loan file draws on **~80-100** document types.
Building a first-class extractor for every one is infeasible and wasteful: most
types are low-value or rarely seen, yet the long-tail still has to be *recognized
and handled*, not dropped.

## The three tiers (level of investment)

A document **type** is assigned a **tier** — how much extraction effort it earns:

| Tier | Name | Handling | Count | Built in |
| ---- | ---- | -------- | ----- | -------- |
| **Tier 1** | First-class | Full structured extraction (typed core + catch-all) via the `EXTRACTORS` registry | ~18 | the 3 existing + LP-60..64 |
| **Tier 2** | Recognized | Classified + categorized + a short AI summary; **no** deep extraction | ~60-80 | LP-65 (summary) |
| **Tier 3** | Long-tail | Didn't match a known type → a generic analyzer produces a structured summary | open-ended | LP-66 (analyzer) |

Tier 1 is reserved for documents whose **exact data drives Phase 3 verification**
(income, assets, the note). Tier 2 still recognizes and files a document for the
processor. Tier 3 catches everything else so nothing is silently lost.

The 3 Phase-1 types **are** Tier 1, and the `EXTRACTORS` registry **is** the
Tier-1 mechanism — Phase 2 generalizes around it rather than replacing it.

## The catalog — the single source of truth

`backend/app/documents/catalog.py` maps each known `document_type` to its
`(tier, category)`:

```python
CATALOG: dict[str, tuple[Tier, DocumentCategory]] = {
    "pay_stub": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "w2": (Tier.TIER_1, DocumentCategory.INCOME_EMPLOYMENT),
    "bank_statement": (Tier.TIER_1, DocumentCategory.ASSETS),
    # … planned Tier-1 types (extractors arrive in LP-60..64) …
    # … a starter Tier-2 set per category (LP-59 fills out all ~80) …
}
```

Helpers: `get_tier(document_type)`, `get_category(document_type)`,
`get_tier_and_category(document_type)`, `is_cataloged(document_type)`. Anything
**not** in the catalog defaults to `(Tier 3, Misc)`.

Why a catalog (not a DB table, not scattered `if/elif`):

- **Maintainable** — adding/retiring a type is a one-line edit. No migration:
  tier and category are app-layer knowledge (ADR-053/ADR-167); only the *tier a
  document was handled as* is persisted (the `documents.tier` column), never the
  type→tier *mapping*.
- **One source of truth** — both the tier (for routing) and the category (for
  filing / needs-matching) come from the same entry, so they never drift. The
  catalog replaces the Phase-1 provisional `_TYPE_TO_CATEGORY` map.

As of **LP-59** the catalog spans the **full ~80-type taxonomy** (88 types: 18
Tier 1, 70 Tier 2, across all seven categories) — an **industry-standard
starter** for a US residential mortgage file. It is **not** yet validated against
the domain expert's (Priya's) real library; expect it to **refine with Priya**
and per-type accuracy to be confirmed against real labeled documents over time.

## Comprehensive classification (LP-59)

The Haiku classifier recognizes all ~80 types. Two pieces, kept in sync by
construction:

- **The catalog** is the structural source of truth (type → tier + category).
- **`DOCUMENT_TYPE_INDICATORS`** (`app/ai/classification_prompt.py`) holds each
  type's *distinguishing indicators* — the cues that tell it from a look-alike
  (a W-2 vs a pay stub, a Loan Estimate vs a Closing Disclosure).

`render_classification_prompt()` builds the system prompt by **iterating the
catalog** (grouped by category) and injecting each type + its indicator into a
template (`prompts/classification/document_classifier.txt`, which holds the
framing + output rules). So the prompt's type list **is** the catalog's — they
cannot drift. A test asserts the indicator set exactly equals the catalog set, so
adding a type without describing it fails CI.

The classifier reads the document directly (PDF/image content block — no OCR) and
returns `document_type` + `category` + `confidence`. The returned **category is
advisory** (kept for observability); the authoritative category persisted on the
document is the **catalog's** `get_category` — one source of truth.

### Confidence handling

Routing branches on **confidence**, not on the `unknown` slug alone (threshold
`0.5`):

- **High confidence + a known type** → route to that type's tier.
- **Low confidence** (the model is unsure *which* known type — it could be one) →
  `NEEDS_REVIEW`; a human confirms/corrects via the LP-44 override.
- **High-confidence `unknown`** (the model is sure it is *none* of the known
  types) → **Tier 3** (the generic analyzer — that is its purpose).
- The graceful **error fallback** returns `unknown` at **zero** confidence, so AI
  failures land in `NEEDS_REVIEW` (low confidence), not Tier 3.

### Accuracy — honestly scoped

The taxonomy + indicators are an industry-standard **starter**. Tests verify the
**mechanism** (catalog/prompt sync, routing by tier, the confidence gates) and a
**representative spread** of types — **not** exhaustive per-type accuracy, which
needs real labeled documents (not available for all ~80) and is validated over
time and **refined with Priya**.

### Categories

`DocumentCategory` (a DB-enforced enum, VARCHAR + CHECK): `assets`,
`borrower_info`, `credit`, `disclosures`, `income_employment`, `property`,
`misc`, `custom`. The catalog default category for the long-tail is `misc`.

## Tier-aware routing

`process_document` (`backend/app/tasks/document_processing.py`) consults the
catalog **after** classification:

```
read bytes → classify (Haiku) → set tier + category from the catalog →
  confidence < 0.5 ? → NEEDS_REVIEW            (unsure which type — a human confirms)
  else route by tier:
    Tier 1 → EXTRACTORS registry          (extractor built → extract;
                                            not built yet → classified-only)
    Tier 2 → _tier2_summarize_stub        (LP-65 — terminal)
    Tier 3 → _tier3_analyze_stub          (LP-66 — terminal; a confident
                                            "unknown" lands here)
```

(LP-59 made the gate **confidence-based**: a high-confidence `unknown` is *not*
sent to review — it routes to Tier 3.)

**Every document takes exactly one path and reaches a terminal status**
(`COMPLETED` / `NEEDS_REVIEW` / `FAILED`) — never left stuck. Two notes:

- **A Tier-1 type whose extractor isn't built yet** (the LP-60..64 types,
  cataloged now) is handled as **classified-only → `COMPLETED`** (no crash),
  exactly as Phase 1 handled a type with no registered extractor. When its
  extractor registers, the same path runs extraction — no pipeline change.
- **Tier 2 / Tier 3 are clean stubs** that record the document at its tier and
  reach `COMPLETED`. LP-65/66 fill the real summary / analyzer **in place**; the
  routing structure is already complete.

## What's built vs. what's next

**LP-58 (foundation):** the `Tier` enum + `tier` column (+ migration), the catalog
+ helpers, catalog-driven category, and tier-aware routing (Tier 1 fully working
via the registry; Tier 2/3 cleanly stubbed). The 3 existing types route as Tier 1.

**LP-59 (this breadth):** the full ~80-type catalog, the comprehensive
catalog-synced classification prompt (per-type indicators), the advisory
category, and confidence-gated routing (low → `NEEDS_REVIEW`; confident-`unknown`
→ Tier 3).

**Next:** LP-60..64 (Tier-1 extractors) → LP-65 (Tier-2 summary) → LP-66 (Tier-3
analyzer). The taxonomy + indicators refine with Priya over time.
