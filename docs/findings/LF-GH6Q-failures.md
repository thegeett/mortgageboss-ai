# LF-GH6Q — two document processing failures

**Investigated:** 2026-08-04 · **DB:** `mbai-bedrock-postgres` (port 5433), read-only
**Loan file:** `LF-GH6Q` = `7ac2bcc1-6e95-4137-bbd6-6d04a1b8629d`

Diagnosis only — no fixes proposed. Every claim is labelled **DATA** (observed) or
**INFERENCE** (reasoned from it).

---

## Summary

Two failures, **two different causes**, neither of them a Bedrock *service* fault:

| | Document | Cause | Category |
|---|---|---|---|
| **A** | W2 2025 Bansari.pdf | Worker cannot resolve AWS credentials → the Bedrock call fails before leaving the process | **Environment** — the known SSO-cache gap |
| **B** | BofA savings May.pdf | Task ran on `mbai-images-worker`, which has **no storage mount** and cannot read the file | **Environment** — a leftover C1 rehearsal container sharing the broker |

**Neither document ever reached Bedrock.** No call has *ever* reached Bedrock from this
database (see Cross-cutting §3).

---

## Evidence

### `documents` rows — DATA

| Column | **A** — W2 2025 Bansari.pdf | **B** — BofA savings May.pdf |
|---|---|---|
| `id` | `422251e6-555c-4f8c-a4c8-3b17098ab35c` | `b9c137ce-5cbc-4971-91f8-ece5edd59358` |
| `file_size_bytes` | 3,698,007 | 270,781 |
| `document_type` | `unknown` | **NULL** |
| `tier` | `tier_3` | **NULL** |
| `category` | `misc` | **NULL** |
| `status` | `needs_review` | `failed` |
| `processing_error` | **NULL** | `processing error` (16 chars) |
| `classification_confidence` | **0** | **NULL** |
| `summary` / `generic_analysis` | null / null | null / null |
| `created_at` | 19:58:20.636715+00 | 19:58:47.991472+00 |
| `updated_at` | 19:58:20.950280+00 | 19:58:48.098721+00 |
| **elapsed** | **314 ms** | **107 ms** |

### `extractions` rows — DATA

**Neither document has an extractions row. `count(*) = 0` for both.** So no
`extraction_status`, `error_detail`, `model_used`, `tokens_used`, `cost_estimate`,
`confidence`, or `confidence_source` exists to report — the pipeline never reached
`create_extraction_version` for either.

### Activity log — DATA

```
file_created        Loan file created from MISMO import   16:55:15
document_uploaded   Uploaded 1 document                   19:58:20.647   ← A
document_processed  Classified as unknown                 19:58:20.948   ← A
document_uploaded   Uploaded 1 document                   19:58:48.001   ← B
                    (no document_processed for B)
```

### Worker logs — DATA, verbatim

**A — on `mbai-bedrock-worker`:**

```
[2026-08-04 19:58:20,685: INFO/MainProcess] Task documents.process_document[1e3ccc21-c07c-42f9-80a9-2478187723a9] received
[2026-08-04 19:58:20,923: WARNING/ForkPoolWorker-4] 2026-08-04 19:58:20 [warning  ] ai_call_failed  attempt=1 error_type=RuntimeError latency_ms=47 max_attempts=3 model=claude-haiku-4-5 transient=False
[2026-08-04 19:58:20,923: WARNING/ForkPoolWorker-4] 2026-08-04 19:58:20 [warning  ] classification_ai_failed
[2026-08-04 19:58:20,952: WARNING/ForkPoolWorker-4] 2026-08-04 19:58:20 [info     ] document_needs_review  document_id=422251e6-555c-4f8c-a4c8-3b17098ab35c reason=low_confidence
[2026-08-04 19:58:20,954: INFO/ForkPoolWorker-4] Task documents.process_document[1e3ccc21-...] succeeded in 0.26413940195925534s: None
```

**B — on `mbai-images-worker`** (nothing for B appears in `mbai-bedrock-worker`'s log at all):

```
[2026-08-04 19:58:48,020: INFO/MainProcess] Task documents.process_document[f1f86b44-d2cc-49fc-8f1f-2cb996d18de1] received
[2026-08-04 19:58:48,094: WARNING/ForkPoolWorker-4] 2026-08-04 19:58:48 [warning  ] process_document_failed  document_id=b9c137ce-5cbc-4971-91f8-ece5edd59358 error_type=StorageError
[2026-08-04 19:58:48,103: INFO/ForkPoolWorker-4] Task documents.process_document[f1f86b44-...] succeeded in 0.0488814078271389s: None
```

**Neither log contains a traceback** — both exceptions are caught and logged
metadata-only (`client.py` for A, `_process_document`'s handler for B), by design.
The traceback for A was obtained by reproduction (below); B's `StorageError` is
reproduced structurally by the mount comparison.

### The exact exception behind A — DATA (reproduced in the worker container)

```
File ".../anthropic/lib/bedrock/_client.py", line 407, in _prepare_request
    headers = get_auth_headers(
File ".../anthropic/lib/bedrock/_auth.py", line 65, in get_auth_headers
    raise RuntimeError("could not resolve credentials from session")
RuntimeError: could not resolve credentials from session
```

Raised in `_prepare_request` — **before the request is sent**. That is the 47 ms.

### Environment — DATA

```
$ docker exec mbai-bedrock-worker env | grep ^AWS      → (none)
$ docker exec mbai-bedrock-worker ls ~/.aws            → No such file or directory
$ docker exec mbai-bedrock-worker python -c "boto3.Session().get_credentials()"
                                                        → credentials: NONE, region: None

$ ls ~/.aws        (host)                               → config, sso/, cli/   ← exists, NOT mounted
```

Worker container config state:

| | `mbai-bedrock-worker` | `mbai-images-worker` |
|---|---|---|
| `AI_PROVIDER` | `bedrock` | **unset** |
| `BEDROCK_MODEL_EXTRACTION` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | — |
| B1 code present (`ai_provider` in config.py) | yes (7 refs) | **no (0 refs — pre-B1 image)** |
| storage mount | `…/backend/storage → /app/storage` | **none** |
| can see the uploaded PDFs | **yes** | **no** |

Both PDFs exist on the host at
`backend/storage/613828ff…/7ac2bcc1…/` (3,698,007 and 270,781 bytes) — the files are fine.

### Document characteristics — DATA

| | A | B |
|---|---|---|
| bytes | 3,698,007 | 270,781 |
| base64 payload | **4,930,676** | 361,044 |
| pages | **1** | 6 |
| text layer | **none** (scanned image) | present |

---

## A — W2 2025 Bansari.pdf → `unknown`, NEEDS_REVIEW

### Why did the classifier return "unknown"? — DATA + INFERENCE

**It never classified anything.** No model response was received.

**DATA:** the log sequence is `ai_call_failed` → `classification_ai_failed` →
`document_needs_review reason=low_confidence`, and `classification_confidence` is
exactly `0`.

**INFERENCE (high confidence — the code path is unambiguous):** `classify_document`
caught `AIClientError`, logged `classification_ai_failed`, and returned
`ClassificationResult.unknown("AI call failed")`, which is defined as
`document_type="unknown", confidence=0.0, reasoning=<reason>`.

**The "raw classification response" you asked for does not exist.** There was no
response to record. The `reasoning` field carried the literal fallback string:

```
document_type: "unknown"
confidence:    0.0
reasoning:     "AI call failed"
category:      None
```

That object is never persisted — only `document_type` and
`classification_confidence` reach the `documents` row — so this is reconstructed from
the code path, corroborated by the two log lines and the stored `0` confidence.

`tier_3` / `misc` follow mechanically: `"unknown"` is not in the catalog, so
`get_tier_and_category` returns the long-tail default. They were written *before* the
confidence gate ran, which is why they are populated on a document that never routed.

### Did it fail the gate, or classify confidently as unknown? — DATA

**It failed the gate.** `classification_confidence = 0`, and `0 < 0.5`
(`_CONFIDENCE_THRESHOLD`, `document_processing.py:75`). The log says
`reason=low_confidence`.

This is the distinction the pipeline is explicitly built to make
(`document_processing.py:141-147`): a *confident* `unknown` falls through to Tier 3 and
the generic analyzer. This document did not — `generic_analysis` is null and no Tier-3
work ran. A `0.0` confidence is the signature of the AI-failure fallback, **not** of a
model that looked at a W-2 and was unsure.

### Is 3.5 MB / the base64 payload the cause? — DATA: no

**It cannot be.** The failure is at `_prepare_request` — credential resolution — which
runs **before** the payload is transmitted. The 47 ms confirms nothing was uploaded.

For completeness: 1 page, 4,930,676 base64 characters (~4.9 MB). For reference the
direct Anthropic API's documented request ceiling is 32 MB / 600 pages, so 4.9 MB / 1
page is comfortably inside it. **I have not verified Bedrock's specific InvokeModel
payload ceiling** and am not asserting one — but since the request never left the
process, the size is moot for this failure either way.

One observation worth carrying forward: the file is a **1-page scan with no text
layer** at 3.5 MB. That is large for one page and suggests a high-DPI image. It is not
implicated here, but it is the kind of document most likely to bump a payload limit
once calls do reach Bedrock.

### Diagnosis — A

**Environment problem, not a code problem.** The containerised worker has no AWS
credentials: no `AWS_*` env vars, no `~/.aws`, and the host's SSO cache is not mounted
into it. `AsyncAnthropicBedrock` therefore fails at signing with
`RuntimeError: could not resolve credentials from session`.

Everything downstream behaved **correctly**: the error was classified non-transient
(a missing credential is not retryable), classification degraded gracefully to
`unknown@0.0` rather than crashing, and the low-confidence gate routed the document to
human review. The pipeline's fail-closed design worked — it just had nothing to work
with.

---

## B — BofA savings May.pdf → FAILED, no type

### The exact exception — DATA

`error_type=StorageError`, logged by `_process_document`'s handler. `processing_error`
is the safe constant `"processing error"` (never raw detail, by design), so the DB
carries no further specifics.

The failure is at `get_storage_backend().read(document.storage_path)` — the **first**
statement inside the `try` block, before `status` is set to `CLASSIFYING`. That is why
`document_type`, `tier`, `category`, and `classification_confidence` are all NULL, and
why there is no `document_processed` activity entry.

### Which of the four candidate causes? — DATA: storage read

You asked me to check specifically for a Bedrock credential error, a misclassified
throttle, a storage read error, or something else. **It is the storage read**, and the
mechanism is precise:

**DATA:** the task ran on `mbai-images-worker`, not `mbai-bedrock-worker`. That
container has **no storage mount**:

```
mbai-bedrock-worker   …/backend/storage → /app/storage    ← file visible
mbai-images-worker    (no mounts)                          ← ls: No such file or directory
```

The API (host process) wrote the PDF to `backend/storage`; the file is present and
readable there. `mbai-images-worker` looked for it on its own empty container
filesystem and `LocalStorageBackend.read` raised `StorageError: No stored file at …`.

**Why that worker got the task — DATA:** both workers are attached to
`mbai-bedrock_mortgageboss-network` and both use `REDIS_URL=redis://redis:6379/0`, i.e.
the same broker. `mbai-bedrock-worker`'s startup log shows `mingle: sync with 1 nodes`.
Each worker received exactly one of the two tasks — ordinary Celery round-robin.

`mbai-images-worker` is the C1 rehearsal container, up 27 hours. C1 omitted its storage
mount **deliberately**, to demonstrate the Fargate no-shared-filesystem gap. It was
never meant to consume production tasks; it does so because it shares the broker.

**Not credentials:** the credential error cannot occur here — execution never reached
the AI layer. (And `mbai-images-worker` has `AI_PROVIDER` unset and a pre-B1 image, so
it has no Bedrock support at all.)

**Not a throttle:** no throttle appears anywhere in either log.

### Diagnosis — B

**Environment problem, not a code problem, and unrelated to A's cause.** A leftover C1
rehearsal worker sharing the broker picked up a task it structurally could not perform,
because it has no view of the storage volume the API writes to.

**INFERENCE:** which worker gets which document is arbitrary. Had B landed on
`mbai-bedrock-worker` it would have read the file successfully and then hit A's
credential error instead. **B's `StorageError` is masking a second instance of A's
failure**, and the two documents' different outcomes are an accident of task
distribution, not of the documents.

---

## Cross-cutting

### 1. Were any `ai_rate_limit_wait` lines emitted? — DATA: zero

`0` in both workers over 4 hours.

**INFERENCE:** this neither confirms nor refutes that pacing works, and should not be
read as a limiter fault. Only **one** AI call was attempted in the whole window. The
limiter logs only when it actually waits, and the first acquisition after
`_next_allowed_at = 0.0` never waits. With one call, zero lines is the expected output.
Pacing at 8 RPM remains unexercised.

### 2. Did `_is_transient` misclassify anything that looks like a throttle? — DATA: no

Exactly one `ai_call_failed` line exists, and it is the credential `RuntimeError`,
classified `transient=False`. Verified directly:

```
_is_transient(RuntimeError("could not resolve credentials from session")) → False
```

That is **correct** — a missing credential will not fix itself, and retrying would burn
two more attempts to reach the same result. **No throttle occurred**, so there was
nothing to misclassify.

### 3. Did any call reach Bedrock at all? — DATA: no, and none ever has

`model_used` across the **entire** `extractions` table:

| `model_used` | rows | most recent |
|---|---|---|
| `claude-sonnet-4-5` | 86 | 2026-07-21 |
| `claude-sonnet-4-6` | 4 | 2026-06-13 |

**No `us.anthropic.*` row exists anywhere.** The Bedrock path is unproven end to end;
these two documents did not change that.

Two further observations from that table:
- There are **no `claude-haiku-4-5` rows at all**, so no extraction has been stored since
  the LP-457 Haiku switch. Every row predates the `phase3_bucket_2` merge — they are
  seeded data from the A1 copy.
- Consequently the `us.anthropic.*` / bare-`claude-*` check documented in `backend/.env`
  currently has no Bedrock-era rows to distinguish.

### 4. A misleading log field — observation, not a cause

A's failure logged `model=claude-haiku-4-5`, the bare direct-API name, on a worker that
**was** configured for Bedrock. That is not evidence of misconfiguration: in
`client.py`, the success path logs `model=resolved_model` while the `ai_call_failed`
path logs `model=model` — the caller's tier value, pre-resolution.

I initially read that bare name as proof the worker had not picked up the Bedrock
config; checking the container directly disproved it (B1 code present, `AI_PROVIDER=bedrock`).
Flagging it because it points diagnosis away from the real cause in exactly the
situation it matters. **No fix proposed here, per scope.**

---

## What the data does not tell us

- **Whether Bedrock would accept these documents.** No request left the process, so the
  inference profiles, IAM permissions, request shape, and payload ceiling are all still
  unverified. `scripts/verify-bedrock.py` remains unrun.
- **Whether A's 3.5 MB / 4.9 MB-base64 payload is within Bedrock's limit.** Stated as
  measured; the ceiling itself is unverified and was not reached.
- **Whether the classifier can identify this W-2.** It never saw it. The `unknown`
  result carries no information about the document's content — notably, it is a scan
  with no text layer, which is a genuinely harder classification input, but that was
  never tested here.
