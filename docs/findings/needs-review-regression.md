# LF-GH6Q — every upload since 20:47 UTC lands at confidence 0 / needs_review

**Investigated:** 2026-08-04, ~21:10 UTC · **DB:** `mbai-bedrock-postgres` (5433), read-only
**Loan file:** `LF-GH6Q` = `7ac2bcc1-6e95-4137-bbd6-6d04a1b8629d`

Diagnosis only — no fixes proposed or applied. Nothing was modified: no code, no config,
no DB row, no container restarted. Claims are labelled **DATA** (observed) or
**INFERENCE** (reasoned from it).

---

## Verdict

**Single root cause, unambiguous: the AWS SSO access token expired at
`2026-08-04T20:38:20Z`.** Every Bedrock call since then fails at credential resolution,
inside the process, before any request is sent.

**This is an ENVIRONMENT problem, not a code problem.** The B1 provider flag is not
implicated — I checked it specifically rather than assuming, and the evidence exonerates
it (§ "Was it the provider switching?" below).

The token expiry falls **between the last Bedrock success and the first failure**:

```
20:32:34   last successful Bedrock extraction      ← token still valid
20:38:20   ██ SSO ACCESS TOKEN EXPIRES ██
20:37–20:43 four successes on the DIRECT API       ← Bedrock unused, expiry irrelevant
20:47:18   first failure, back on Bedrock          ← token already 9 min expired
```

---

## 1. The exact exception — DATA, verbatim

Every failure since 20:47 is identical in kind. All `ai_call_failed` /
`classification_ai_failed` lines from `docker compose logs worker --since 45m`:

```
[2026-08-04 20:47:18,773: WARNING/ForkPoolWorker-4] ai_call_failed  attempt=1 error_type=TokenRetrievalError latency_ms=196 max_attempts=3 model=claude-haiku-4-5 transient=False
[2026-08-04 20:47:18,773: WARNING/ForkPoolWorker-4] classification_ai_failed
[2026-08-04 20:47:18,774: WARNING/ForkPoolWorker-2] ai_call_failed  attempt=1 error_type=TokenRetrievalError latency_ms=197 max_attempts=3 model=claude-haiku-4-5 transient=False
[2026-08-04 20:47:18,774: WARNING/ForkPoolWorker-2] classification_ai_failed
[2026-08-04 20:47:59,758: WARNING/ForkPoolWorker-4] ai_call_failed  attempt=1 error_type=TokenRetrievalError latency_ms=44  max_attempts=3 model=claude-haiku-4-5 transient=False
[2026-08-04 20:47:59,758: WARNING/ForkPoolWorker-4] classification_ai_failed
[2026-08-04 20:47:59,759: WARNING/ForkPoolWorker-2] ai_call_failed  attempt=1 error_type=TokenRetrievalError latency_ms=40  max_attempts=3 model=claude-haiku-4-5 transient=False
[2026-08-04 20:47:59,759: WARNING/ForkPoolWorker-2] classification_ai_failed
[2026-08-04 20:55:46,237: WARNING/ForkPoolWorker-4] ai_call_failed  attempt=1 error_type=TokenRetrievalError latency_ms=135 max_attempts=3 model=claude-haiku-4-5 transient=False
[2026-08-04 20:55:46,237: WARNING/ForkPoolWorker-4] classification_ai_failed
```

| Field | Value | Reading |
|---|---|---|
| `error_type` | **`TokenRetrievalError`** | `botocore.exceptions.TokenRetrievalError` — the SSO **token** could not be retrieved or refreshed. Not an Anthropic SDK error; not HTTP. |
| `transient` | **`False`** | Correctly non-transient. Fails fast at attempt 1 of 3 — retrying an expired token achieves nothing. |
| `latency_ms` | **40, 44, 135, 196, 197** | **Sub-200 ms, three under 140 ms.** The request never left the process. Consistent with failing during credential resolution in `_prepare_request`. |
| `attempt` | **1** of `max_attempts=3` | No retry, by design. |
| `model` | `claude-haiku-4-5` | ⚠️ **Misleading — ignore for provider identification.** See § "A misleading log field". |

**Zero `ai_rate_limit_wait` lines** — DATA. Consistent: pacing runs *before* the call, and
the very first acquisition never waits.

### How that produces confidence 0 / needs_review — INFERENCE (code path is unambiguous)

`complete()` raises `AIClientError` → `classify_document` catches it, logs
`classification_ai_failed`, returns `ClassificationResult.unknown("AI call failed")` =
`document_type="unknown", confidence=0.0`. The pipeline writes that, then the gate
`0.0 < 0.5` routes to `NEEDS_REVIEW` and **returns before tier routing** — which is why
no extraction row is ever created. Your reading of the hardcoded `0` is exactly right.

---

## 2. What the container has right now — DATA

```
AI_PROVIDER=bedrock
AWS_PROFILE=mbai-dev
BEDROCK_REGION=us-east-1
BEDROCK_MODEL_CLASSIFICATION=us.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_MODEL_EXTRACTION=us.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_MODEL_REASONING=us.anthropic.claude-sonnet-4-5-20250929-v1:0
ANTHROPIC_MODEL_{CLASSIFICATION,EXTRACTION}=claude-haiku-4-5
ANTHROPIC_MODEL_REASONING=claude-sonnet-4-5
ANTHROPIC_API_KEY=<redacted>
```

**Did the `~/.aws` mount survive? YES.**

```
/Users/geetthaker/.aws  ->  /root/.aws  (read-only)
/…/backend/storage      ->  /app/storage
```

```
/root/.aws:         config (561 B), cli/, sso/
/root/.aws/sso/cache:  4 files — 2 TOKEN, 2 REGISTRATION
```

**Does `AI_PROVIDER` match `backend/.env`? YES.**

| Source | Value |
|---|---|
| `backend/.env` | `AI_PROVIDER=bedrock` |
| worker container env | `AI_PROVIDER=bedrock` |

**So: config is present, correct, and consistent. The mount survived. Neither is the fault.**

---

## 3. Was the container recreated after the last `.env` edit? — DATA: YES

```
backend/.env mtime : 2026-08-04T20:40:28Z
container Created  : 2026-08-04T20:46:05Z   ← 5m37s AFTER the edit
container StartedAt: 2026-08-04T20:46:09Z
```

The container **postdates** the edit, so it is **not** running stale config — corroborated
independently by §2, where the live container env already matches `.env`.

**The stale-config hypothesis is ruled out.** (The `restart` vs `up -d` distinction you
raised is real and would have explained a mismatch — there just isn't one here.)

Note the first failures at 20:47:18 came ~69 s after this container started, i.e. the
container was freshly created *with correct Bedrock config* and failed immediately.

---

## 4. The SSO token — DATA, and this is the root cause

`~/.aws/sso/cache`, read without triggering a refresh (`now = 2026-08-04T21:10:10Z`):

| Cache entry | Kind | `expiresAt` | Status |
|---|---|---|---|
| `2f16ad3b0a19…` | **TOKEN** (active) | **`2026-08-04T20:38:20Z`** | **EXPIRED −0.53 h** |
| `933e1a104ff4…` | TOKEN (older) | `2026-08-04T13:42:46Z` | EXPIRED −7.46 h |
| `81addf2bb1f4…` | REGISTRATION | `2026-11-01T02:41:44Z` | valid +2117 h |
| `bc79f9085d2a…` | REGISTRATION | `2026-11-01T03:00:54Z` | valid +2117 h |

**The client *registration* is valid for months; the *access token* is what expired.**
That distinction matters — it is why nothing looks obviously broken on inspection.

The token does carry a `refreshToken`, and the profile uses the **modern** format
(`[sso-session mbai-dev]` with `sso_registration_scopes`), so refresh is structurally
supported. **INFERENCE:** the refresh is nonetheless failing — that is precisely what
`TokenRetrievalError` reports. The most likely reason is that an IAM Identity Center
refresh token is bound to the same SSO **session** as the access token, so when the
session ends both expire together and re-authentication is required. A **contributing
factor**: `~/.aws` is mounted **read-only**, so even a successful refresh could not be
written back to the cache — the container can never self-heal a token, and every call
re-attempts and re-fails.

### On your stated login time — DATA vs INFERENCE

You ran `aws sso login` at ~16:18 UTC; the token expires at 20:38:20 UTC — a lifetime of
about **4 h 20 m**, not the AWS default 8 h. **DATA** is the expiry timestamp. **INFERENCE:**
either the IAM Identity Center session duration is configured to ~4 h, or the login was
slightly earlier than recalled. Either way the expiry itself is measured, not derived, and
the causal chain does not depend on resolving this. Worth knowing because it sets how often
re-authentication is actually needed.

### A live-credential check that lies — DATA, worth knowing

```
$ docker exec mbai-bedrock-worker python -c "boto3.Session().get_credentials()"
creds: OK    method: sso    expiry: None
```

**This reports OK while every real call fails.** `get_credentials()` returns a *deferred*
resolver — it finds an SSO provider but does not fetch. Only `get_frozen_credentials()`
forces resolution and would raise. **I deliberately did not call it**: a refresh that
happened to succeed would rewrite the SSO cache and silently repair the environment
mid-investigation, destroying the evidence you asked me to gather. Flagging it because a
shallow "are credentials OK?" check here returns a false green.

---

## 5. The other worker — DATA: ruled out, it is gone

```
$ docker ps --format '{{.Names}}' | sort
mbai-bedrock-postgres
mbai-bedrock-redis
mbai-bedrock-worker
mortgageboss-mailhog
mortgageboss-postgres
mortgageboss-redis
mortgageboss-worker
```

`mbai-images-worker` is **no longer running** — the C1 rehearsal stack has been torn down.

```
$ celery inspect ping  →  celery@565429803f2e: OK   ·   1 node online.
```

**One node on this broker.** (`mortgageboss-worker` belongs to the *other* worktree's stack
on port 5432 with its own Redis — not this broker.)

**INFERENCE:** with a single consumer there is no round-robin, so all five failures ran on
the same worker with the same cause. This is one uniform failure mode, not a mixture — and
it is a genuine change from the earlier LF-GH6Q investigation, where task-stealing produced
two different causes.

---

## 6. Do the API and the worker disagree? — DATA: no

| | provider | client | resolved extraction model |
|---|---|---|---|
| **host** (uvicorn reads `backend/.env`) | `bedrock` | `AsyncAnthropicBedrock` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| **worker** (env_file at creation) | `bedrock` | — | `us.anthropic.…` (env confirms the ids) |

Both are on Bedrock. **No disagreement**, and both read the *same* SSO cache — the host's
`~/.aws` is the bind-mount source. The host's own token is the same expired one:

```
2f16ad3b0a19… expiresAt=2026-08-04T20:38:20Z  EXPIRED (-0.55 h)
```

**INFERENCE:** the host-run API would fail identically on any AI call it makes. This is not
container isolation — the SSO session is expired for the whole machine.

---

## The document evidence rules out content and size — DATA

| created | file | bytes | type | status | conf | model_used |
|---|---|---|---|---|---|---|
| 20:22:00 | BofA checking April.pdf | 279,052 | bank_statement | completed | 0.95 | `us.anthropic.…haiku…` |
| 20:23:18 | DL Akash Patel.pdf | 2,859,322 | drivers_license | completed | 0.95 | `us.anthropic.…haiku…` |
| 20:32:34 | Bansari W2 2024.pdf | 20,445,126 | w2 | needs_review | 0.95 | `us.anthropic.…haiku…` |
| 20:37:47 | **Akash Pay stub 1.pdf** | **9,481** | pay_stub | completed | 0.95 | `claude-haiku-4-5` |
| 20:39:19 | DL Bansari.pdf | 1,998,294 | drivers_license | completed | 0.95 | `claude-haiku-4-5` |
| 20:42:36 | **Akash Pay stub 1.pdf** | **9,481** | pay_stub | completed | 0.95 | `claude-haiku-4-5` |
| 20:42:36 | DL Bansari.pdf | 1,998,294 | drivers_license | needs_review | 0.95 | `claude-haiku-4-5` |
| 20:47:18 | **Akash Pay stub 1.pdf** | **9,481** | unknown | needs_review | **0** | **(no extraction)** |
| 20:47:18 | DL Bansari.pdf | 1,998,294 | unknown | needs_review | **0** | **(no extraction)** |
| 20:47:59 | **Akash Pay stub 1.pdf** | **9,481** | unknown | needs_review | **0** | **(no extraction)** |
| 20:47:59 | DL Bansari.pdf | 1,998,294 | unknown | needs_review | **0** | **(no extraction)** |
| 20:55:45 | **Akash Pay stub 1.pdf** | **9,481** | unknown | needs_review | **0** | **(no extraction)** |

**The same 9,481-byte file succeeded twice (20:37, 20:42) and then failed three times
(20:47, 20:47, 20:55) — byte-identical input, opposite outcomes.** Document content,
size, and quality are conclusively excluded.

Note also the successful rows: confidence **0.95** and a populated `model_used`. The
failing rows are `0` with none. There is no gradient here — it is on or off.

---

## Was it the provider switching? — checked, not assumed

You were right to flag that B1 shipped a provider flag and that a code regression from the
switching itself is possible. I tested that rather than dismissing it:

| Hypothesis | Verdict | Evidence |
|---|---|---|
| The flag left the container on stale config | **Ruled out** | Container created 20:46:05, `.env` edited 20:40:28; live env matches `.env` (§2, §3) |
| Host and worker disagree after the switch | **Ruled out** | Both resolve `bedrock` / `AsyncAnthropicBedrock` (§6) |
| `resolve_model` mis-maps after a flip | **Ruled out** | Both resolve to `us.anthropic.claude-haiku-4-5-20251001-v1:0`; and resolution happens *before* the call, so a mis-map would surface as a Bedrock validation error, not `TokenRetrievalError` |
| The rate limiter wedged after the flip | **Ruled out** | Zero `ai_rate_limit_wait` lines; failures at 40–197 ms |
| A throttle misclassified as non-transient | **Ruled out** | The only non-transient classification is `TokenRetrievalError`, which is correctly non-transient |
| Bedrock path itself broken | **Ruled out** | It demonstrably worked 20:22–20:32 with non-zero cost on the same config |

**The switching is a red herring — but an understandable one.** It is *correlated* with the
failures because switching back to Bedrock is what re-exposed the app to AWS credentials,
which had silently expired 9 minutes earlier while the direct API was carrying traffic.
Had you stayed on Bedrock throughout, the failures would have begun at 20:38 instead of
20:47, with no `.env` edit anywhere near them.

### A misleading log field — code observation, not the cause

`ai_call_failed` logs `model=claude-haiku-4-5` — the bare direct-API name — on a worker
that **is** on Bedrock. In `client.py` the success path logs `model=resolved_model` while
the failure path logs `model=model`, the caller's pre-resolution tier value.

This actively points diagnosis away from the real cause in exactly the situation where it
matters. I flagged the same thing in the previous LF-GH6Q investigation; it has now
misled twice. **No fix proposed here, per scope.**

---

## Diagnosis

**Root cause (single, high confidence): the AWS SSO access token expired at
`2026-08-04T20:38:20Z`.** Under `AI_PROVIDER=bedrock`, `AsyncAnthropicBedrock` signs every
request with credentials from that session. botocore cannot retrieve or refresh the token,
raises `TokenRetrievalError` during `_prepare_request`, and the call fails in ~40–200 ms
without a request ever being sent. `complete()` correctly classifies it non-transient;
classification degrades to `unknown@0.0`; the confidence gate routes to `NEEDS_REVIEW`
before any extraction is attempted.

**Environment problem, not a code problem.** Every application-layer component behaved as
designed: correct non-transient classification, graceful degradation instead of a crash,
the low-confidence gate doing its job, no data loss. The code has no defect here — it had
no credentials to work with.

Contributing factor, not the cause: `~/.aws` is mounted **read-only**, so the container
cannot persist a refreshed token even if a refresh were to succeed.

---

## What would confirm the diagnosis

In rough order of decisiveness:

1. **Re-authenticate and re-upload the same 9,481-byte file.** `aws sso login --profile
   mbai-dev`, recreate the worker (`up -d`, not `restart`, so it re-reads env_file — though
   the mount is live so this may be unnecessary), upload `Akash Pay stub 1.pdf` again. A
   `us.anthropic.…` `model_used` with non-zero cost confirms it. This is the same file that
   already succeeded twice and failed three times, so it is a controlled comparison.
2. **Force credential resolution and watch the exception disappear.**
   `get_frozen_credentials()` should raise `TokenRetrievalError` **now** and return
   credentials after re-login. *(I did not run this — see §4 — because a successful refresh
   would repair the environment and destroy the evidence.)*
3. **Check the new token's `expiresAt`** after re-login. If it lands ~4 h out rather than
   ~8 h, the shorter session duration is confirmed and predicts when this recurs.
4. **Falsification test:** switch to `AI_PROVIDER=anthropic` and re-upload. If it succeeds
   with `model_used = claude-haiku-4-5`, the fault is isolated to the AWS credential path
   and everything else in the pipeline is healthy. *(Not run — it changes config.)*

If (1) fails after a fresh login, this diagnosis is wrong and the next thing I would
examine is the read-only mount interacting with botocore's cache-write path.
