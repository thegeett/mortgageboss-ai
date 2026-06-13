# POC Learnings

Lessons carried forward from the proof-of-concept (POC) into the V1 build.

> **How to read this doc:** sections pre-populated from project context are
> factual. Sections marked **📝 DEVELOPER TODO** need first-hand knowledge of the
> POC that only the developer has — please expand them. They are the most
> valuable part of this document.

---

## POC overview

The POC was an in-memory exploration of the core AI workflow for mortgage
documents: **classify** a document by type, **extract** structured fields from
it, and **verify** the results with a set of rule utilities. It used a
session-based, in-memory architecture (no database) to move fast and prove the
concept before committing to a schema.

## What the POC proved

- AI classification of mortgage document types is feasible and reliable enough to
  drive an automated pipeline.
- AI extraction of structured fields from document text is feasible.
- A library of verification utilities can turn extracted data into useful
  red/yellow/green signals.

## Why V1 starts fresh

The POC and V1 differ enough that porting code directly would do more harm than
good:

- **Generic vs typed extraction.** The POC used a generic `ExtractedField`
  (`fieldName` / `value` / `confidence`). V1 uses **typed, document-specific
  schemas** (e.g. a `PayStubExtraction` with real fields) so downstream rules can
  rely on shapes.
- **Generic vs program-specific verification.** The POC's verification was a set
  of generic utilities (`cross_document`, `derived_math`, `recency`,
  `internal_bank`, `internal_paystub`, `internal_w2`, `transactions`). V1 needs
  **program-specific rules** (Conventional / FHA) tied to investor guidelines and
  lender overlays.
- **In-memory vs persistent + multi-tenant.** The POC kept state in a session
  store; V1 is built on a **multi-tenant PostgreSQL** schema with soft delete,
  versioning, and an audit log.

The *concepts* carry forward; the *shapes* are too different to port.

## What carries forward from the POC

- **Prompts** — the classification and extraction prompts, copied as text into
  `backend/app/ai/prompts/...` (Epic 5).
- **Test documents** — sample documents copied into test fixtures.
- **Lessons** — this document.

## POC components worth referencing during V1 development

Reference these for *patterns and logic*, re-implemented against V1's typed,
persistent architecture — not copied wholesale:

| POC component             | Reference when building…                                   | Phase     |
| ------------------------- | ---------------------------------------------------------- | --------- |
| `name_matching.py`        | comparing names across documents                           | Phase 2–3 |
| `transaction_classifier.py` | bank-statement transaction categorization                | Phase 2   |
| `internal_paystub.py`     | per-document pay-stub validation                           | Phase 2–3 |
| `internal_w2.py`          | per-document W-2 validation                                | Phase 2–3 |
| `internal_bank.py`        | per-document bank-statement validation                     | Phase 2–3 |
| `cross_document.py`       | cross-source verification rules                            | Phase 3   |
| `recency.py`              | documentation timing/recency rules                         | Phase 3   |
| `derived_math.py`         | DTI / LTV calculators                                      | Phase 3   |
| `email_generator.py`      | the communication module                                   | Phase 4   |
| `runner.py`               | general orchestration patterns                             | general   |

## POC components NOT to reference

- **`session_store.py`** — an anti-pattern for V1. It held state in memory; V1's
  source of truth is PostgreSQL. Do not model persistence on it.

---

## 📝 DEVELOPER TODO: Specific edge cases and gotchas from the POC

> This section can only be written by someone who ran the POC. Please expand it —
> it will save real time during Epics 2–6. Suggested prompts:
>
> - **Documents that were hard to classify or extract.** Which document types or
>   layouts confused the model? Any formats to special-case?
> - **Extraction gotchas.** Fields that were unreliable, ambiguous, or formatted
>   inconsistently (dates, currency, employer names, YTD vs current, etc.).
> - **Verification surprises.** Rules that produced false positives/negatives;
>   thresholds that needed tuning; cross-document mismatches that were actually
>   fine.
> - **Prompt lessons.** What phrasing/structure worked; what made the model
>   hallucinate or over/under-confidently classify.
> - **Model choice notes.** Where Haiku was sufficient vs where Sonnet was needed;
>   latency/cost observations.
> - **Domain gotchas (ask the domain expert).** Mortgage-specific edge cases the
>   POC revealed — co-borrowers, multiple employers, gaps in employment, large
>   deposits, gift funds, etc.
> - **Anything that surprised you.** The "I didn't expect that" moments.

_(Replace this block with your notes. Keep the bullets that apply; delete the
rest.)_
