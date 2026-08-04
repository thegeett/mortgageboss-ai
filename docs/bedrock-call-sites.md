# Bedrock / Anthropic call sites — API process vs Celery worker

**Purpose:** determine the IAM task role for the ECS `api` service.
**Branch:** `bedrock_integration` · **Date:** 2026-08-03 · **Method:** read-only static trace.

---

## Funnel list verified

`app/ai/client.py:complete()` (`:183`) is still the single funnel — the only
`AsyncAnthropic` construction in application code is `app/ai/client.py:153`, and the only
`from anthropic import` outside tests is `client.py:40`.

Grepping every `complete(` call site returns **exactly the 13 modules** A2 listed. One
needs a note: `app/verification/finding_guidance.py` never writes `complete(` — it
injects the function as a **default argument** (`complete_fn: CompleteFn = complete`,
`:305`), so a naive `complete(` grep misses it. It is a real call site.

Twenty other modules import from `app.ai.client` but only take `build_document_message`
(the 18 extractors) or `AIClientError` (`occupancy_judgment.py`,
`services/cross_source.py`, `rule_engine/consistency.py`, `rule_engine/judgment.py`) —
they catch or build, they do not invoke.

---

## The table

Entry point = the outermost route or task reached. Chains read call-site → upward.

| module (call site) | API route? | Celery task? | entry point (file:line) | call chain |
|---|---|---|---|---|
| `app/ai/classification.py:143` | **no** | **yes** | `app/tasks/document_processing.py:448` `documents.process_document` | `classify_document:119` ← `document_processing.py:120` `_process_document:102` ← `_run:419` ← task `:448` |
| `app/ai/summarization.py:61` | **no** | **yes** | `app/tasks/document_processing.py:448` | `summarize_document:41` ← `:242` `_tier2_summarize:228` ← `_route_by_tier:178` (`:206`) ← `_process_document:162` ← task |
| `app/ai/generic_analyzer.py:187` | **no** | **yes** | `app/tasks/document_processing.py:448` | `analyze_document:168` ← `:269` `_tier3_analyze:254` ← `_route_by_tier:178` (`:208`) ← `_process_document:162` ← task |
| `app/ai/extraction/model_call.py:86` | **no** | **yes** (×2) | `app/tasks/document_processing.py:448` **and** `:466` | `run_extraction_completion:97` ← each of 18 extractors ← `EXTRACTORS` (`app/ai/extraction/__init__.py:61`) ← `:310` `_extract_branch:298` ← **(a)** `_route_by_tier:196-199` ← `_process_document` ← task `:448`; **(b)** `reprocess_document_extraction:390` (`:409`) ← `_run_reprocess:425` ← task `:466` |
| `app/services/needs_ai.py:345` | **no** | **yes** (×2) | `app/tasks/needs.py:92` **and** `:109` | `propose_needs:331` ← `apply_ai_needs:376` (`:385`) ← `apply_ai_needs_for_file_id:429` ← `tasks/needs.py:76` `_run_needs_update:64` → task `:92`; and `tasks/needs.py:84` `_run_propose_ai_needs:81` → task `:109` |
| `app/services/needs_dedup.py:372` | **no** | **yes** (×2) | `app/tasks/needs.py:92` **and** `:109` | `flag_possible_duplicates:340` ← `consolidate_and_flag:227` (`:248`) ← `tasks/needs.py:77` and `:85` → tasks `:92` / `:109` |
| `app/ai/cross_source.py:154` | **no** | **yes** | `app/tasks/cross_source.py:32` `verification.run_cross_source` | `reason_cross_source:144` ← `services/cross_source.py:125` (default `reason_fn` in `run_cross_source:99`) ← `tasks/cross_source.py:49` `_run:42` ← task `:32` |
| `app/verification/finding_guidance.py:305` | **no** | **yes** | `app/tasks/cross_source.py:32` | `generate_guidance:299` ← `services/cross_source.py:106` (default `guidance_fn`) ← `:235` `_generate_novel_guidance:223` ← `:183` in `run_cross_source:99` ← task. *Also* `app/scripts/generate_finding_guidance.py:72` — a CLI script, not a service path |
| `app/ai/tag_production.py:158` | **no** | **yes** | `app/tasks/verification_rules.py:67` `verification.run_rule_engine` | `reason_stage_a_transactions:145` ← `services/tag_production.py:151` (default `reason_fn` in `produce_stage_a_transaction_tags:139`) ← `services/verification_run.py:487` in `run_verification:453` ← `tasks/verification_rules.py:91` `_run:83` ← task `:67` |
| `app/ai/tag_correlation.py:123` | **no** | **yes** | `app/tasks/verification_rules.py:67` | `reason_stage_b_sourcing:111` ← `services/tag_correlation.py:376` (default `reason_fn` in `produce_stage_b_sourcing_tags:356`) ← `services/verification_run.py:496` ← task |
| `app/ai/rule_judgment.py:65` | **no** | **yes** | `app/tasks/verification_rules.py:67` | `reason_rule_judgment:54` ← `rule_engine/judgment.py:334` `_bind_prompt` **and** `rule_engine/consistency.py:594` `_bind_prompt` ← wired as `Reasoner` defaults at `services/verification_run.py:56,59` ← `run_verification:453` ← task |
| `app/verification/tag_materialization/ai.py:105` | **no** | **yes** | `app/tasks/verification_rules.py:67` | `reason_ai_group:99` ← `ai.py:397` `_bind_prompt` → `Reasoner` ← `materialize_tags` at `services/verification_run.py:507` (and `:349`) ← `run_verification:453` ← task |
| `app/ai/observation.py:97` | **no** | **no** | **(d) — none** | `reason_observation:85` ← `services/observations.py:164` (default in `observe_unmapped:148`). **`observe_unmapped` has no caller in `app/`** — the only references are `tests/services/test_observations.py:105,133` |

**Category tally: 12 × (b) worker-only, 1 × (d) unreachable, 0 × (a), 0 × (c).**

---

## 1. VERDICT

# NO — the `api` task role does **not** need `bedrock:InvokeModel`.

Every one of the 13 model-invoking modules is reachable only from a Celery task. Not one
is reachable from a FastAPI request handler, by any path.

Two supporting facts make this a strong "no" rather than a "probably":

- **There is no `BackgroundTasks` anywhere in the codebase.** Grepping
  `BackgroundTasks` / `background_tasks` / `add_task` across `app/` returns **nothing**.
  So there is no in-process background execution route — the only asynchrony is Celery,
  which runs in the worker.
- **No route calls a task function directly.** Every reference to `process_document`,
  `reprocess_document`, `propose_ai_needs`, `run_cross_source_pass`,
  `run_rule_engine_pass`, or `update_needs_for_document` from `app/api/` goes through
  `.delay()`. There is no synchronous fallback path where the API executes a task body.

### The trap this could easily have fallen into

Three modules that API routes import **do** import AI-calling code at module level:

| module | imports | but the API imports only |
|---|---|---|
| `app/services/needs_dedup.py` | `complete` (`:38`) | `confirm_duplicate_merge:251`, `dismiss_duplicate_flag:280` — verified: DB writes only, no AI |
| `app/services/cross_source.py` | `reason_cross_source` (`:43`), `generate_guidance` (`:66`) | `assemble_cross_source_context:556`, `compute_input_fingerprint:503`, `latest_completed_run:535` — verified: no AI |
| `app/services/document_findings.py` | `DivorceDecreeExtraction` (`:26`) | a Pydantic **type**, not a call |

An audit done by grepping "which modules import `app.ai`" would wrongly conclude the API
needs Bedrock. **Importing `app.ai.client` only loads the module; it does not invoke.**
In each case the AI-invoking function in that same module
(`flag_possible_duplicates:340`, `run_cross_source:99`) is called exclusively from a task.

---

## 2. API endpoints that trigger a Bedrock call

All five **enqueue**; none invoke. The Bedrock call happens in the worker process, after
the HTTP response has been sent.

| Endpoint | Route (file:line) | Enqueues | Bedrock work performed in the worker | Sync or backgrounded |
|---|---|---|---|---|
| `POST /api/v1/loan-files/{file_identifier}/documents` | `documents.py:119` `upload` | `process_document` via `_enqueue_processing:74` at `:186` | classification, then summarize / analyze / extract by tier; then the needs chain | **backgrounded** |
| `POST /api/v1/documents/{document_id}/replace` | `documents.py:276` `replace` | `process_document` at `:348` | same as above | **backgrounded** |
| `PATCH /api/v1/documents/{document_id}` | `documents.py:225` `override_document_type` | `reprocess_document` via `_enqueue_reprocess:88` at `:271` | re-extraction only (classification is skipped) | **backgrounded** |
| `POST /api/v1/loan-files/import-mismo` | `loan_files.py:117` `import_mismo` | `propose_ai_needs` via `_enqueue_ai_needs:52` at `:180` | `needs_ai.propose_needs` + `needs_dedup.flag_possible_duplicates` | **backgrounded** |
| `POST /api/v1/loan-files/{identifier}/verification/run` | `verification.py:176` `run_verification` | `run_cross_source_pass` at `:212`, `run_rule_engine_pass` at `:224` | cross-source reasoning + guidance; Stage A/B tags, rule judgment, AI groups | **backgrounded** |

Notes:

- The enqueue helpers are all **fire-and-forget and swallow broker errors**
  (`documents.py:74-97`, `loan_files.py:52-63`) — an enqueue failure logs and returns
  rather than 500-ing. `verification.py` is the exception: `_enqueue_cross_source:142`
  and `_enqueue_rule_engine:159` return a bool and the route marks the run FAILED on
  failure (`:212`, `:224`), deliberately, so a swallowed enqueue cannot strand a run
  RUNNING forever.
- `POST …/verification/run` has a **cache path that skips the AI entirely**: if the input
  fingerprint matches the last completed run and `force` is not set, it returns the
  cached run without enqueuing anything (`verification.py:203-...`). This reduces how
  often the worker calls Bedrock; it does not change what the API process does.
- **Name collision worth knowing:** there are three `run_verification` symbols —
  `api/verification.py:176` (the *route*, enqueues only), `services/verification_run.py`
  (the real orchestrator, task-only), and `services/verification_engine.py:67` (the
  *deterministic* engine, no AI, imported **only by tests**). Tracing by name alone would
  conflate them.

---

## 3. Synchronous in-request Bedrock calls — latency concern

**None. There are zero synchronous in-request Bedrock calls to flag.**

Every AI path is already behind Celery, so nothing blocks an ALB connection on a model
call today. No candidates for "move this to Celery" exist, because the move has already
been made everywhere.

Two observations that follow from that, relevant to C2/C3 rather than to latency:

- The architecture is already correct for ALB idle-timeout purposes. The longest
  in-request work is MISMO parsing, which `loan_files.py:64-65` explicitly notes is
  "parsed inline (fast, deterministic — no AI/Celery)".
- Because AI latency lives entirely in the worker, **worker task timeouts** (not ALB
  timeouts) are what govern AI-call duration. `settings.ai_request_timeout_seconds` (60s)
  is applied by `asyncio.wait_for` in five Phase-3 modules but **not** in the
  classification or extraction paths — noted in A2 §4 and still true.

---

## 4. S3 / storage — API-side vs worker-side

All access goes through `get_storage_backend()`; there are **8 call sites**, unchanged
since A2 (C0 added the S3 implementation, not new call sites).

| # | Call site | Operation | Side | Entry point |
|---|---|---|---|---|
| 1 | `app/api/documents.py:153` | **save** | **API** | `POST /api/v1/loan-files/{file_identifier}/documents` (`upload:120`) — backend obtained at `:149`, saved per file in the staging loop |
| 2 | `app/api/documents.py:318` | **save** | **API** | `POST /api/v1/documents/{document_id}/replace` (`replace:281`) |
| 3 | `app/api/documents.py:394` | **read** | **API** | `GET /api/v1/documents/{document_id}/download` (`download:381`) — backend obtained at `:393`; the endpoint **proxies bytes**, it does not redirect |
| 4 | `app/mismo/import_service.py:241` | **save** | **API** | `POST /api/v1/loan-files/import-mismo` (`loan_files.py:122` `import_mismo`) — stores the raw MISMO file for audit |
| 5 | `app/api/dev.py:74` | **read** | **API** (non-prod only) | `POST /api/v1/dev/documents/{document_id}/extract-text-layer` — the dev router is mounted only `if not settings.is_production` (`main.py:138-142`), so this route is **absent in production** |
| 6 | `app/tasks/document_processing.py:115` | **read** | **worker** | `documents.process_document` |
| 7 | `app/tasks/document_processing.py:408` | **read** | **worker** | `documents.reprocess_document` |
| 8 | `app/scripts/seed_dev_data.py:389` | **save** | **neither** — CLI script | `app/scripts/seed_dev_data.py` |

### Confirming the recon

A2 said uploads and downloads are API-side. **Confirmed**, with two refinements:

- The line numbers are `:153` (not `:318`) for the *bulk* upload — `:318` is the
  **`replace`** route, a second and distinct API-side write. `:149` and `:393` are
  factory calls, not operations.
- **A third API-side write exists that the recon did not name:**
  `app/mismo/import_service.py:241`, reached from `POST /api/v1/loan-files/import-mismo`.
  An IAM policy scoped from the recon's two sites would still cover it (same bucket, same
  key shape) — but it is a distinct code path and is listed here so it is not a surprise.

### Consequences for the task roles

| | API role | Worker role |
|---|---|---|
| `s3:PutObject` | **required** — sites 1, 2, 4 | not needed today (the worker never writes) |
| `s3:GetObject` | **required** — site 3 (download) | **required** — sites 6, 7 |
| `s3:DeleteObject` | not needed | not needed |
| `s3:ListBucket` | not needed by the code | not needed by the code |

- **`delete()` has no call site anywhere in `app/`.** It is implemented on both backends
  but never invoked — consistent with soft-delete everywhere (the document `DELETE`
  endpoint at `documents.py:403` soft-deletes the row and preserves the bytes). Granting
  `s3:DeleteObject` today would be an unnecessary permission.
- **`get_url()` also has no call site.** The download endpoint proxies bytes through the
  API rather than redirecting to a presigned URL, so no role needs presign-specific
  permissions today. (Presigning is a local signing operation and needs no extra IAM
  action anyway.)
- **If SSE-KMS is enabled** (`s3_kms_key_id` set, C0): the API role additionally needs
  `kms:GenerateDataKey` (for the three writes) and `kms:Decrypt` (for the download); the
  worker role needs `kms:Decrypt` only. With SSE-S3 (the default) no KMS grants are
  needed.
- **`scripts/verify-s3.py`** (C0) exercises put/get/delete/head. It runs from a developer
  or CI identity, not a task role — do not widen either task role to accommodate it.

---

## Summary for C2 / C3

| Permission | `api` task role | `worker` task role |
|---|---|---|
| `bedrock:InvokeModel` | **NO** | **YES** |
| `s3:PutObject` | YES | no |
| `s3:GetObject` | YES | YES |
| `s3:DeleteObject` | no | no |
| `kms:GenerateDataKey` | only if SSE-KMS | no |
| `kms:Decrypt` | only if SSE-KMS | only if SSE-KMS |

**Watch item for the future.** The "no Bedrock on the API role" conclusion is a property
of the current design (everything AI is behind `.delay()`), not an enforced invariant.
Two changes would silently break it: adding a FastAPI `BackgroundTasks` call that touches
an AI path, or a route calling `run_cross_source` / `apply_ai_needs_for_file_id` /
`run_verification` (the `verification_run` one) directly instead of enqueuing. Both would
fail in production with an access-denied at model-invoke time, which is a safe failure
mode — but the reason would not be obvious from the traceback. A CI grep asserting that
`app/api/**` never transitively reaches `app.ai.client.complete` would pin it.

## Loose ends found while tracing

Neither affects the verdict; both are recorded because they surfaced in the trace.

- **`app/ai/observation.py` is unreachable from application code.** `reason_observation`
  is only wired into `observe_unmapped` (`services/observations.py:148`), and
  `observe_unmapped` has no caller outside `tests/services/test_observations.py`. It is
  either an unfinished feature or dead code. It invokes the model when called, so if it
  is ever wired up, check which process calls it before assuming this document still
  holds.
- **`app/services/verification_engine.py:run_verification`** is imported only by tests
  (`tests/integration/test_refinance_e2e.py`, `tests/services/test_demo_proofs.py`,
  `tests/services/test_finding_verification_dimensions.py`, plus three `build_file_facts`
  importers). It is the deterministic LP-74 engine and makes no model calls, so it is
  irrelevant to IAM — but its name collides with two other `run_verification` symbols.
