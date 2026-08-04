# Extraction bench (dev-only)

A development-only tool that runs a folder of **real** documents through the **live** classification +
extraction pipeline and reports what the schemas actually capture.

> **It measures COVERAGE, not ACCURACY.** Every number it reports is *"was this field populated"* —
> never *"is the value correct."* A high fill rate is **not** evidence the extractor reads the field
> correctly. The report itself repeats this in every artifact.

It persists **nothing** to the database. It writes JSON + Markdown + CSV to disk and nothing else. It
changes nothing about the system under test — production prompts are byte-unchanged, the rule engine is
untouched (`ACTIVE_RULE_IDS == 37`), and no production module imports the bench.

---

## What it is for

We have 109 registered extractors and a growing rule set, but our confidence in what the schemas
*actually* capture on real paperwork is thin (the MISMO parser, for one, was hardened against a single
real file). The bench closes that gap: point it at a folder of real documents and it tells you, per
document type, which fields fill in, what values they return, what valuable data is landing in the
catch-all instead of a typed field, how classification behaves, and whether the documents a rule family
needs even appear in the corpus.

It answers *"is the schema good enough to build a rule on"* — a question that needs real documents, not
fixtures.

## The two gates (defence-in-depth)

The tool must be unreachable in production. Two independent gates enforce that:

1. **The mount** — the API router is added to the app **only** when `settings.is_development`
   (`app/main.py`). In staging/production it is never mounted, so the routes do not exist.
2. **The guard** — every handler additionally calls `_require_dev()`, which raises `404` unless
   `settings.is_development` (`app/api/dev_bench.py`). So even a misconfigured mount cannot serve it.

The frontend page is belt-and-braces on top: under a production build (`NODE_ENV === "production"`) it
renders an "unavailable" notice instead of the controls. That is UX only — the backend `404` is the real
boundary.

## How the bench prompt is kept separate from production

The bench needs the model to placeholder PII, but **production prompts must be provably untouched.** So
the PII-placeholder instruction is *not* added to any production prompt:

- It lives in its **own file** — `app/dev/bench/bench_pii_instruction.txt`, next to the bench code,
  **never** under `app/ai/prompts/extraction/`.
- It is **appended at call time** by a scoped monkeypatch of the one shared extraction call site
  (`model_call.complete` — every extractor funnels through `run_extraction_completion` → `_attempt` →
  `complete`). The patch is installed only inside a `with bench_pii_prompt():` block, which the bench
  process enters and nothing else does. On exit the original is restored.

This is enforced, not just intended, by `tests/dev/test_extraction_bench.py`:

- the instruction file exists and lives outside the production prompt tree;
- **no** production extraction prompt mentions `PII PLACEHOLDER` / `[SSN]` / "extraction bench";
- **no** production module imports `app.dev.bench` (allow-list: the dev router + the dev-gated
  `main.py` mount);
- within `bench_pii_prompt()` the system prompt gets the instruction appended, and outside it the call
  is byte-unchanged (proven by capturing what reaches a mocked `complete`).

## PII redaction — two layers

Because we run **real** documents, PII is redacted before anything is written:

- **Layer 1 (model)** — the bench prompt tells the model to return placeholders in place of identity
  data: person name → `[NAME]`, street address → `[ADDRESS]`, SSN/TIN → `[SSN]`, DOB → `[DOB]`, phone →
  `[PHONE]`, email → `[EMAIL]`, full account number → `[ACCOUNT]`. A masked last-4 (`****1234`) is kept.
  It applies **everywhere** — typed core, list rows, and the catch-all. It deliberately **keeps**
  amounts, dates, statuses, form codes, and organisation names (creditors, banks, carriers, employers,
  bureaus), because those are what the bench measures.
- **Layer 2 (regex backstop)** — after extraction, `redact_tree` sweeps every string in the result
  (typed core, list rows, catch-all — recursively) for missed identity *shapes*: SSNs, long digit runs
  (account numbers), phones, emails → `[redacted]`. Organisation names, amounts, form codes, and masked
  last-4 survive it (asserted in tests). The classifier's short free-text reasoning is run through the
  same string redactor, since it can echo a snippet.

Because both layers run before disk I/O, a `borrower_name` "fill rate" reflects *whether the field was
populated*, not any real name — the report says so explicitly.

## The flow

Deliberately two-step, so a real spend is never a surprise:

1. **Preview** (`POST /preview`) — walks the folder recursively, counts files, breaks them down by
   extension, lists the unreadable ones (zero bytes, unsupported extension, or a `.pdf` without a
   `%PDF-` header) and their reason, and estimates cost (readable count × a rough per-document figure).
   **Nothing is sent to a model.**
2. **Start** (`POST /start`) — only on an explicit press. Launches a background task and returns a
   `run_id`. The page then polls `GET /status/{run_id}` (progress, cost-so-far, current file) until
   finished. `POST /cancel/{run_id}` interrupts after the in-flight document and writes what it has.

Estimated cost is a guardrail (midpoint of two real Haiku-4.5 measurements: a credit report ~$0.074, a
pay stub ~$0.021 → $0.05/doc). **Actual** cost is measured per document from real token counts.

## Output

Written under `bench_output/<run_id>/` (a sibling of the storage root — outside the DB, never persisted
to it):

- **per-document JSON** at `<type>/<n>-<file>.json` — the redacted classification + extraction record
  for one document;
- **`_SUMMARY.md`** — the cross-document report (the five findings, human-readable), headed by the
  coverage-not-accuracy warning;
- **`_FINDINGS.csv`** — the same findings as a flat table for spreadsheeting.

## The five findings and how each is computed

All are **evidence for a human**. They report numbers; they never diagnose which cause produced a null
field, and never propose or apply a change.

1. **Coverage** — per typed-core field of a document type, populated on N of M documents.
   `populated` counts non-null, non-blank values. This is fill rate, i.e. coverage.
2. **Value vocabulary** *(the most valuable)* — every distinct value each typed field returned, with
   counts (top 25). A field is flagged **open-ended** when it is populated on ≥4 documents and
   `distinct / populated ≥ 0.6` — i.e. the values look like free text or issuer codes, so the field
   **cannot back a deterministic rule**. This is the signal that keeps us from building a rule on a
   field that will never take a stable, enumerable value (cf. LP-448 / LP-455, which stalled on exactly
   this).
3. **Stranded data** — the catch-all (`additional_sections`) for a type, grouped by `section :: label`
   with counts, plus how many documents had any catch-all. A label recurring across many documents is a
   **schema gap** — something valuable is being captured but not typed, so no rule can read it.
4. **Classification** — confidence distribution (`<0.5`, `0.5–0.7`, `0.7–0.9`, `≥0.9`), the list of
   low-confidence (`<0.7`) documents, and the count of each type seen. Surfaces documents the classifier
   is unsure about and confusable type pairs.
5. **Rule readiness** *(coarse)* — per rule-id **prefix** (the rule family, e.g. `AS`, `CR`, `IN`), did
   a document type that family needs appear in the corpus, and if so its average typed fill rate. It is
   deliberately coarse — a rule may read several documents — so it answers *"did a document this family
   needs even show up,"* **not** the full LP-451 per-rule gate. The report labels it as such.

## Files

**Backend** (`app/dev/bench/`, plus the dev router):

- `bench_pii_instruction.txt` — the separate PII-placeholder instruction (not under the prompt tree).
- `prompt.py` — `bench_pii_instruction()` + the `bench_pii_prompt()` scoped monkeypatch.
- `redact.py` — the layer-2 regex backstop (`redact_string`, `redact_tree`).
- `engine.py` — `walk_documents`, `preview`, `run_one` (classify → extract under the bench prompt →
  redact → cost), and the per-document findings slice.
- `findings.py` — the five findings + the JSON / `_SUMMARY.md` / `_FINDINGS.csv` writers.
- `app/api/dev_bench.py` — the dev-gated router (`/dev/extraction-bench/{preview,start,status,cancel}`).
- `app/main.py` — the conditional (`is_development`) mount.

**Frontend**:

- `lib/api/extraction-bench.ts` — the typed data layer.
- `app/(protected)/dev/extraction-bench/page.tsx` — the dev page (preview → start → progress),
  prod-gated.

**Tests**: `tests/dev/test_extraction_bench.py` — the separation and safety guarantees (17 tests).

## What it deliberately does not do

- It does **not** judge accuracy — only coverage.
- It does **not** write to the database.
- It does **not** propose or apply schema/rule changes — it produces evidence a human reads.
- It does **not** modify production prompts or the rule engine.
