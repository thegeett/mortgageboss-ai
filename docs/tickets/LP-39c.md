# LP-39c — Bank Statement Extraction (transactions list) + Pipeline Routing to All Three Types

- **Ticket:** LP-39c — bank statement extraction (transactions list) + type-extractor registry routing all three types
- **Epic:** Epic 5 — Document Upload & Processing
- **Status:** Completed
- **Date:** 2026-06-12

## Summary

Added **bank statement extraction** — the most complex of the three Phase 1 types (nested
transactions) — and a **type→extractor dispatch registry** that fans the LP-42 pipeline out to
all three types (pay stub, W-2, bank statement). After this, **all three Phase 1 document
types flow through the live pipeline and extract.** This completes the Phase 1 extraction set.

## What Was Built

- **`bank_statement.py`** — a `Transaction` model + `BankStatementExtraction` (typed core +
  **`transactions: list[Transaction]`** (ADR-061) + `additional_sections`) +
  `BankStatementExtractionResult` (+ `.failed()`); `extract_bank_statement`. Reuses `shape.py`
  + the shared parser; a `_parse_transactions` helper.
- **Prompt** (`prompts/extraction/bank_statement.txt`) — read ALL pages; core → typed slots;
  **every transaction → the list** (date/description/amount/type/running balance, page+snippet);
  the rest → grouped sections; **never invent a transaction**; documented JSON contract.
- **Registry** (`app/ai/extraction/__init__.py`) — `EXTRACTORS = {pay_stub, w2, bank_statement}`
  + an `ExtractionResult` Protocol + an `Extractor` type. Replaces LP-42's `if/elif`.
- **Pipeline** — `process_document` routes via the registry (`_extract_branch` generalized,
  needs rule generalized to the document's category); a **`reprocess_document_extraction`** core
  (the function LP-44's override calls) uses the **same** registry. `w2`/`bank_statement` added
  to the type→category map (already present).
- **Drawer** — a **transactions table** (date / description / amount / running balance,
  scrollable for long lists) + the account number **masked** (`maskLast4`, generalizing
  `maskSsn`). TS `Transaction` type + `extractionTransactions` helper.

## The Transactions List (ADR-061)

A bank statement's decision-relevant content is its transactions, so they're **first-class
typed rows** (not loose catch-all): `date` (`date`), `description`, `amount` (`Decimal`),
`transaction_type`, `running_balance` (`Decimal`), `source`. Captured across **all pages**.
**No hallucination** — only rows the model returned are kept; a fully-empty row is dropped, a
bad field becomes `None` (the row is kept), a fabricated row is never created.

## The Dispatch Registry (ADR-149)

`EXTRACTORS.get(document_type)` → the type's extractor (or classified-only if unregistered),
used by **both** `process_document` and `reprocess_document_extraction`. The result types share
a structural `ExtractionResult` Protocol, so the pipeline stores any extraction uniformly via
`create_extraction_version(result.data.model_dump(mode="json"), ...)`. **Adding a Phase 2 type
= write an extractor + register it.** All LP-42 resilience (unexpected → FAILED safe; every path
terminal; retry-safe) and the needs/activity behaviour are preserved.

## Reuse of the Shape

Reuses `shape.py` + the shared parser (`app/ai/extraction/parsing.py`); keeps honest nulls /
no hallucination, tolerant coercion (single bad field/row → `None`), defensive parsing,
graceful failure (never raises), full-document Sonnet reading, prompt-as-file, metadata-only
logging.

## Sensitivity (ADR-150)

`account_number_masked` is captured masked, **never logged** (metadata-only logging: status,
confidence, transaction count, core-field count — no values, no account number; tested), and
**displayed masked** to last-4. Reuses/generalizes the LP-39b SSN pattern.

## The Hard Parts

- **Multi-page** — capture transactions from all pages (Option A, whole document).
- **Output length** — `max_tokens=8192` so long lists aren't truncated.
- **Truncation** — an incomplete/malformed JSON (long list cut off) → `.failed("could not parse
  extraction")`, never a crash (tested with a truncated array).
- **No hallucinated transactions** — reinforced in the prompt and the parser.

## Decisions Made

- **ADR-148** — bank statement: typed core + typed transactions list (ADR-061) + catch-all.
- **ADR-149** — type→extractor dispatch registry (pipeline fan-out).
- **ADR-150** — bank account number captured masked, never logged, displayed masked.

> **ADR numbering:** LP-39b used 146/147; the next free numbers were **148-150**.

## Assumptions

- **Transaction analysis** (large-deposit flags, NSF, sourcing) is **Phase 3** — this only
  EXTRACTS.
- The typed core is a **V1 starter**; the registry scales to Phase 2 (~100 types).
- The **LP-44 override endpoint/UI** is not built here — only `reprocess_document_extraction`
  (the registry-using core it will call).
- Prompt + typed core are **starters** (Priya / POC). Tests **mock** the wrapper (no key).

## Verification Performed

Backend `uv run pytest` → **525 passed** (19 new bank statement + 5 new pipeline registry/
reprocess; pay-stub/W-2/pipeline unchanged and green); ruff check + format, `mypy app/`
(strict), pre-commit clean. Frontend `pnpm lint` + `pnpm typecheck` + `pnpm build` pass; **21
vitest**.

- **Bank statement (mocked AI)** — full-shape success (typed core coerced + source; **multiple
  transactions** as typed rows with date/amount/running_balance + source; catch-all); **nothing
  dropped**; **no hallucination** (junk row dropped, a partial row kept with the bad field
  `None`); honest nulls; transactions-only → SUCCEEDED; **truncated/malformed JSON → `.failed()`**
  (no crash); AI failure → `.failed()`; empty/unsupported → `.failed()` without calling;
  confidence clamp; **account number never logged** (and bank name / a transaction description
  never logged), with the raw account still returned to the caller.
- **Pipeline registry** — `pay_stub`/`w2`/`bank_statement` each route to their extractor → an
  `Extraction` version + COMPLETED; an **unregistered type → classified-only** (no extraction);
  **`reprocess_document_extraction` uses the registry** (re-extracts via the new type; unregistered
  → classified-only); all LP-42 resilience preserved (unexpected → FAILED; terminal; retry-safe).
- **Frontend** — `maskLast4` (account); `extractionFields` masks the account (last-4, not SSN
  format) and excludes `transactions`/`additional_sections`; `extractionTransactions` filters
  odd rows; bank balances render as currency.

## Notes

- **Phase 1 extraction set complete**: pay stub + W-2 + bank statement all live in the
  pipeline via the registry.
- **Developer:** refine each typed core + prompt with Priya / the POC prompts.

## What's Next

- **Epic 6 / Phase 1 completion** — integration tests (LP-45) and polish. (LP-44 — the manual
  type-override endpoint/UI — uses `reprocess_document_extraction` built here.)

## References

- `backend/app/ai/extraction/bank_statement.py`, `app/ai/extraction/__init__.py` (registry),
  `app/ai/prompts/extraction/bank_statement.txt`, `app/tasks/document_processing.py` (registry
  routing + `reprocess_document_extraction`).
- `backend/tests/ai/test_bank_statement_extraction.py`, `backend/tests/tasks/test_document_processing.py`.
- `frontend/lib/loan-files/documents.ts` (`maskLast4`, `extractionTransactions`) + `documents.test.ts`,
  `frontend/components/file/documents/extraction-view.tsx` (transactions table),
  `frontend/lib/types/document.ts` (`Transaction`).
- `docs/architecture.md` — bank statement + registry. `decisions.md` — ADR-148/149/150 (+ ADR-061).
