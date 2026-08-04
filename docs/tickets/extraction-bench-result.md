# Extraction bench — result

Outcome record for the dev-only extraction bench. The design/reference write-up is in
[`extraction-bench.md`](extraction-bench.md); this file records what was actually built, verified, and
found.

- **Branch:** `extraction_bench` (off `phase3_bucket_2` HEAD)
- **Scope:** a dev-only tool that runs a folder of real documents through the **live** classification +
  extraction pipeline and reports what the schemas capture. Measures **COVERAGE, not accuracy**.
  Persists **nothing** to the database.

## What was built

| Area | File | Purpose |
|---|---|---|
| Engine | `backend/app/dev/bench/engine.py` | walk + preview/cost + `run_one` (classify → extract under the bench prompt → redact → cost) |
| Findings | `backend/app/dev/bench/findings.py` | the five findings + `_SUMMARY.md` / `_FINDINGS.csv` / per-doc JSON writers |
| Bench prompt | `backend/app/dev/bench/prompt.py` + `bench_pii_instruction.txt` | the SEPARATE PII-placeholder instruction, appended at runtime only |
| Redaction | `backend/app/dev/bench/redact.py` | layer-2 regex backstop (`redact_string`, `redact_tree`) |
| API | `backend/app/api/dev_bench.py` | dev-gated router `/dev/extraction-bench/{preview,start,status,cancel}` |
| Mount | `backend/app/main.py` | conditional (`is_development`) include |
| Tests | `backend/tests/dev/test_extraction_bench.py` | 17 tests — separation + safety guarantees |
| Frontend data layer | `frontend/lib/api/extraction-bench.ts` | typed client for the four endpoints |
| Frontend page | `frontend/app/(protected)/dev/extraction-bench/page.tsx` | preview → start → progress, prod-gated |
| Docs | `docs/tickets/extraction-bench.md` | full write-up |

**Diff:** 14 files, +1460, all additive (only `main.py` is modified, +9 lines for the gated mount).

## Verification

| Check | Result |
|---|---|
| ruff (bench + router + `main.py` + tests) | ✅ All checks passed |
| ruff format | ✅ 9 files already formatted |
| mypy (whole app, 401 source files) | ✅ Success: no issues |
| bench tests (`tests/dev`) | ✅ 17 passed |
| frontend biome (new files) | ✅ clean |
| frontend tsc (`--noEmit`, strict) | ✅ clean |
| full backend suite | 4012 passed, 5 skipped, 1 xfailed, **15 env-driven failures** (see below) |

### The 15 full-suite failures are environment-driven, not the bench

All 15 come from the local `backend/.env` carrying `AI_PROVIDER=bedrock`; the affected tests
(`tests/ai/test_client.py`, `test_model_resolution_boundary.py`, `test_provider_selection_b1.py`,
`tests/tasks/test_document_processing.py`) are written to assert the **anthropic** default and reject a
bedrock provider. Proven independent of the bench:

- overriding `AI_PROVIDER=anthropic` on the same subset → **121 passed, 0 failed**;
- none of the failing tests touch bench code; the bench changes are isolated to `app/dev/`, the dev
  router, the dev-gated mount, and `tests/dev/`.

So the suite is green modulo the provider the environment is currently set to.

## Safety guarantees — confirmed

- **Two dev gates.** The router is mounted only when `settings.is_development` (`main.py`), and every
  handler also calls `_require_dev()` → `404` otherwise. The frontend page is belt-and-braces: under a
  production build (`NODE_ENV === "production"`) it renders "unavailable". The backend `404` is the real
  boundary.
- **Production prompts provably untouched.** The PII-placeholder instruction lives in its own file under
  `app/dev/bench/` (never under `app/ai/prompts/`) and is appended at call time by a scoped monkeypatch
  of the single shared extraction call site (`model_call.complete`) inside `with bench_pii_prompt():`.
  Tests assert no production prompt mentions the bench/PII placeholder and no production module imports
  `app.dev.bench`.
- **PII redacted in two layers** before any disk write — model placeholders (`[NAME]`/`[SSN]`/…
  everywhere) plus a regex backstop over every string (typed core, list rows, catch-all, classifier
  reasoning). Amounts, dates, statuses, form codes, org names, and masked last-4 are kept.
- **Rule engine untouched** — `ACTIVE_RULE_IDS == 37` (asserted in the bench tests).
- **Nothing persisted to the database** — output is JSON/Markdown/CSV on disk under
  `bench_output/<run_id>/` only.

## Notes / follow-ups

- The bench has **not yet been run against a real document corpus** — it is built and verified, but the
  five findings on real paperwork are the point of the exercise and are still to be produced.
- Finding 5 (rule readiness) is intentionally **coarse** (rule-family → needed doc type appeared), not
  the full LP-451 per-rule gate.
- Estimated cost is a guardrail ($0.05/doc midpoint); actual cost is measured per document from real
  token counts.
