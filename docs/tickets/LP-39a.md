# LP-39a — Extraction Shape: Typed Core + Grouped Catch-All + Source Location (Pay Stub)

- **Ticket:** LP-39a — extraction shape (typed core + grouped catch-all + source location), pay stub; Phase 3 design note
- **Epic:** Epic 5 — Document Upload & Processing
- **Status:** Completed
- **Date:** 2026-06-12

## Summary

Established the **new extraction shape** on the pay stub — **typed core + grouped catch-all +
per-field source location** — and recorded the Phase 3 verification design. Extraction now
captures **every** field on a document (processors use all fields; the Phase 3 AI cross-source
layer needs the full content to catch discrepancies like an undisclosed decree obligation)
while keeping the decision-driving fields **typed** so the deterministic verification engine
(Phase 3) can consume them. This shape is reused by W-2 (LP-39b) and bank statement (LP-39c).

## What Was Built

- **Shape types** (`app/ai/extraction/shape.py`) — `SourceLocation {page, snippet}`,
  `TypedField[T] {value, source}` (PEP 695 generic), `CatchAllField {label, value, source}`,
  `CatchAllSection {section, fields}`. Reusable across document types.
- **Reshaped `PayStubExtraction`** — a **typed core** (11 decision fields, each a `TypedField`
  with source) + **`additional_sections: list[CatchAllSection]`** (everything else, by
  section). The result wrapper (`data/status/confidence/reasoning` + `.failed()`) is unchanged.
- **Rewritten prompt** (`prompts/extraction/pay_stub.txt`) — extract EVERYTHING; core → typed
  slots, the rest → grouped sections; **page + verbatim snippet per field**; null-not-guess; a
  documented JSON contract (`typed_core` + `additional_sections`).
- **New-shape parser** — typed core coerced (currency/date/string) with source; grouped
  catch-all passed through (strings); tolerant (fences/prose, flat fallback, bad sections/
  fields skipped); honest nulls; graceful failure.
- **LP-42** — stores the richer JSON unchanged in mechanism (`create_extraction_version`); the
  log now counts `core_fields_present` + `catch_all_sections` (no values).
- **LP-43 drawer** — a new `ExtractionView` renders the typed core (key/value + click-to-source)
  and the grouped catch-all as **collapsible sections**; TS types mirror the shape.
- **Phase 3 design note** — `docs/phase-3-verification-design.md`.

## The New Shape

```
PayStubExtraction
├─ typed core: employer_name, …, gross_pay, … (each TypedField{value, source})
└─ additional_sections: [ {section, fields: [{label, value, page, snippet}]} ]
```

**Capture everything, keep decision fields typed.** The typed core is what the Phase 3
deterministic rules read (DTI/recency as `Decimal`/`date`); the catch-all is what makes the
cross-source/divorce-decree case catchable and lets the processor see the whole document.

## Source Location (page + snippet)

Every field — typed core **and** catch-all — carries a `SourceLocation` (page + verbatim
snippet) of where it was read. A present-but-uncoercible typed value drops to `value=None`
**but keeps its source**. The drawer's click-to-source affordance reveals `p.{page}:
"{snippet}"` — the trust/audit mechanism (visual bounding boxes deferred).

## Reused By

The `shape.py` types are document-type-agnostic and are reused by **W-2 (LP-39b)** and **bank
statement (LP-39c)** — same typed-core + grouped-catch-all + source pattern.

## Decisions Made

- **ADR-145** — pay-stub extraction realizes the typed-core + grouped-catch-all + source shape
  (implements **ADR-144**).
- The verification behaviour these feed is recorded in `docs/phase-3-verification-design.md`
  (**ADR-140…144**).

## Assumptions

- The **typed core is a V1 starter** (refine with Priya); it **grows in Phase 3** by promoting
  catch-all fields as deterministic rules need them.
- **Catch-all values are strings** (not coerced) — only the typed core is coerced.
- **Verification / findings / aggression dial** are Phase 3 — only **recorded** here (the
  design note + ADRs), not built.
- The prompt + field set remain **starters** (Priya / POC).
- **W-2 (LP-39b)** and **bank statement (LP-39c)** are next, on this shape.

## Verification Performed

Backend `uv run pytest` → **480 passed**; ruff check + format, `mypy app/` (strict), pre-commit
clean. Frontend `pnpm lint` + `pnpm typecheck` + `pnpm build` pass; **16 vitest**.

- **Backend (mocked AI)** — full-shape success (typed core coerced + source; catch-all
  preserved by section); **source location** present on core + catch-all; **nothing dropped**
  (a non-core field lands in the catch-all); honest nulls (absent → `value None`); currency/
  date coercion; **junk core field → None, source kept, PARTIAL**; all-null → FAILED;
  malformed → `failed`; AI failure → `failed`; empty/unsupported → `failed` without calling;
  confidence clamp; flat fallback; catch-all skips empty/bad sections; **no bytes/base64/
  values logged** (incl. a catch-all SSN). Pipeline tests updated for the `TypedField` shape.
- **Frontend** — `extractionFields` reads `{value, source}` (+ bare-value tolerance);
  `catchAllSections` filters odd shapes; `formatSource` formats `p.N: "snippet"`.

## Notes

- **Developer:** refine the typed core + prompt with Priya / the POC pay-stub prompt; the
  catch-all section names come from the model and are passed through.
- The drawer's catch-all uses native `<details>` (accessible, collapsible); the source
  snippet is revealed on demand (not always shown, to keep the view calm).

## What's Next

- **LP-39b** — W-2 extraction on this shape (typed core for W-2 + grouped catch-all).

## References

- `backend/app/ai/extraction/shape.py`, `backend/app/ai/extraction/pay_stub.py`,
  `backend/app/ai/prompts/extraction/pay_stub.txt`; `backend/tests/ai/test_pay_stub_extraction.py`,
  `backend/tests/tasks/test_document_processing.py`.
- `frontend/lib/types/document.ts`, `frontend/lib/loan-files/documents.ts`
  (+ `documents.test.ts`), `frontend/components/file/documents/extraction-view.tsx`,
  `document-drawer.tsx`.
- `docs/phase-3-verification-design.md`; `docs/architecture.md` — Extraction shape.
  `decisions.md` — ADR-144/145 (+ ADR-140…143 for the verification design).
