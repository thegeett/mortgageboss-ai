# Extraction bench — Bedrock rate-limit safety

Make the extraction bench safe to run as a batch under Bedrock's ~10 requests/min quota, and make sure a
throttle can never masquerade as a coverage finding. Builds on
[`extraction-bench.md`](extraction-bench.md).

## Diagnosis (what was wrong)

1. **`AI_REQUESTS_PER_MINUTE_BEDROCK` was unset** → `resolve_requests_per_minute()` returned `None` →
   `RateLimiter(None)` never waits. The client limiter existed but was doing nothing; a batch run was
   completely unpaced.
2. The limiter **does** gate every `complete()` (both classification and extraction route through it) and
   it counts **requests** — 2 per document — so a cap of 8 requests/min = 4 docs/min. But it is
   **process-local**.
3. The bench loop is **sequential**, so no burst from the loop itself — but sequential is not safe while
   unpaced (fast responses still exceed 10/min).
4. On an exhausted 429, `complete()` raises `AIClientError`, and **both call sites swallow it into a
   generic `"AI call failed"`** (`_attempt` → `None`; classification → `unknown("AI call failed")`),
   losing the fact that it was a throttle. A rate-limited document was **indistinguishable** from a
   genuinely failed one — and, since neither call raises, it landed in the findings as a false schema gap.
5. Arithmetic: at 8 req/min, 200 docs × 2 calls ≈ **50 min** floor (more with retries).

## The fix (four parts)

1. **Set the cap.** `AI_REQUESTS_PER_MINUTE_BEDROCK=8` in `backend/.env` (gitignored; `.env.example`
   already documents `8` for dev+bedrock). Units are **requests** → 4 docs/min under the 10/min ceiling.
2. **Refuse to start unpaced.** `POST /start` now calls `_require_paced()`: if `AI_PROVIDER=bedrock` and
   the request limit is unset, it returns **409** with a fix-it message. A refusal, not a warning — an
   accidental unpaced 200-document run is made impossible.
3. **Tag throttled documents.** `run_one` wraps both model calls in `bench_run_context()`, whose patched
   `complete` inspects the `AIClientError` cause and, if transient (throttle/capacity/5xx/timeout),
   records `rate_limited: true` on the record **before** the sentinel swallows the type. It patches both
   `model_call.complete` (extraction) and `classification.complete`, so a throttle on either call is
   seen. Production is untouched — the wrapper only observes and re-raises.
   - **Findings exclude rate-limited docs** and **count them separately**; `_SUMMARY.md` states the
     rate-limited count on every run (`0` when none) — so a throttle is never read as a coverage gap or a
     network problem.
   - **Consecutive-throttle abort:** 3 throttled documents in a row stop the run
     (`aborted_reason="rate_limited"`) rather than writing more false findings.
4. **Incremental writes + resume.** Each document's JSON is written as it completes, plus an append to
   `_records.jsonl`. `POST /start` with `resume_run_id` reuses the output dir, skips documents already on
   disk, and still aggregates the whole corpus — a 50–90 min run is no longer all-or-nothing.

The preview now also surfaces pacing (requests/min + estimated duration), so a long or unpaced run is
visible before Start.

## ⚠️ Per-process caveat (documented, not fixed)

The client limiter is a **process-local** singleton. The bench paces its own calls correctly, but if
Celery workers are processing documents (separate processes hitting Bedrock) during a bench run, the
limiters don't coordinate and the combined rate can exceed 10/min. Run the bench in isolation, or size
the cap to leave the workers headroom. (A cross-process limiter is a larger change, out of scope here.)

## Files changed

- `backend/.env` — `AI_REQUESTS_PER_MINUTE_BEDROCK=8` (untracked; not committed).
- `backend/app/api/dev_bench.py` — `_require_paced()` refusal; incremental `write_record`;
  consecutive-throttle abort; `resume_run_id`; `rate_limited`/`aborted_reason` in status.
- `backend/app/dev/bench/prompt.py` — `bench_run_context()` (patches both call sites) + throttle
  detection via `CallTally` / `_TALLY` contextvar.
- `backend/app/dev/bench/engine.py` — `run_one` tags `rate_limited`; preview pacing
  (`requests_per_minute`, `estimated_minutes`); `RunProgress.rate_limited`/`aborted_reason`.
- `backend/app/dev/bench/findings.py` — `write_record` / `load_records` (incremental + resume);
  `finalize_output` partitions rate-limited out and reports the count in `_SUMMARY.md`.
- `frontend/lib/api/extraction-bench.ts` + `app/(protected)/dev/extraction-bench/page.tsx` — pacing on
  preview, unpaced-Bedrock warning, rate-limited badge, abort banner, resume button, 409-detail surfacing.
- `backend/tests/dev/test_extraction_bench.py` — 8 new tests (refusal, throttle tagging on transient vs
  non-transient cause, write/load round-trip, findings exclude rate-limited, consecutive-throttle abort).

## Verification

- `ruff` + `mypy app/` clean; **25** bench tests pass (17 + 8 new); frontend `biome` + `tsc` clean.
- No model calls anywhere — every test mocks the model boundary.
