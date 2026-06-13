# LP-39b — W-2 Extraction (typed core + grouped catch-all + source location)

- **Ticket:** LP-39b — W-2 extraction on the typed-core + grouped-catch-all shape (SSN masked/never-logged)
- **Epic:** Epic 5 — Document Upload & Processing
- **Status:** Completed
- **Date:** 2026-06-12

## Summary

Added **W-2 extraction**, the **first replication** of the LP-39a extraction shape (typed core
+ grouped catch-all + per-field source) onto a new document type — proving the shape
generalizes. A W-2 is a fixed federal form whose decision fields are **annual** figures (a
different typed core than the pay stub's period figures), so it demonstrates "different typed
core, **same shape**" — what Phase 2's ~100-type fan-out needs. Pay stub (LP-39a) is built;
bank statement + pipeline routing is LP-39c.

## What Was Built

- **Shared parser** (`app/ai/extraction/parsing.py`) — refactored out of the pay-stub module so
  W-2 (and LP-39c) reuse it, no duplication: the field coercers (`coerce_decimal`, `coerce_date`,
  `coerce_str`, **`coerce_int`** new, `coerce_page`), `source_payload`, `parse_typed_core(payload,
  core_spec)`, `parse_catch_all`, `derive_status`. Pay stub was refactored onto it (its tests
  unchanged and green).
- **`W2Extraction`** (`app/ai/extraction/w2.py`) — typed core (each a `TypedField` with source)
  + `additional_sections`; `W2ExtractionResult` (`data/status/confidence/reasoning` +
  `.failed()`, mirrors the pay stub). `extract_w2(content, media_type)` mirrors
  `extract_pay_stub`.
- **W-2 prompt** (`prompts/extraction/w2.txt`) — extract everything; core → typed slots (with
  box numbers); the rest → grouped sections (State/Local, Box 12 Codes, Box 13, Box 14, Other);
  page + snippet per field; null-not-guess; the documented JSON contract.
- **SSN masking (frontend)** — `maskSsn` helper + `MASKED_FIELD_KEYS`; the drawer's
  `extractionFields` now handles **any** typed core (pay stub or W-2) and **masks
  `employee_ssn`** (last-4). W-2 field labels + money keys added.
- **Backend + frontend tests**; docs + ADRs.

## The W-2 Typed Core (box mapping)

| Field | Type | Source |
| --- | --- | --- |
| `tax_year` | `int` | the year on the form |
| `employee_name` / `employee_ssn` | `str` | identity (box e / box a) — **SSN sensitive** |
| `employer_name` / `employer_ein` | `str` | box c / box b |
| `wages_tips_other_comp` | `Decimal` | **Box 1** (federal taxable wages) |
| `federal_income_tax_withheld` | `Decimal` | Box 2 |
| `social_security_wages` / `_tax_withheld` | `Decimal` | Boxes 3 / 4 |
| `medicare_wages` / `_tax_withheld` | `Decimal` | Boxes 5 / 6 |

Everything else (state/local Boxes 15-20, Box 12 codes, Box 13 checkboxes, Box 14, control
number, addresses) → the **grouped catch-all**. V1 starter; grows in Phase 3.

## Reuse of the LP-39a Shape

Reuses `shape.py` (`SourceLocation`, `TypedField[T]`, `CatchAllField`, `CatchAllSection`) and
the shared parser; keeps honest nulls / no hallucination, tolerant coercion (a single bad core
field → `None`, source kept → `PARTIAL`), defensive parsing, graceful failure (never raises),
full-document Sonnet reading, prompt-as-file, metadata-only logging. The LP-43 drawer renders a
W-2 with the same generic typed-core + collapsible catch-all + click-to-source view.

## SSN Handling (ADR-147)

`employee_ssn` is **extracted** into the typed core (for the Phase 3 W-2-SSN-vs-borrower-SSN
identity cross-check) but **sensitive**: **never logged** (metadata-only logging; a test asserts
the SSN value is absent from logs) and **displayed masked** (last-4, `•••-••-6789`) in the
drawer — consistent with the borrower `masked_ssn` discipline. The raw value lives only in the
tenant-scoped extraction JSON. *(Flagged for confirmation: the alternative — not extracting the
SSN at all — was rejected so the cross-check can compare actual values.)*

## Decisions Made

- **ADR-146** — W-2 extraction on the typed-core + grouped-catch-all shape.
- **ADR-147** — W-2 SSN extracted for the identity cross-check, masked in display, never logged.

> **ADR numbering:** LP-39a used 144/145; the next free numbers were **146-147**.

## Assumptions

- The typed core is a **V1 starter** (refine with Priya); **grows in Phase 3**.
- **Routing into the LP-42 pipeline** (fan-out to pay stub / W-2 / bank statement) is **LP-39c**
  — W-2 is not yet wired into `process_document`.
- **Verification / cross-source** is Phase 3.
- The prompt + typed core are **starters** (Priya / POC). Tests **mock** the wrapper (no key).

## Verification Performed

Backend `uv run pytest` → **501 passed** (21 new W-2 tests; pay-stub + pipeline tests unchanged
and green after the shared-parser refactor); ruff check + format, `mypy app/` (strict),
pre-commit clean. Frontend `pnpm lint` + `pnpm typecheck` + `pnpm build` pass; **18 vitest**.

- **W-2 (mocked AI)** — full-shape success (typed core coerced + source; catch-all by section);
  source location on core + catch-all; **`tax_year` is an int**, boxes are `Decimal`, names/SSN/
  EIN strings; **nothing dropped** (a non-core field lands in the catch-all); honest nulls;
  junk core field → `None`, source kept, `PARTIAL`; all-null → `FAILED`; malformed → `failed`;
  AI failure → `failed`; empty/unsupported → `failed` without calling; confidence clamp.
- **Privacy / SSN** — bytes/base64/extracted values absent from logs, and **specifically the
  SSN value (`123-45-6789`) never appears**; the metadata log carries only `core_fields_present`
  / `catch_all_sections`. The raw SSN is still returned to the caller (tenant-scoped JSON).
- **Frontend** — `maskSsn` (last-4, `—`/`•••` for empty/short); `extractionFields` masks
  `employee_ssn` and renders `tax_year` + Box amounts; `additional_sections` excluded from the
  typed-core rows.

## Notes

- **Developer:** refine the W-2 typed core + prompt with Priya / the POC W-2 prompt.
- The catch-all section names come from the model (passed through).

## What's Next

- **LP-39c** — bank statement extraction on this shape **+ pipeline routing** (`process_document`
  fans out to pay stub / W-2 / bank statement by classified type).

## References

- `backend/app/ai/extraction/w2.py`, `backend/app/ai/extraction/parsing.py` (shared, refactored),
  `backend/app/ai/extraction/pay_stub.py` (now uses the shared parser),
  `backend/app/ai/prompts/extraction/w2.txt`; `backend/tests/ai/test_w2_extraction.py`.
- `frontend/lib/loan-files/documents.ts` (`maskSsn`, masked `extractionFields`) + `documents.test.ts`.
- `docs/architecture.md` — Extraction per-type modules. `decisions.md` — ADR-146/147.
- Builds on LP-39a (shape), LP-37 (wrapper), the borrower `masked_ssn` discipline (LP-29/ADR-097).
