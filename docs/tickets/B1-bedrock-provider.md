# B1 — Bedrock provider for the AI client

**Branch:** `bedrock_integration`
**Depends on:** A2 recon, the `phase3_bucket_2` merge
**Blocks:** C3 (task roles), C5 (staging deploy)

---

## What this does and why

Every model call in the app funnels through `complete()` in `backend/app/ai/client.py`, and the
only place the SDK client is constructed is `client.py:153`. This ticket makes that construction
switchable between the direct Anthropic API and Amazon Bedrock, controlled by one setting, with
**both paths live** so nothing is lost if Bedrock misbehaves.

Staging will hold real borrower files (GLBA-covered NPI). Running that through Bedrock keeps
inference inside the AWS trust boundary under AWS's terms, which is the compliance story the
whole deployment rests on. So this must land before staging, not after.

**The swap itself is one line. The risk is in four things that fail silently** — see Hazards.

## Acceptance criteria

1. `AI_PROVIDER=anthropic` (the default) behaves **exactly** as today. No behavioural change.
2. `AI_PROVIDER=bedrock` routes every model call through Bedrock with no change to any caller.
3. A real Bedrock call records a **non-zero** `cost_estimate` and a correct `model_used`.
4. Bedrock throttling is classified as **transient** and retried.
5. Truncation detection works on Bedrock (`stop_reason` semantics verified, not assumed).
6. Classification and extraction calls have a request timeout.
7. Client-side rate limiting is configurable per provider and applies to every `complete()` call.
8. The LP-457 guard test still passes and is **not** deleted.
9. Full suite green, ruff and mypy clean.
10. The two baseline documents re-extract through Bedrock with results matching the direct-API
    baseline below.

## Verified facts — use these, do not re-derive

Confirmed working in AWS account `591554480818`, `us-east-1`, profile `mbai-dev`, via
`bedrock-runtime converse`:

```
us.anthropic.claude-haiku-4-5-20251001-v1:0      (classification, extraction)
us.anthropic.claude-sonnet-4-5-20250929-v1:0     (reasoning)
```

The bare IDs (`anthropic.claude-haiku-4-5-...`) are **rejected** — on-demand throughput is not
supported for these models, only the `us.` cross-region inference profile.

Current account quotas: **TPM 5,000,000. RPM 10.** RPM is the binding constraint and a request
for 100 is pending. Assume throttling will occur.

Post-merge model tiers (`config.py`): classification `claude-haiku-4-5`, extraction
`claude-haiku-4-5`, reasoning `claude-sonnet-4-5`.

### Direct-API baseline — the comparison target

Measured post-merge on the direct Anthropic API, extraction model `claude-haiku-4-5`:

| | Credit report | Pay stub (Bansari May 1) |
|---|---|---|
| primary list | **18** tradelines | **9** earnings_lines |
| other lists | 0 public_records, 0 inquiries | 6 deduction_lines |
| status | succeeded | succeeded |
| confidence | 0.92 | 0.97 |
| typed core set | 26/29 | 14/17 |
| tokens | in 32,902 / out 7,887 | in 6,104 / out 3,264 |

---

## Tasks

### 1. Dependency

Add the `bedrock` extra to the `anthropic` dependency in `backend/pyproject.toml` (it pulls
`boto3`/`botocore`). Run `uv sync`, commit `uv.lock`.

Note C0 already added `aioboto3`. Check for a botocore version conflict and report it rather
than pinning around it silently.

### 2. Settings — `backend/app/core/config.py`

Add:

| Setting | Type | Default |
|---|---|---|
| `ai_provider` | `Literal["anthropic", "bedrock"]` | `"anthropic"` |
| `bedrock_region` | `str` | `"us-east-1"` |
| `bedrock_model_classification` | `str \| None` | `None` |
| `bedrock_model_extraction` | `str \| None` | `None` |
| `bedrock_model_reasoning` | `str \| None` | `None` |
| `ai_requests_per_minute_anthropic` | `int \| None` | `None` |
| `ai_requests_per_minute_bedrock` | `int \| None` | `None` |

**Why a parallel triplet rather than reusing the existing three settings:** switching providers
must not require hand-editing three values that can silently mismatch — a direct-API model name
sent to Bedrock fails at invoke time, in production, as a validation error. With both triplets
present, a provider flip is one variable.

Add a **model resolver** — a single function returning the right ID for (purpose, provider).
Every model selection must go through it. Do not scatter `if provider == ...` across call sites.

Add a **startup validator**: when `ai_provider == "bedrock"`, all three `bedrock_model_*` must be
set. Fail at boot, not at first call — matching the C0 precedent and the repo convention.

**`anthropic_api_key` must become conditionally required.** It is currently a `Field` with no
default (`config.py:49`), so the app refuses to start without it; `get_anthropic_client` also
hard-fails on a falsy key (`client.py:151-152`). Required for the anthropic provider, **not
required** for bedrock. Do not introduce a dummy-key workaround.

**No AWS credential settings.** Default provider chain only — SSO locally, task role on ECS.

Update `backend/.env.example` with the new keys (keys only).

### 3. Client — `backend/app/ai/client.py`

Change `get_anthropic_client()` at `:142-153` to construct either client based on
`settings.ai_provider`:

- `anthropic` → `AsyncAnthropic(api_key=..., max_retries=0)` — unchanged
- `bedrock` → `AsyncAnthropicBedrock(aws_region=settings.bedrock_region, max_retries=0)`

**Keep `max_retries=0`.** The wrapper is the single retry authority (`client.py:19-20`); letting
the SDK also retry would multiply attempts invisibly.

**Keep the `@lru_cache(maxsize=1)`** — but confirm the Bedrock client is safe to cache across
Celery prefork workers, and that its credential chain refreshes. C0 found `aioboto3` clients are
event-loop-bound and the Celery bridge creates a fresh loop per task
(`app/tasks/base.py:41-43`). **Verify whether `AsyncAnthropicBedrock` has the same constraint.**
If it does, follow C0's precedent — per-operation construction — and say so. If it does not,
say why not. This is the single most likely source of an intermittent, hard-to-reproduce bug.

`complete()`'s response handling (`:234-239`) should be unchanged — the SDK returns the same
shape either way. **Verify, do not assume.**

### 4. Retry classification — the throttling hazard

`_is_transient` at `client.py:156-170` treats `APIStatusError` as transient **only** for 429 or
≥500. Bedrock surfaces throttling as `ThrottlingException` and capacity pressure as
`ModelNotReadyException` / `ServiceUnavailableException`.

**Empirically determine** what the Anthropic SDK's Bedrock client raises for a throttle — its
type, and its `status_code` if it is an `APIStatusError`. At 10 RPM this is easy to reproduce:
fire a burst and observe.

If a throttle does not already classify as transient, extend `_is_transient` so it does. Add a
test pinning the behaviour. **A misclassified throttle fails fast instead of retrying** — at
your current RPM that is not an edge case, it is the common path.

Report what you found. Do not guess from documentation.

### 4b. Client-side rate limiting

At 10 RPM, burst extraction throttles continuously. Retry-after-429 works but wastes quota — a
rejected request still counts against it. Pace **before** sending instead.

**Two settings**, because the providers have very different ceilings:

```python
ai_requests_per_minute_anthropic: int | None = None   # None = unlimited
ai_requests_per_minute_bedrock:   int | None = None
```

Resolve through **one function** that picks by `settings.ai_provider`, alongside the model
resolver from task 2. Apply it in `client.py` to every `complete()` call — no call site should
know a limiter exists.

Async token bucket or simple spacing, whichever fits the codebase style. **Process-local.**

⚠️ **State clearly in the result doc that this is per-process, not global.** Once the worker
scales past one ECS task, the effective rate is N × the setting. The deployed value must
therefore be *the account quota divided by task count*, not the quota itself. Two tasks each
pacing at 8 against a 10 RPM account throttles anyway — and looks like a broken limiter.

Log at **INFO** when a call waits, including the wait duration, so throttling is visible rather
than looking like a hang.

**No environment lookup in code.** Both default to `None`, so unset behaviour is unchanged;
values come from the environment per deployment. Document recommended starting points in
`backend/.env.example` as comments:

```
# dev + bedrock:      8     (account is at 10 RPM; retries count against it too)
# dev + anthropic:    unset (direct API limits are generous)
# staging/production: that account's granted quota ÷ number of worker tasks
```

### 5. Truncation — `stop_reason` semantics

`model_call.py:116` and `:135` compare `stop_reason == "max_tokens"`. If Bedrock returns a
different value, the truncation guard silently stops working and a cut-off response is
misreported as *"could not parse extraction"* — precisely the bug LP-102 exists to prevent.

**Verify empirically**: issue a Bedrock call with a deliberately tiny `max_tokens` and record the
exact `stop_reason` string. Add a test asserting it. If it differs, normalise it in
`client.py` — where the SDK response is already converted to `AICompletion` — rather than
scattering provider checks through `model_call.py`.

### 6. Cost — `backend/app/ai/cost.py`

`PRICING` at `:20-28` is keyed on the exact model string. Bedrock IDs miss every key, and
`estimate_cost` returns **$0.00** with only an `ai_cost_unknown_model` warning (`:43-46`). Every
`Extraction.cost_estimate` would quietly become zero while looking healthy.

1. Add entries for both Bedrock inference-profile IDs.
2. The file carries `TODO(pricing): VERIFY against current Anthropic pricing` (`:15`) — verify
   the existing entries and correct them. Bedrock and direct-API per-token rates are the same.
3. **Add a test that fails when a configured model is missing from `PRICING`.** Read the three
   `bedrock_model_*` and three `anthropic_model_*` settings and assert each resolves to a price.
   A silent zero is worse than a crash here, because it destroys the telemetry you would use to
   detect it.

### 7. Timeouts

`ai_request_timeout_seconds` exists (`config.py:69`) and is applied by five Phase-3 modules via
`asyncio.wait_for`, but **neither classification nor extraction applies it** — they rely on the
SDK default. On Fargate a hung call holds a Celery worker slot indefinitely.

Apply the timeout to both paths. A timeout should surface as `AIClientError` and be treated as
**transient** (it is a network-class failure), so the existing retry loop covers it.

### 8. LP-457 guard test

`tests/ai/test_model_selection_lp457.py` fails CI on any literal `claude-*` string in `app/`
outside the config home. Bedrock IDs contain `claude-`, so this will trip.

**Widen the exemption to cover the config home and the pricing table. Do NOT delete or weaken
the test** — its purpose is that a hard-coded model cannot creep back in, and that purpose is
unchanged. Say exactly what you widened.

### 9. Tests

- `tests/ai/test_client.py` — its `_install_fake_client` monkeypatches `get_anthropic_client`
  (`:70-73`), so it should survive. Verify. Add coverage for provider selection: each value of
  `ai_provider` constructs the right class.
- The existing tests import real SDK exception classes (`test_client.py:18`). Add Bedrock
  throttle classification to that suite so the finding from task 4 is pinned.
- Startup validation: `ai_provider="bedrock"` with a missing `bedrock_model_*` fails; and
  `ai_provider="bedrock"` with **no** `anthropic_api_key` succeeds.
- Rate limiter: `None` imposes no delay; a set value paces calls; the resolver picks the
  per-provider setting correctly. Do not add a test that actually sleeps for a minute — assert
  against an injected clock or the limiter's own accounting.

### 10. Live verification script

`scripts/verify-bedrock.py` — standalone, run by the user (it needs AWS credentials you do not
have). Given a profile and region it must:

1. Issue one `complete()` per tier (classification, extraction, reasoning) and print the model,
   token counts, latency, and `stop_reason`
2. Force a truncation with a tiny `max_tokens` and print the exact `stop_reason`
3. Fire a burst to trigger throttling and print the exception type, class, and status code
4. Print the computed `estimate_cost` for each call and **fail loudly if any is 0.00**

Print each step's outcome, exit non-zero on failure. Verify it imports and `--help` works.

### 11. Document

**`docs/tickets/B1-bedrock-provider-result.md`** must contain:

- **What this ticket is** and why, in two or three sentences
- **Acceptance criteria**, each marked met or not met with evidence
- **What was implemented** — files created and modified, one line each
- **Every assumption and decision made**, with the reasoning. Specifically: the parallel-triplet
  settings shape, the client caching / event-loop decision, how `stop_reason` was handled, and
  what was widened in the LP-457 guard, and the rate limiter's per-process scope limitation
- **Empirical findings** from tasks 4 and 5 — the actual exception type and the actual
  `stop_reason` string, not what the docs say
- **Actual test output**, not "passed"
- The exact commands the user must run for tasks 10 and 12

**`decisions.md`** — append ADRs only for real decisions. The merge renumbered the Bedrock ADRs
to 355–359, so **read the file for the current maximum** and continue from there. Candidates:
the provider flag with both paths live; the parallel model-ID triplet; conditional
`anthropic_api_key`.

### 12. Baseline comparison — do not skip

After the user has run `verify-bedrock.py` successfully, re-extract **the same two documents**
through Bedrock and compare against the table above. Report every field side by side.

**The 18 tradelines is the number that matters.** Fewer means the dense nested case is dropping
rows on Bedrock, which the direct API handled. That is a finding, not something to fix by
adjusting the extractor.

You cannot run this yourself — it needs AWS credentials. Provide the exact command.

---

## Verify

```bash
cd backend
uv sync
uv run pytest                        # full suite, no regressions
uv run ruff check . && uv run mypy app
uv run pytest tests/ai/test_model_selection_lp457.py -v   # must pass, not skip
python scripts/verify-bedrock.py --help
```

Then confirm the default path is untouched:

```bash
grep AI_PROVIDER backend/.env.example      # documented
grep -c "AI_PROVIDER" backend/.env || true # local .env may not have it — default is anthropic
docker compose ps                          # mbai-bedrock-* healthy
```

**With `AI_PROVIDER` unset, behaviour must be byte-identical to today.**

---

## Stop and report — do not work around

- `AsyncAnthropicBedrock` returning a response shape that `complete()` cannot consume unchanged.
- A Bedrock throttle that cannot be classified as transient without weakening the 4xx-fails-fast
  rule for genuine client errors.
- `stop_reason` differing in a way that cannot be normalised in `client.py`.
- Any need to change a `complete()` caller. There are 13 and none should need touching.
- A botocore version conflict between `anthropic[bedrock]` and C0's `aioboto3`.
- The LP-457 guard requiring more than an exemption widening to pass.

## Do not

- `git push`. Commit locally with a clear message; the user pushes manually.
- Create any Alembic migration. `us.anthropic.claude-sonnet-4-5-20250929-v1:0` is 46 characters
  and fits `Extraction.model_used` `varchar(64)` — **verify this** and report the length.
- Change the default `ai_provider` from `"anthropic"`.
- Delete or weaken `tests/ai/test_model_selection_lp457.py`.
- Collapse the three model tiers. 37 rules are calibrated on Sonnet reasoning.
- Add AWS access-key or secret-key settings.
- Modify `app/storage/`, `infra/`, or any Dockerfile.
- Run anything requiring AWS credentials.
