# A2 — Extraction pipeline reconnaissance (READ-ONLY)

**Branch:** `bedrock_integration`
**Depends on:** A1
**Blocks:** every Bedrock implementation ticket

---

## Purpose

Produce an accurate picture of how document classification and extraction work **today** —
storage shape, per-type schemas, the AI client seam, and how downstream consumes the result.
The Bedrock work is designed against this document, so guessing here propagates into every
later ticket.

**This ticket writes exactly one file. It changes no code.**

---

## Rules

- **Read-only.** Do not modify, create, or delete any file except the output document.
- Do not run `docker compose up/down`, Alembic, `uv sync`, or `pnpm install`.
- Read-only DB inspection via `docker exec mbai-bedrock-postgres psql …` is allowed and
  encouraged for schema questions. `SELECT` only.
- **Quote `file:line` for every claim.** A claim without a reference is a guess.
- Where something is genuinely absent, write **NOT FOUND** rather than inferring.
- Never print secret values. Keys and variable names only.

---

## Output

Write **`docs/extraction-current-state.md`** with the sections below, and print it to stdout.
Terse — facts and references, not narrative.

### 1. Document type registry

- Where are document types defined? Enum, DB table, config file, or seed data — give the path.
- **Full list of type identifiers** currently supported, with their category grouping if one
  exists.
- Is the three-tier model from the V1 build plan (Tier 1 first-class / Tier 2 recognized /
  Tier 3 custom) actually implemented? If so, how is tier recorded, and which types are Tier 1?
- Is there a "custom" or "other" catch-all type? How is it assigned?
- Specifically: are **credit report**, **appraisal**, and **AUS/DU findings** present as types?
  These are the three blocker documents; report exactly what exists for each.

### 2. Extraction storage

- Which tables hold extraction results? Give `__tablename__` and the model file for each.
- **Full column list** for each: name, type, nullable, default.
- Are extracted fields typed columns, JSONB, or an EAV key/value shape?
- How is **confidence** stored — per field, per document, or not at all?
- Where does the confidence value originate — model output, a constant, or computed?
- Is there a per-field **source location** (page number, bounding box, citation)?
- Is document **versioning** implemented (build plan §2.4)? How is supersession represented?
- Relevant Alembic revisions that created or altered these tables, in order.

### 3. Per-document extraction schemas

The core question: **how does the system know which fields to extract from a pay stub versus a
W-2?**

- Where is that defined — Pydantic models, JSON schema, prompt templates, DB rows?
- Show **one complete example** for a Tier 1 type (pay stub or W-2 preferred), verbatim.
- How does a schema bind to its document type? Naming convention, registry, dispatch table?
- Is the schema used to constrain the model (tool use / structured output), or only to validate
  the response afterward?
- What happens when the response fails validation — retry, partial store, or discard?

### 4. The AI client seam

- `backend/app/ai/client.py` — full public interface. Every function, its signature, and who
  calls it.
- Where is `AsyncAnthropic` constructed, and is `client.py:153` the **only** construction site?
  Grep the whole backend and report every hit.
- How are messages assembled? Show the request shape for one classification call and one
  extraction call.
- Are documents sent as base64 blocks, extracted text, or images? Which content-block types
  appear?
- Retry and backoff: how do `AI_MAX_RETRIES` and `AI_BASE_RETRY_DELAY_SECONDS` get used, given
  the client is constructed with `max_retries=0`?
- How are `ANTHROPIC_MODEL_CLASSIFICATION` and `ANTHROPIC_MODEL_EXTRACTION` consumed? Are there
  other model selection points?
- Is token usage recorded anywhere — logged, stored, or discarded?
- Are prompt caching, Citations, or tool use used at all today?

### 5. Pipeline flow

The worker registers `documents.process_document` and `documents.reprocess_document`. Trace
both end to end.

- Entry point file and function for each.
- **Ordered step list** from upload through stored extraction, with the file:line for each step.
- Where does classification happen relative to extraction? One call or two?
- Is there any pre-processing today — PDF page splitting, text-layer extraction, rasterizing,
  form-field handling, size checks? Report exactly what exists.
- Is multi-page or multi-document handling present in any form?
- How does a failure mid-pipeline get recorded? Is there a status field, and what are its
  values?

### 6. Loan-file scoping

- How is every extraction record tied to its loan file? Show the FK.
- Are there DB constraints preventing cross-loan-file association, or only application logic?
- Do extraction queries always filter by `loan_file_id`? Report any query path that does not.
- Is there row-level security or tenant scoping beyond the FK?

### 7. Downstream consumption

- Which code reads extraction results? List each consumer with file:line.
- How does the **Stage 1 snapshot builder** read them — direct query, service, or repository?
- What shape does it expect? Show the interface.
- Is the PII masking from Architecture v2 §3B (display last-4 + salted `match_hash`)
  implemented? If yes, where; if no, say NOT FOUND.

### 8. Storage backend

- `backend/app/storage/` — the full backend interface (abstract base or protocol).
- Every method `LocalStorageBackend` implements, with signatures.
- Every call site of the storage interface across the backend.
- What is stored — original upload only, or derived artifacts too?
- How are storage keys or paths constructed? Is `loan_file_id` in the path?
- Confirm the `"s3"` branch state in `app/storage/__init__.py` and exactly what would need to
  exist for it to work.

### 9. Tests

- Which test files cover extraction, classification, and the AI client?
- Are AI calls mocked? Show the mocking approach.
- Are there fixtures with real or de-identified documents? Where?
- Is there any golden-file or eval harness for extraction accuracy?

### 10. Gaps and risks

Your own assessment, clearly separated from the factual sections above:

- What would have to change for extraction to run through Bedrock instead of the direct
  Anthropic API? List concretely.
- Which parts are tightly coupled to the Anthropic SDK's specific response shape?
- Anything that looks like it would break under a different provider.
- Anything surprising, inconsistent, or apparently unfinished.

---

## Verify

- `docs/extraction-current-state.md` exists and every section has content.
- Every factual claim carries a `file:line` reference.
- `git status` shows **only** that one new file. Anything else is a ticket violation.

---

## Stop and report — do not work around

- Any section that cannot be answered from the repo — write NOT FOUND and continue, then list
  it in the result summary.
- Any place where the code contradicts Verification Architecture v2 or the V1 Build Plan.
  Record the contradiction; do not reconcile it.

---

## Do not

- Modify any file other than `docs/extraction-current-state.md`.
- Run any write query, migration, or container lifecycle command.
- `git push`.
- Refactor, fix, or improve anything you find. This ticket only observes.
