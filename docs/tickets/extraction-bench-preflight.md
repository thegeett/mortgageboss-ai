# Extraction bench — preflight, fail-fast, and output naming

Three operational fixes after a run produced **246 × "AI call failed", $0 spent** — the AWS SSO session
had expired and the backend never saw it, yet the bench marched through all 246 writing empty records and
wrote a summary that read like a coverage result. Builds on [`extraction-bench.md`](extraction-bench.md).

## 1. Credentials must not depend on the shell that started the server

**Root cause.** The app reads `.env` via pydantic-settings into the `Settings` object, **not** into
`os.environ` (there is no `load_dotenv`). `AsyncAnthropicBedrock` (`app/ai/client.py`) is built with no
profile — it reads `AWS_PROFILE` from the process **environment**. There is no `[default]` AWS profile.
So a local `uv run` backend inherited **no profile → no credentials**, regardless of what Geet had
exported in his own terminal (a different process).

**Fix.**
- `AWS_PROFILE=mbai-dev` added to `backend/.env` (+ documented in `.env.example`), and a new
  `settings.aws_profile` field reads it.
- The bench **preflight** exports `settings.aws_profile` into `os.environ` when the launching shell
  provided none, then rebuilds the client — so the backend does not depend on that shell. (Docker already
  injects `AWS_PROFILE` and mounts `~/.aws` via `docker-compose.override.yml`, so docker was unaffected;
  this fixes the local `uv run` path.)

**Preflight (refuse-if-unreachable).** `POST /start` now makes **one minimal live call** before
processing anything (`app/dev/bench/engine.py::preflight`, mirroring `scripts/verify-bedrock.py` step 1).
If it fails it returns **409 with the real cause attached** (e.g. `NoCredentialsError`,
`ExpiredTokenException`) instead of processing the corpus into `"AI call failed"` records. Under Bedrock
the preflight also clears the cached client so it re-reads current credentials.

### Does the backend pick up a refreshed SSO session without a restart?

**For the bench: no restart needed.** `get_anthropic_client` is `lru_cache`d, but the preflight calls
`get_anthropic_client.cache_clear()` on every `/start` under Bedrock, so the client is **rebuilt each
run** and re-reads the current SSO token from `~/.aws/sso/cache`. After `aws sso login`, just press Start
again — the preflight proves creds resolve (and refuses with the real error if they still don't).

**For other Bedrock traffic (Celery / normal document processing): a restart is the safe bet.** Those
paths keep the cached client for the life of the process. botocore resolves credentials per request and
generally re-reads a refreshed SSO token, but a process that **started with no profile/credentials** will
not gain them without either the env fix above or a restart. So: after `aws sso login`, the bench works
immediately; if normal processing was also failing, restart the backend.

**Operational gotcha, stated plainly:** the backend is a **separate process** from your terminal.
`export AWS_PROFILE=… && aws sso login` in your shell does **not** reach it. Put `AWS_PROFILE` in `.env`
(now done) and keep the SSO session live; the preflight is the source of truth for whether it worked.

## 2. Abort on consecutive failures — distinguish auth vs throttle

**Before:** only *throttles* aborted (after 3), and only throttles were tagged. A 100% **auth** failure
was neither tagged nor aborted — so it ran to 246.

**Now:**
- The bench wrapper tags **every** `AIClientError` on a document: `ai_failed: true` always, plus
  `rate_limited: true` only when the cause is transient (throttle/capacity/5xx/timeout), plus the cause
  type (`failure_error_type`). So a non-transient auth failure is `ai_failed: true, rate_limited: false`
  — the auth-vs-throttle distinction the report needs.
- After **5 consecutive failures** (throttle **or** auth **or** error) the run aborts with
  `aborted_reason` = `rate_limited` or `ai_error` and the cause type. This is the generalisation of the
  throttle-abort; the 246-run would now stop at 5.
- **A run where nothing succeeded is marked FAILED.** `finalize_output` partitions **all** infrastructure
  failures out of every finding and, if 0 documents succeeded, `_SUMMARY.md` opens with
  `# ⚠️ RUN FAILED — 0 of N documents produced a result`, naming the cause. It can never again read like
  a coverage result (the last one said *"246 documents, types: 1"*). Failure counts (rate-limited /
  auth-or-other / errored, with the top cause) are reported on every run.

## 3. Output naming and layout

- **Source extension stripped** before `.json`: `foo.pdf` → `<n>-foo.json` (was `foo.pdf.json`, which
  file browsers tried to open as a PDF).
- **Per-type folder layout confirmed on a real run** (see below): documents land under their classified
  type slug, not `unknown/`. `unknown/` remains only for genuinely unclassifiable documents.

## Verify — proven on a real 5-document smoke run

Unit tests (mocked, no spend) cover: preflight raises/refuses when unreachable; auth failures tagged
distinctly from throttles; abort after 5 consecutive throttles **and** after 5 consecutive auth failures
(with cause); FAILED summary when nothing succeeds; single-extension filenames. **32 bench tests pass**;
`ruff` + `mypy app/` clean; 1441 targeted tests green under `AI_PROVIDER=anthropic`.

Then a **live smoke run** (Bedrock, paced 8/min) over the real corpus — 4 documents (all that were
present), every one a success:

| file | classified | conf | in/out tokens | cost |
|---|---|---|---|---|
| 219-glen-clova-dr-27603.pdf | `property_profile_subject` | 0.95 | 22960 / 3688 | $0.0414 |
| Bank Statements AmexDec25.pdf | `bank_statement` | 0.95 | 6990 / 3332 | $0.0237 |
| Bank Statements AmexNov25.pdf | `bank_statement` | 0.95 | 6864 / 2833 | $0.0210 |
| Homeowner's Insurance …pdf | `homeowners_insurance` | 0.95 | 15682 / 4848 | $0.0399 |

- preflight passed (real Bedrock reachable + authenticated);
- **real classification** (three distinct types at 0.95 — not `unknown`), **real extraction with real
  tokens/cost**;
- folders `bank_statement/`, `homeowners_insurance/`, `property_profile_subject/` — **not** `unknown/`;
- filenames single-extension (`1-Bank_Statements_AmexDec25.json`); zero double-extension names;
- `finalize`: usable 4, 0 failures, not marked FAILED.

The full 246-document corpus was **not** run — per the ticket, only the 5-doc (here 4, all available)
smoke test, which passed.
