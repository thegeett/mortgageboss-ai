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
   `%PDF-` header) and their reason, estimates cost (readable count × a rough per-document figure), and
   shows the **pacing** (requests/min + an estimated duration). **Nothing is sent to a model.**
2. **Start** (`POST /start`) — only on an explicit press. Launches a background task and returns a
   `run_id`. The page then polls `GET /status/{run_id}` (progress, cost-so-far, current file,
   rate-limited count) until finished. `POST /cancel/{run_id}` interrupts after the in-flight document
   and writes what it has. Pass `resume_run_id` to **continue** an interrupted run (see below).

Estimated cost is a guardrail (midpoint of two real Haiku-4.5 measurements: a credit report ~$0.074, a
pay stub ~$0.021 → $0.05/doc). **Actual** cost is measured per document from real token counts.

## Rate limiting, throttling & resume

Under Bedrock the account is capped at ~10 requests/min; the bench makes **2 model calls per document**
(classification + extraction), so at a cap of **8 requests/min** it runs **4 docs/min** — a 200-document
run is ~50 min (floor). Four things keep a batch from corrupting its own findings:

- **Pacing is enforced by the client limiter** (`resolve_requests_per_minute` → `RateLimiter`), which
  gates every `complete()` call — both classification and extraction. Set
  `AI_REQUESTS_PER_MINUTE_BEDROCK=8` (units are **requests**, not documents).
- **The bench refuses to start unpaced.** If `AI_PROVIDER=bedrock` and no request limit is set, `POST
  /start` returns **409** — not a warning, a refusal. An accidental unpaced 200-document run is a mistake
  made impossible, not merely discouraged.
- **Throttled documents are tagged, not silently failed.** When `complete()` exhausts its retries on a
  429/throttle it raises `AIClientError`, and both call sites swallow it into a generic `"AI call
  failed"` — indistinguishable from a genuinely unparseable document. So the bench's runtime wrapper
  inspects the exception cause and, if transient (throttle/capacity/5xx/timeout), tags the record
  `rate_limited: true` **before** the sentinel hides it. Rate-limited documents are **excluded from every
  finding** and **counted separately** in `_SUMMARY.md` — a throttle can never read as a coverage gap.
  The summary states the rate-limited count on every run (`0` when none), so a rate-limit problem is
  never mistaken for a schema or network finding.
- **A run of failures aborts the run.** After **5 consecutive failed documents** — throttle, auth, or
  error (almost certainly infrastructure, not the corpus) — the run stops itself, marks
  `aborted_reason` (`rate_limited` or `ai_error`, with the cause type), and writes what it has rather
  than continuing to log false schema gaps. (This is why the 246 × "AI call failed" run should have
  stopped at 5.)
- **A preflight refuses a doomed run.** `POST /start` first makes one minimal live call; if the model
  backend is unreachable/unauthenticated (e.g. no AWS credentials) it returns **409 with the real error**
  rather than processing the whole corpus into `"AI call failed"` records. See
  [`extraction-bench-preflight.md`](extraction-bench-preflight.md).
- **A run where nothing succeeded is marked FAILED.** If 0 documents produced a result, `_SUMMARY.md`
  opens with a **`⚠️ RUN FAILED`** banner naming the cause — it can never read like a coverage result.

**Resume.** Each document's JSON is written **incrementally** as it completes, plus an append to a
`_records.jsonl` log — so a crash (or an abort, or a cancel) at document 150 of a 50–90 min run loses at
most the in-flight document. `POST /start` with `resume_run_id` reuses the output dir, skips the
documents already on disk, and still aggregates the whole corpus into the final findings.

⚠️ **Per-process caveat.** The client limiter is a **process-local** singleton. The bench runs inside the
dev API process, so its own calls are paced correctly — but if **Celery workers are also processing
documents** (which hit Bedrock from separate processes) during a bench run, the two limiters do not
coordinate, and the combined rate can exceed the account's 10/min. Run the bench when nothing else is
hitting Bedrock, or account for the workers' share in the cap.

## Output

Written under `<storage_local_path>/bench_output/<run_id>/` (inside the storage dir so it inherits
storage's gitignore; outside the DB, never persisted to it):

- **per-document JSON** at `<type>/<n>-<stem>.json` — the redacted classification + extraction record
  for one document, written **incrementally** as each document completes. The source extension is
  **stripped** before `.json` (`foo.pdf` → `<n>-foo.json`, not `foo.pdf.json`) so a file browser doesn't
  treat the JSON as a PDF;
- **`_records.jsonl`** — one record per line, the resume log (source of truth for resuming + the final
  aggregation);
- **`_SUMMARY.md`** — the cross-document report (the five findings, human-readable), headed by the
  coverage-not-accuracy warning and the **rate-limited count**;
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
