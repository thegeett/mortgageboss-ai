# B1 — Bedrock provider for the AI client — result

**Branch:** `bedrock_integration` · **Date:** 2026-08-04

## What this ticket is

Every model call funnels through `complete()` in `backend/app/ai/client.py`, and the only
SDK client construction is `client.py:153`. B1 makes that construction switchable between
the direct Anthropic API and Amazon Bedrock via one setting, with **both paths live** so
nothing is lost if Bedrock misbehaves. Staging will hold real borrower NPI, and routing
that through Bedrock keeps inference inside the AWS trust boundary — which is why this had
to land before staging rather than after.

**Two findings are EMPIRICAL-PENDING.** Tasks 4 and 5 require live Bedrock calls I cannot
make. The code is implemented against the *expected* behaviour and written so the fix is a
one-line change in one place if the expectation is wrong; `scripts/verify-bedrock.py`
prints both actual values. They are marked **PENDING** throughout and must not be read as
verified.

---

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | `AI_PROVIDER=anthropic` (default) behaves **exactly** as today | ✅ **Met** | Default asserted in code *and* test; `resolve_model` is the identity function under `anthropic`; limiter defaults to unlimited (`None`). Live check with `AI_PROVIDER` unset: provider `anthropic`, all three tiers resolve to their own values, `rpm None`, client `AsyncAnthropic`. Full suite green. |
| 2 | `AI_PROVIDER=bedrock` routes every call through Bedrock, no caller changes | ✅ **Met** | `get_anthropic_client()` returns `AsyncAnthropicBedrock`; `test_complete_sends_the_resolved_bedrock_id` asserts the wire `model` is the profile id. **Zero of the 13 `complete()` callers changed** — `git diff --stat` touches none of them. |
| 3 | A real Bedrock call records non-zero `cost_estimate` and correct `model_used` | ⚠️ **Met in code, unproven live** | Both Bedrock profiles priced; pipeline now records `resolve_model(...)` — the model that *actually ran* — for both `model_used` and the cost key. `test_configured_models_produce_a_non_zero_estimate` passes. Needs a real call (task 10) to be *proven*. |
| 4 | Bedrock throttling classified transient and retried | ⚠️ **Implemented, shape PENDING** | `_is_transient` matches `ThrottlingException` / `ModelNotReadyException` / `ServiceUnavailableException` in type, message **and body**, on top of 429/5xx. Tests pin both directions. The **actual** exception is unverified — see Empirical findings. |
| 5 | Truncation detection works on Bedrock (`stop_reason` verified, not assumed) | ❌ **NOT met — PENDING** | Cannot be met without a live call. Normalisation boundary + shared constant are in place so the fix is one map entry; verify script step 2 prints the exact string. |
| 6 | Classification and extraction calls have a request timeout | ✅ **Met** | `asyncio.wait_for(..., timeout=settings.ai_request_timeout_seconds)` wraps every attempt inside `complete()`, so both paths (and the other 11 callers) are covered. `TimeoutError` classified transient → retried. |
| 7 | Client-side rate limiting configurable per provider, applied to every call | ✅ **Met** | `app/ai/rate_limit.py`; `resolve_requests_per_minute()` picks by provider; `limiter.acquire()` runs per **attempt** in `complete()`. 8 limiter tests, none sleeping in real time. |
| 8 | LP-457 guard still passes and is **not** deleted | ✅ **Met** | `tests/ai/test_model_selection_lp457.py` **unmodified** (`git status` shows it untouched) and passing. **Nothing was widened** — see below. |
| 9 | Full suite green; ruff and mypy clean | ✅ **Met** | `4001 passed, 5 skipped, 1 xfailed`. `ruff check` + `ruff format --check` clean (854 files). `mypy app` clean (394 files). |
| 10 | The two baseline documents re-extract through Bedrock matching the baseline | ❌ **NOT met — needs AWS credentials** | Task 12; exact command below. |

---

## What was implemented

| File | Change |
|---|---|
| `backend/pyproject.toml` | **Modified** — `anthropic` → `anthropic[bedrock]` |
| `backend/uv.lock` | **Modified** — records the extra; **no package version changed** |
| `backend/app/core/config.py` | **Modified** — 7 settings, `resolve_model()`, `resolve_requests_per_minute()`, `ModelResolutionError`, a blank-string normalizer, and a provider-credential model validator; `anthropic_api_key` → conditionally required |
| `backend/app/ai/client.py` | **Modified** — provider-based construction, throttle classification, per-attempt timeout + pacing, `stop_reason` normalisation, `TRUNCATED_STOP_REASON` |
| `backend/app/ai/rate_limit.py` | **Created** — process-local spacing limiter with injectable clock |
| `backend/app/ai/cost.py` | **Modified** — Bedrock profile pricing; **corrected a wrong Opus 4.8 rate** |
| `backend/app/ai/extraction/model_call.py` | **Modified** — truncation compares the shared constant, not a literal |
| `backend/app/tasks/document_processing.py` | **Modified** — records the model that actually ran, for `model_used` and cost |
| `backend/.env.example` | **Modified** — 7 keys, verified profile ids and RPM guidance as comments |
| `backend/tests/ai/test_provider_selection_b1.py` | **Created** — 40 tests |
| `backend/scripts/verify-bedrock.py` | **Created** (`chmod +x`) — live 4-step verification |
| `decisions.md` | **Modified** — ADR-360, ADR-361 (max was ADR-359) |

**Not modified:** `app/storage/`, `scripts/verify-s3.py`, any Dockerfile, `infra/` (does not exist).
No Alembic revision. `STORAGE_BACKEND` still `local`. Default `ai_provider` still `"anthropic"`.
**None of the 13 `complete()` callers** — the Stop-and-report condition did not fire.

### Dependency — no botocore conflict

```
Resolved 117 packages … Prepared 1 package
aioboto3 15.5.0 · aiobotocore 2.25.1 · anthropic 0.109.1 · boto3 1.40.61 · botocore 1.40.61
```

Byte-identical before and after: C0's `aioboto3` had already pulled boto3/botocore 1.40.61, which
satisfies `anthropic[bedrock]` too. Only the project's own editable install was rebuilt.
**`AsyncAnthropicBedrock` was already importable** from the installed SDK — the extra changes the
declared dependency, not the resolved set.

### `Extraction.model_used` width — verified

| id | length |
|---|---|
| `us.anthropic.claude-haiku-4-5-20251001-v1:0` | **43** |
| `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | **44** |

`model_used` is `String(SHORT_STRING)` = **varchar(64)** (`models/extraction.py:130`,
`models/types.py:28`). 44 < 64 — fits, no migration. Confirmed rather than assumed, because this is
exactly the class of error that only appears once real data flows.

---

## Empirical findings

### ✅ VERIFIED — client lifecycle and credential refresh

The ticket flagged this as "the single most likely source of an intermittent, hard-to-reproduce
bug", so it was measured, not reasoned about.

**Both clients use the same transport.** `AsyncAnthropic._client` and
`AsyncAnthropicBedrock._client` are both `AsyncHttpxClientWrapper`, created eagerly in `__init__`.
`AsyncAnthropicBedrock` is *not* a subclass of `AsyncAnthropic` (MRO:
`AsyncAnthropicBedrock → BaseBedrockClient → AsyncAPIClient → BaseClient`) but shares the HTTP layer.

**Reuse across event loops works, including pooled connections.** C0 found `aioboto3` clients are
event-loop-bound while `run_async` is `asyncio.run` — a fresh loop per Celery task. First test
(client reused across three `asyncio.run()` loops against a dead port) returned `APIConnectionError`
each time — but that fails at *connect*, so nothing was ever pooled. Ran a stricter one against a
real local HTTP server:

```
SUCCESSFUL requests, pooled connection, reused across loops:
   loop1:200
   loop2:200
   loop3:200
```

httpx re-establishes a connection whose loop has gone rather than raising. **This is not the
aioboto3 situation, and Bedrock adds no constraint the direct client did not already have** under
the same `@lru_cache`.

**Credentials refresh.** `AsyncAnthropicBedrock` signs **per request** —
`_get_signed_headers` is called from `_prepare_request` — using an `@lru_cache`d **`boto3.Session`**
(not frozen credentials). A Session resolves through the provider chain and refreshes, so a rotating
ECS task role works and a cached client does not pin expiring credentials.

**Decision: keep `@lru_cache(maxsize=1)` for both.** C0's per-operation precedent does **not**
apply — its cause (aiohttp connector loop-binding) is absent here. Tests flipping `ai_provider` must
call `get_anthropic_client.cache_clear()`; the fixture does.

**Response shape unchanged** — `complete()`'s handling at `:334-339` needed no edit. Both clients
return `.content[].text`, `.usage.input_tokens/.output_tokens`, `.stop_reason`.

### ⚠️ PENDING — task 4: the actual throttle exception

**Not determined. Requires live calls.** `_is_transient` is implemented to be correct either way —
it matches the three Bedrock codes in the exception type name, message, **and response body**, on
top of the existing 429/5xx rule. Body inspection was added after a test proved message-only
matching missed a throttle surfaced as a 400 with the code in the body.

`verify-bedrock.py` step 3 fires a burst and prints the exception's module, class, `status_code`,
body, and whether `_is_transient` accepts it — failing loudly if it does not. **Record the result
here.**

### ⚠️ PENDING — task 5: the actual `stop_reason` on truncation

**Not determined. Requires a live call.** Acceptance criterion 5 is therefore **not met**.

Handled structurally: `model_call.py` now compares `TRUNCATED_STOP_REASON` (a test asserts it never
carries its own literal again), and normalisation happens in `client.py` where the SDK response
becomes an `AICompletion`. **`_STOP_REASON_ALIASES` is deliberately empty** — the Bedrock client
returns the Messages API shape so `"max_tokens"` is *expected*, and inventing a speculative alias
would be a guess dressed as a fix. Verify step 2 forces a truncation with `max_tokens=16` and prints
the exact string; if it differs, add one entry to that map and nothing else.

### ✅ VERIFIED — a pre-existing pricing error

Task 6 asked me to verify the existing `PRICING` entries. **One was wrong:**

| Model | Was | Correct | Effect |
|---|---|---|---|
| `claude-haiku-4-5` | $1.00 / $5.00 | $1.00 / $5.00 | ✅ correct |
| `claude-sonnet-4-5` | $3.00 / $15.00 | $3.00 / $15.00 | ✅ correct |
| **`claude-opus-4-8`** | **$15.00 / $75.00** | **$5.00 / $25.00** | ❌ **3× overstated** |

Every Opus-tier `cost_estimate` recorded before 2026-08-04 is **overstated threefold**. Not a
Bedrock issue — it was already wrong. The stale `TODO(pricing)` marker is removed and replaced with
a dated verification note.

**Unresolved, and flagged rather than assumed:** the ticket states "Bedrock and direct-API per-token
rates are the same." Anthropic's own documentation describes Bedrock as **partner-operated with
separately published pricing** (AWS's page). I used the ticket's premise — the Bedrock rows mirror
the direct rates, with a test pinning that — but recorded the disagreement in `cost.py` and here.
**Reconcile against the AWS Bedrock pricing page and the first invoice before treating Bedrock
`cost_estimate` as authoritative.**

---

## Decisions and assumptions

**The parallel triplet.** `bedrock_model_*` sits alongside `anthropic_model_*` rather than one
triplet holding whichever vocabulary is active, so a provider flip is one variable. A shared triplet
would need three hand-edits, and a wrong one fails at **invoke time in production**, per call, as a
validation error — not at boot.

**The resolver is keyed on the caller's VALUE, not a `purpose` argument.** Callers keep passing
`settings.anthropic_model_*` — the setting they read *is* their tier — and `resolve_model()` maps
that value to the same tier's Bedrock id. A `purpose` parameter on `complete()` would have meant
editing all 13 call sites, which the ticket lists as a Stop-and-report condition. **The cost:**
classification and extraction hold the same value today, so they collapse to one map key — harmless
while their Bedrock ids match, a silent mis-route the moment they diverge. The startup validator
**refuses** that configuration rather than resolving it by dict order.

**No Bedrock model identifiers invented.** Per the correction, B1 does not ship any: the three
`bedrock_model_*` settings default to `None` and the app refuses to start under `bedrock` without
them. The verified profile ids appear only as `.env.example` comments and `PRICING` keys.

**Client caching kept** — see the verified finding above. The C0 per-operation precedent does not
transfer because its cause is absent.

**`stop_reason` normalised at one boundary, alias map empty** — see PENDING above.

**Timeouts and pacing are per ATTEMPT, not per call.** A retry is a fresh request that counts
against quota exactly as the first did, and a hung attempt would otherwise hold a Celery worker slot
indefinitely. `TimeoutError` is classified transient so the existing loop covers it.

### ⚠️ The rate limiter is PROCESS-LOCAL

**N worker tasks pace at N × the setting.** The deployed value must be *the account quota divided by
task count*, **never the quota itself** — two tasks each pacing at 8 against a 10 RPM account still
throttle, and it looks like a broken limiter. Documented in the module, in `.env.example`, and in
ADR-361. Recommended starting points:

```
dev + bedrock:      8      (account is at 10 RPM; rejected requests count too)
dev + anthropic:    unset  (direct API limits are generous)
staging/production: granted quota / number of worker tasks
```

A shared limiter would need Redis coordination on the hot path of every model call — a heavier
decision, not made here. Waits log at INFO (`ai_rate_limit_wait`) so pacing looks like pacing, not a
hang.

**Spacing, not a token bucket:** a bucket permits a burst then stalls, which is exactly the shape
that trips a per-minute server-side quota.

### The LP-457 guard: NOTHING was widened

The ticket predicted the guard would trip because "Bedrock IDs contain `claude-`". **It does not,
and I widened nothing** — the test file is byte-unchanged.

Two independent reasons:

1. **The regex does not match.** It is `["']claude-(?:haiku|sonnet|opus|fable)-` — a quote
   *immediately* followed by `claude-`. A Bedrock id is `"us.anthropic.claude-haiku-…"`, where the
   quote is followed by `us.`. No match.
2. **Both files are already exempt anyway.** The ids appear only in `core/config.py` and `ai/cost.py`,
   both in `_ALLOWED`. `scripts/` is outside the scanned tree (`_APP` is the `app` dir).

Widening an exemption that nothing needs would have weakened the guard for no reason. `3 passed`.

---

## Actual test output

```
$ uv run pytest tests/ai/test_provider_selection_b1.py tests/ai/test_client.py \
                tests/ai/test_cost.py tests/ai/test_model_selection_lp457.py -q
72 passed in 0.19s

$ uv run pytest -q
4001 passed, 5 skipped, 1 xfailed, 2 warnings in 224.61s (0:03:44)

$ uv run ruff check .          → All checks passed!
$ uv run ruff format --check . → 854 files already formatted
$ uv run mypy app              → Success: no issues found in 394 source files

$ uv run python scripts/verify-bedrock.py --help   → EXIT=0
$ uv run python scripts/verify-bedrock.py          → [ FAIL ] provider — AI_PROVIDER is
  "anthropic", not "bedrock" … (refuses to run against the wrong provider)
```

Three of my own tests failed on first run; all three are recorded because two were my errors and one
was a real gap:

1. **A real gap** — a throttle surfaced as a 400 with the code in the *body* was classified
   non-transient, because the matcher only read the type name and `str(exc)`. Fixed by also
   inspecting `exc.body`.
2. **Test bug** — the "no literal `max_tokens`" assertion scanned the whole file and hit the module
   *docstring*, which legitimately quotes the literal while explaining LP-102. Narrowed to code lines.
3. **Test bug, not a limiter bug** — I asserted a cumulative backlog (0/10/20/30s). Each waiter
   correctly waits *one* interval; the fake clock advances as each sleeps. The resulting schedule
   (four calls at t=0/10/20/30) is right. Assertion corrected and the reasoning written into the test.

### Default path untouched

```
$ grep AI_PROVIDER backend/.env.example   → AI_PROVIDER=anthropic
$ grep -c AI_PROVIDER backend/.env        → 0  (unset — default applies)

provider      : anthropic
classification: claude-haiku-4-5      (identity — no translation)
extraction    : claude-haiku-4-5
reasoning     : claude-sonnet-4-5
rpm           : None                  (unlimited)
client        : AsyncAnthropic

$ docker compose ps
mbai-bedrock-postgres  Up 4 days (healthy)
mbai-bedrock-redis     Up 26 hours (healthy)
mbai-bedrock-worker    Up 2 hours (healthy)
```

---

## Commands you must run

### Task 10 — live Bedrock verification

Needs AWS credentials I do not have. **Run this before anything depends on the Bedrock path.**

```bash
cd backend

export AI_PROVIDER=bedrock
export BEDROCK_REGION=us-east-1
export BEDROCK_MODEL_CLASSIFICATION=us.anthropic.claude-haiku-4-5-20251001-v1:0
export BEDROCK_MODEL_EXTRACTION=us.anthropic.claude-haiku-4-5-20251001-v1:0
export BEDROCK_MODEL_REASONING=us.anthropic.claude-sonnet-4-5-20250929-v1:0
export AI_REQUESTS_PER_MINUTE_BEDROCK=8      # account is at 10 RPM

AWS_PROFILE=mbai-dev uv run python scripts/verify-bedrock.py --region us-east-1

# To skip the burst that deliberately consumes quota (leaves finding 4 PENDING):
AWS_PROFILE=mbai-dev uv run python scripts/verify-bedrock.py --skip-throttle
```

It prints one line per step and exits non-zero on the first failure. On success it prints the two
PENDING findings in a form you can paste into this document:

```
  stop_reason: 'max_tokens'
  throttle: anthropic.RateLimitError status=429 transient=True
```

**Then reconcile:** if `stop_reason` differs, add one entry to `_STOP_REASON_ALIASES` in
`app/ai/client.py`. If the throttle is classified non-transient, extend `_BEDROCK_TRANSIENT_CODES`.
Update the two PENDING sections above and mark criteria 4 and 5.

IAM needed: `bedrock:InvokeModel` on both inference profiles. Per
`docs/bedrock-call-sites.md`, the **worker** task role needs this; the **api** role does not.

### Task 12 — baseline comparison

Only after `verify-bedrock.py` passes. Same two documents, same selection method as the direct-API
baseline (the pay stub was chosen by counting earnings rows in the PDF **text layer**, not by stored
row count — a previous test picked a 3-line stub that way):

```bash
cd backend
# same six exports as above
AWS_PROFILE=mbai-dev uv run python - <<'PY'
import asyncio, pathlib
from app.ai.extraction import EXTRACTORS
from app.core.config import settings, resolve_model

CREDIT = pathlib.Path("../../mortgageboss-ai/backend/storage/613828ff-c542-4766-a9bc-22b0c8f30866/04baf1ef-4f63-436b-9b15-cf47fe0779ec/6dd9f569-a895-4bdc-8eb3-2ee7be197b68.pdf")
STUB   = pathlib.Path("storage/613828ff-c542-4766-a9bc-22b0c8f30866/3908a20d-4cfc-45e4-a5c6-07ce9b88b8d4/bf527cc5-ca20-4601-8640-966176916253.pdf")

async def run(label, doc_type, path, list_field):
    res = await EXTRACTORS[doc_type](path.read_bytes(), "application/pdf")
    data = res.data.model_dump(mode="json")
    print(f"{label}: model={resolve_model(settings.anthropic_model_extraction)} "
          f"status={res.status} confidence={res.confidence} "
          f"{list_field}={len(data.get(list_field) or [])} "
          f"tokens in={res.input_tokens} out={res.output_tokens}")
    for other in ("public_records", "inquiries", "deduction_lines"):
        if other in data:
            print(f"    {other}: {len(data.get(other) or [])}")

async def main():
    await run("CREDIT REPORT", "credit_report", CREDIT, "tradelines")
    await run("PAY STUB",      "pay_stub",      STUB,   "earnings_lines")

asyncio.run(main())
PY
```

Compare against the direct-API baseline:

| | Credit report | Pay stub |
|---|---|---|
| primary list | **18** tradelines | **9** earnings_lines |
| other lists | 0 public_records, 0 inquiries | 6 deduction_lines |
| status | succeeded | succeeded |
| confidence | 0.92 | 0.97 |
| tokens | in 32,902 / out 7,887 | in 6,104 / out 3,264 |

⚠️ **18 tradelines is the number that matters.** Fewer means the dense nested case is dropping rows
on Bedrock where the direct API handled it. **That is a finding to report, not something to fix by
adjusting the extractor.**

---

## Decisions recorded

`decisions.md` max was **ADR-359** (C1). Appended:

- **ADR-360** — both paths live behind one flag; the parallel triplet and why value-keyed resolution;
  conditional `anthropic_api_key`; no AWS credential settings.
- **ADR-361** — the runtime half: `max_retries=0` kept, throttles classified by code, per-attempt
  timeout and pacing, one-boundary `stop_reason` normalisation, the pricing correction, and the
  measured client-lifecycle finding.

## Not done, and why

- **Tasks 10 and 12 not executed** — need AWS credentials; commands above.
- **Criteria 4 and 5 not verified** — the two PENDING findings.
- **Bedrock pricing not independently confirmed** — flagged above and in `cost.py`.
- **No Alembic migration** — the longest id is 44 chars against `varchar(64)`.
- **Default `ai_provider` unchanged**, LP-457 guard untouched, three tiers not collapsed, no AWS key
  settings, `app/storage/` and the Dockerfiles untouched, nothing pushed.
- **The `AnthropicBedrockMantle` client not used.** The SDK now offers it as the preferred Bedrock
  path for new code, but it takes `anthropic.`-prefixed ids — a *different* scheme from the `us.`
  inference profiles this account verified. Switching would invalidate the ticket's verified ids.
  Worth a later evaluation; out of scope here.
