# PII Outbound Audit — is borrower PII sanitized before Anthropic calls?

**Scope:** read-only trace of what actually crosses the network boundary to
`api.anthropic.com` on the live classify/extract/verify pipeline.
**Branch:** `phase3_new_AI_arch_finding_stage2`. **Date:** 2026-07-21.
**Nature:** audit only — no application code was changed.

---

## 1. The one-line answer

**No.** Borrower PII is **not** sanitized before it leaves the system. Raw
document bytes (the whole PDF/image, base64-encoded) go to Anthropic as-is, and
the text-reasoning passes send assembled borrower financial data (names, incomes,
amounts, verbatim document snippets) as-is.

The single most load-bearing file is **`backend/app/ai/client.py`** —
`build_document_block()` (client.py:99) base64-encodes the raw upload and
`complete()` (client.py:183) forwards it to `messages.create` untouched. There is
no redaction/masking step anywhere on that path.

The Phase 7 "PII sanitization layer before LLM calls" **does not exist yet**, as
suspected. In local dev today, uploading a real document sends its real SSNs,
account numbers, and DOBs to Anthropic.

---

## 2. The outbound payload — every Anthropic call site

The single network gateway is `complete()` in `backend/app/ai/client.py:183`
(constructs `AsyncAnthropic` at client.py:153, calls
`client.messages.create(**kwargs)` at client.py:213). Every call below routes
through it. Two payload families:

### Family A — whole-document (raw base64 bytes) — MAXIMUM exposure

These send the **entire document** as a base64 `document`/`image` block
(`build_document_message` → `build_document_block`, client.py:99–139). No OCR, no
text extraction, no field isolation — the model natively reads the raw file, so
**everything on the page** goes out: SSN, account numbers, DOB, full names,
addresses, signatures, the lot.

| Call site | Model | What is sent |
|---|---|---|
| `app/ai/classification.py:138,143` (`classify_document`) | Haiku (`anthropic_model_classification`) | Full raw document bytes |
| `app/ai/extraction/*.py` — **20 extractors**, each `build_document_message(content=content, …)` then `run_extraction_completion` → `complete` (`app/ai/extraction/model_call.py:86`) | Opus (`anthropic_model_extraction`) | Full raw document bytes |
| `app/ai/summarization.py:56,61` (`summarize_document`, Tier 2) | Haiku | Full raw document bytes |
| `app/ai/generic_analyzer.py:181,186` (Tier 3 unknown-type analysis) | Opus | Full raw document bytes |

The 20 extractors all follow the identical pattern (e.g. `pay_stub.py:210`,
`bank_statement.py:230`, `w2.py:178`, `tax_return.py:298`, `drivers_license.py:156`,
`form_1099.py:163`, `divorce_decree.py:226`, …). Confirmed via grep: every
extractor imports `build_document_message` and passes `content=content`.

Byte source (`app/tasks/document_processing.py`): `process_document` →
`content = await get_storage_backend().read(document.storage_path)`
(document_processing.py:115) → `classify_document(content, …)`
(document_processing.py:120) → `_route_by_tier(db, document, content)`
(document_processing.py:162). The **same raw `content`** bytes flow straight to
classification, extraction, summary, or generic analysis. Nothing transforms them
in between.

### Family B — assembled-text-context (structured JSON) — targeted PII

These do **not** send document bytes. They send a JSON string the app assembles
from already-extracted values + stated (MISMO) data. This is field-isolated, but
the fields it contains are still PII (names, dollar amounts, employers, and
**verbatim document snippets**).

| Call site | Model | What is sent |
|---|---|---|
| `app/ai/cross_source.py:153` (`reason_cross_source`) | Opus | `assemble_cross_source_context` JSON (see below) |
| `app/ai/rule_judgment.py:64` (`reason_rule_judgment`) | — | structured-tag context JSON |
| `app/ai/tag_production.py:157` (`reason_stage_a_transactions`) | — | `{transactions:[{date, amount, direction, …}]}` |
| `app/ai/tag_correlation.py:122` (`reason_stage_b_sourcing`) | — | `{deposit:{…}, candidates:[…]}` |
| `app/ai/observation.py:96` (`reason_observation`) | — | assembled observation context |

The cross-source context is the clearest example of what Family B carries.
`assemble_cross_source_context` (`app/services/cross_source.py:556`, its own
docstring at :559 states "Contains borrower PII (names, amounts)"):

- Borrower **full names** — `f"{b.first_name} {b.last_name}"` (cross_source.py:590)
- Stated **income** items (monthly amounts, types), **employers** by name
  (cross_source.py:591–605)
- Stated **liabilities** (payment, holder name) and **assets** (value, holder name)
  (cross_source.py:619–636)
- The verified side — each document's typed-core field **values + verbatim
  `snippet`s** (cross_source.py `_verified_documents` / `_typed_fields`)

Note: the cross-source context does **not** include SSN (no SSN field is
assembled). But verbatim `snippet`s are raw document text and can contain account
numbers or other identifiers the extractor read off the page.

---

## 3. Sanitization found — and where it actually sits

Searched broadly (`sanitiz|redact|mask|scrub|pii|anonymiz|deidentif|strip_pii|clean_text|presidio|spacy|ner`).
Everything found is **display/storage masking — NONE of it is on the outbound
LLM path.** Do not mistake these for outbound sanitization:

- **`Borrower.masked_ssn`** (`app/models/borrower.py:142`) — `***-**-1234` for
  *display/API responses*. The extraction prompt never touches this; it reads the
  SSN fresh off the raw document.
- **SSN encrypted at rest** (`app/core/encryption.py`, Fernet, ADR-051) — protects
  the DB column, not the API payload.
- **Snapshot PII masking** (`app/verification/snapshot/pii.py` — `mask`,
  `match_hash`) — masks SSN/account for the verification snapshot's *display* and
  hashes for correlation. This is the exact thing the prompt warned against
  conflating: it is display/storage masking, **not** payload sanitization.
- **At-rest raw-PII guard** (`app/verification/snapshot/persistence.py:63` —
  `RawPiiAtRestError`) — fails the DB write if a snapshot still contains a raw
  dashed SSN or a long bare digit run. This guards the *database*, downstream of
  and unrelated to what the LLM already received.
- **`app/storage/base.py:37` `_sanitize_extension`** — filename path-traversal
  hygiene. Unrelated to PII.

**Outbound-path result: zero sanitization.** `build_document_block` (client.py:99)
base64-encodes and ships; `complete` (client.py:183) forwards `messages`
unchanged (its own docstring, client.py:26–28, confirms "document bytes … are
never logged" — a logging guarantee, not a redaction one).

---

## 4. Can extraction even be sanitized? (whole-document vs field-isolated)

**Family A is whole-document by design, and that design requires raw PII to go
out.** Classification and extraction send the entire file precisely so the model
can *read* the SSN / account number / income off it (client.py:22–28: "send the
**full document** … for native reading — no OCR, no pre-extracted text").
Extraction's job **is** to read those exact values. A naive redaction pass on the
bytes would blank out the very fields the extractor exists to capture, and would
also have to defeat the model's native PDF/image reading (redacting rendered pixels
/ PDF text is a hard problem, not a filter). So for Family A, "add sanitization" is
a **design question**, not a small filter.

**Family B is already field-isolated** — it sends a structured JSON the app
controls (cross_source.py:556+). Here selective redaction *is* mechanically easy
(drop/mask chosen keys before `json.dumps`), but the values it sends (names,
amounts, employers) are largely the substance the reasoning pass compares, so
redacting them degrades the feature too — though less catastrophically than
Family A.

---

## 5. Logging / retention exposure

- **Prompt/response content is never logged.** `complete()` logs metadata only —
  model, token counts, latency, attempt, error type, stop reason
  (client.py:218–226 on failure, client.py:241–249 on success). Every AI module's
  own logging is metadata/count-only and says so (classification.py:150,155;
  cross_source.py:171–177; model_call.py:93). Grep for logging of `.text`
  (response) content returned **nothing**. This is a genuine strength — no debug
  log dumps the extraction prompt.
- **No zero-data-retention / no-logging posture in code.** The client is built as
  `AsyncAnthropic(api_key=…, max_retries=0)` (client.py:153) with **no**
  `default_headers`, no beta/ZDR header, no retention flag. Grep for
  `zdr|retention|anthropic.?beta|default_headers|extra_headers` returned nothing.
  Whatever retention applies is purely the account-tier default at Anthropic — the
  code asserts nothing. (Reporting what the code shows; account settings are out of
  scope.)
- **Where bytes rest — local disk only, today.** `storage_backend` defaults to
  `"local"` (`app/core/config.py:105`), `storage_local_path = "./storage"`
  (config.py:106). The factory only constructs `LocalStorageBackend`; the S3 branch
  is commented-out/future (`app/storage/__init__.py:35–38`, base.py:4–5 "S3 in
  production — Phase 7"). No `boto`/S3 code path is live. Nothing copies bytes
  elsewhere. So raw files sit on the local filesystem and leave the box **only** via
  the Anthropic calls above.

---

## 6. Recommendation (options — the choice is Geet's)

The layer is absent. Given that Family A extraction inherently must read real
values, the honest options, smallest-first:

1. **Accept that extraction sends PII; rely on a data-processing posture instead
   of redaction (recommended as the realistic V1 stance).** Whole-document
   classification/extraction cannot function without the raw file. The correct
   "smallest correct version" here is *not* a redaction filter — it is:
   (a) enable **zero-data-retention** on the Anthropic account and, if ZDR is
   available via header, set it explicitly on the client (client.py:153) so the
   guarantee is in code, not just account config;
   (b) confirm you are on a **no-training / commercial** data terms tier;
   (c) keep the existing metadata-only logging (already true).
   This is the standard posture for document-AI on real PII and is defensible for
   real-client testing. It does **not** make the local-dev URL "safe" by itself —
   it makes the *third party* contractually non-retaining.

2. **Gate real-PII testing behind that posture; use synthetic files until then.**
   For the immediate "can we test real client files" question: until ZDR + terms
   are confirmed, test with synthetic/redacted fixtures. This is a process control,
   not code.

3. **Add selective redaction to Family B only (cheap, partial).** The text-context
   passes (cross_source.py:556+) are field-isolated JSON — you *could* mask holder
   names / drop snippets there before `json.dumps` at low effort. But this leaves
   Family A (the bulk of the exposure) untouched, so it is cosmetic unless paired
   with option 1.

4. **True Family-A redaction (large, design-level, not recommended for V1).**
   Would require a pre-pass that OCRs → redacts → re-renders the document before
   sending, *and* a way to still recover the real values the extractor needs
   (defeating the point) — or a switch to a two-stage "locate-then-reveal" design.
   This is a Phase-7-sized project, not a filter.

**Bottom line:** there is no outbound sanitization today; extraction's design
means the practical fix is a retention/terms posture (option 1), not a redaction
filter. Whether real client files may be tested now hinges on that posture, which
is not asserted anywhere in the code — so as of this branch, treat every real
upload as shipping raw PII to Anthropic.

---

### Where I looked (for anything reported "not found")

- ZDR/retention/beta headers: grep over `backend/app` — none.
- Response-content logging: grep `.text` + `log|print|debug` over `app/ai` — none.
- Redaction on outbound path: grep the full sanitization term set over
  `backend/app` — only display/storage masking (§3), none on the `complete()` path.
- Live S3/remote byte copy: `app/storage/` — local-only; S3 is commented future.
