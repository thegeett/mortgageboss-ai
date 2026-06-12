# API

The HTTP API surface. All business endpoints are versioned under `/api/v1`,
require authentication, and are **tenant-scoped** to the caller's company.

See [`authentication.md`](authentication.md) for login/refresh/logout and the
auth dependencies, and [`onboarding-and-tenancy.md`](onboarding-and-tenancy.md)
for the tenancy model.

## Conventions

- **Auth** — every business endpoint depends on `CurrentUser` (a valid Bearer
  access token → the live, active user). No token → `401`.
- **Tenant scope** — the company is **always** `current_user.company_id` (LP-24),
  **never** taken from the request body or query. Queries are filtered with
  `scope_to_company` (LP-11), so another company's data is never returned.
- **Out-of-company access → `404`** (not `403`): a scoped query simply finds
  nothing, and we don't reveal that a resource exists (anti-enumeration).
- **Soft delete** — deletes set `deleted_at`; reads exclude soft-deleted rows via
  `only_active` (LP-10). Nothing is hard-deleted.
- **Never exposed** — `inbox_token` (the borrower-email capability) and raw `ssn`
  (borrowers expose `masked_ssn` only) appear in no response.
- **Transactions** — `get_db` does not auto-commit; write endpoints commit after
  the service flushes.

## Error responses (LP-46)

Every error uses **one envelope** (ADR-154), so a client has a single shape to
handle:

```json
{ "error": { "type": "not_found", "message": "Loan file not found" } }
```

- `type` — a stable code derived from the status (`unauthorized`, `forbidden`,
  `not_found`, `conflict`, `validation_error`, `internal_error`, …).
- `message` — a **SAFE**, human-readable sentence. Never a stack trace, internal
  path, DB text, or PII.
- `details` — present only for **422** validation errors: a list of
  `{ "field": "loan_amount", "message": "…" }` (the message describes the
  *constraint*, never echoes the submitted value).

A global handler (`app/core/errors.py`) guarantees the envelope for: any
unhandled exception → a generic **500** (`"An unexpected error occurred…"`; full
detail logged server-side as PII-safe metadata only — error type, path, method),
`HTTPException` (404/401/403/409/…), and `RequestValidationError` (422). No
endpoint returns a raw 500, a stack trace, or framework HTML.

## Loan files (LP-28)

Base path: `/api/v1/loan-files`. Identifiers in paths may be the **UUID** or the
human **`display_id`** (`LF-XXXX`). Relevant ADRs: **ADR-093** (tenant scoping),
**ADR-094** (summary vs detail, capabilities hidden), **ADR-095** (identifier +
soft delete).

| Method | Path | Auth | Body | Success | Notes |
| --- | --- | --- | --- | --- | --- |
| POST | `/loan-files` | yes | `LoanFileCreate` | `201` `LoanFileDetail` | company from the user; starts `DRAFT` |
| GET | `/loan-files` | yes | — | `200` `PaginatedLoanFiles` | company-scoped, paginated, status filter |
| GET | `/loan-files/{id_or_display_id}` | yes | — | `200` `LoanFileDetail` | `404` if not in the caller's company |
| PATCH | `/loan-files/{id_or_display_id}` | yes | `LoanFileUpdate` | `200` `LoanFileDetail` | partial; immutable fields protected |
| DELETE | `/loan-files/{id_or_display_id}` | yes | — | `204` | soft delete; `404` if out-of-company |

### Create

`LoanFileCreate` carries only optional, settable fields (`lender_id`,
`loan_program`, `loan_purpose`, `loan_officer_name`, `loan_officer_email`) — **no
`company_id`** (derived from the user; a `company_id` in the body is ignored). A
file may be created empty and filled in later.

**Creation is orchestrated (LP-30).** Beyond inserting the row, `POST` also generates a
**provisional initial needs list** (program-based starter template, origin `TEMPLATE`)
and records a `FILE_CREATED` activity. These are internal side-effects — the **response
contract is unchanged** (still `LoanFileDetail`). The needs template is *provisional* and
pending domain refinement (ADR-100). See ADR-099 (orchestration) and ADR-101 (activity
logging).

### Activity logging (LP-30)

Loan-file write operations now append to the file's audit trail (the first adoption of
`log_activity`, ADR-101), with the acting user:

| Operation | Activity | Detail |
| --- | --- | --- |
| `POST` (create) | `FILE_CREATED` | program/purpose + `initial_needs_count` |
| `PATCH` (status change) | `STATUS_CHANGED` | `{from, to}` |
| `PATCH` (other fields) | `FILE_UPDATED` | `{changed_fields: [...]}` |
| `DELETE` (soft) | `FILE_DELETED` | — |

This logs **status changes**, not a transition *state machine* — any-to-any status moves
are still allowed (enforcement would be a separate ticket). Two enum values
(`FILE_UPDATED`, `FILE_DELETED`) were added to `ActivityType` for this.

### List — pagination & filtering

Unchanged from LP-28 — listing was not rebuilt for LP-30.

Query params: `page` (default `1`, ≥1), `page_size` (default `20`, 1–100),
`status` (**repeatable** `LoanFileStatus` — `?status=draft&status=submitted` filters
to any of them, so the dashboard's grouped pills paginate correctly), and `search`
(LP-31). Returns `PaginatedLoanFiles`: `{ items: LoanFileSummary[], total, page,
page_size }`, ordered newest-first (`created_at desc`), excluding soft-deleted and
other companies' files. `total` is the full count for the filters, independent of
the page.

**`search` (LP-31, ADR-103)** — case-insensitive, matches `display_id` OR a
borrower's name; **always company-scoped** (composed with `scope_to_company`), so it
can never reach another company's files (verified by test).

### Summary vs detail

- **`LoanFileSummary`** (list items) — lean: `id`, `display_id`, `status`,
  `loan_program`, `loan_purpose`, `loan_amount`, `lender_id`,
  **`lender_name`** (the lender's name, or null), **`property_address`** (the
  property's address line, or null — both LP-31, resolved via eager-load),
  `primary_borrower_name` (derived from the `is_primary` borrower),
  `created_at`, `updated_at`. **No `inbox_token`.**
- **`LoanFileDetail`** (single file) — summary + `loan_officer_name`/`email` +
  nested `borrowers` (`BorrowerPublic`, `masked_ssn` only) and `property`
  (`PropertyPublic`). **No `inbox_token`, no raw `ssn`.**

### Update — PATCH semantics

`LoanFileUpdate` holds only mutable fields (`lender_id`, `loan_program`,
`loan_purpose`, `loan_amount`, `status`, `loan_officer_name`,
`loan_officer_email`). Only fields the client **explicitly sends** are applied
(`exclude_unset`): an omitted field is left untouched, while an explicit `null`
clears it. Identifiers and ownership (`id`, `display_id`, `inbox_token`,
`company_id`) are immutable — they aren't in the update schema and can't be
changed.

### Tenant isolation (the crux)

Every read/write goes through a company-scoped service. A Company A user **cannot**
list, retrieve, update, or delete Company B's files — out-of-company access
returns `404`, verified by tests. The scoping `company_id` is non-forgeable (it
comes from the validated token + live user), so isolation holds regardless of what
the client sends.

## Borrowers & property (LP-29) — nested under a loan file

Borrowers and the subject property have **no `company_id`** of their own — they are
scoped **transitively through the parent file** (ADR-052/053). The endpoints are
nested, and every route first resolves the parent file scoped to the caller's
company (the `ScopedLoanFile` dependency): if the file isn't the caller's (or
doesn't exist) it returns **`404` before the child is ever reached** — the tenant
gate. Relevant ADRs: **ADR-096** (nested routes, transitive scoping), **ADR-097**
(SSN in-but-masked-out), **ADR-098** (property singleton + minimal primary logic).

### Borrowers — a collection

Base path: `/api/v1/loan-files/{file_identifier}/borrowers`.

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| GET | `/borrowers` | `200` `BorrowerResponse[]` | ordered by `borrower_position` |
| POST | `/borrowers` | `201` `BorrowerResponse` | SSN accepted, stored encrypted |
| GET | `/borrowers/{borrower_id}` | `200` `BorrowerResponse` | `404` if not under this file |
| PATCH | `/borrowers/{borrower_id}` | `200` `BorrowerResponse` | partial; provided `ssn` re-encrypted |
| DELETE | `/borrowers/{borrower_id}` | `204` | soft delete |

**SSN — in-but-masked-out.** Create/update accept a raw `ssn`, written to the
`EncryptedString` column (encrypted at rest). **No response carries a raw `ssn`** —
only `masked_ssn` (`***-**-1234`). The raw SSN never leaves the server and is never
logged (verified: encrypted at rest via raw SQL; no raw SSN in any response body).

**Cross-file safety.** `get_borrower` matches both the borrower id **and** the
`loan_file_id`, so a borrower id from a *different* file (even in the same company)
is `404` under this file.

**Primary/position (minimal V1).** The first borrower defaults to primary at
position 1; later borrowers default to non-primary at the next position. Creating or
updating a borrower to `is_primary=True` demotes the file's other borrowers (one
primary). Otherwise primary state is client-managed.

### Property — a per-file singleton

Base path: `/api/v1/loan-files/{file_identifier}/property` (no child id — one per file).

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| GET | `/property` | `200` `PropertyResponse` | `404` if none |
| POST | `/property` | `201` `PropertyResponse` | **`409`** if one already exists |
| PATCH | `/property` | `200` `PropertyResponse` | `404` if none |
| DELETE | `/property` | `204` | soft delete; `404` if none |

One active property per file (DB `unique(loan_file_id)`); a second create returns
`409`.

## Lenders (LP-32)

| Method | Path | Auth | Success | Notes |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/lenders` | yes | `200` `LenderSummary[]` | company-scoped; empty list when none |

`LenderSummary` = `{ id, name, supported_programs }`. Company-scoped (only the
caller's lenders), active only, ordered by name; no pagination (a company has few
lenders). Populates the intake-form lender dropdown; lenders are seeded later (LP-48),
so an empty list is a normal, graceful state.

## Overview reads (LP-34) — needs & activity, nested under a file

Two read-only lists for the file overview tab, both **nested under the file** and
transitively company-scoped via the same `ScopedLoanFile` gate as borrowers/property
(the parent file is resolved with the caller's company **first** → `404` if it isn't
theirs; ADR-110).

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| GET | `/api/v1/loan-files/{file_identifier}/needs` | `200` `NeedsItemPublic[]` | active items, **blocking-first** then oldest |
| GET | `/api/v1/loan-files/{file_identifier}/activity` | `200` `ActivityPublic[]` | recent first, capped (20) |

- `NeedsItemPublic` = `{ id, title, category, needs_type, status, priority, origin,
  borrower_id, satisfied_by_document_id, created_at }`. The needs list is **provisional**
  template data (LP-30, pending domain refinement) — shown as-is, not authoritative.
- `ActivityPublic` = `{ id, activity_type, summary, actor_user_id, detail, created_at }`.
  `detail` carries only safe structured data (e.g. status from/to, needs count) — never
  SSNs or tokens.
- Both 404 for an out-of-company file (tenant-safe, tested). No raw SSN / `inbox_token`.

## Intake (LP-32) — client orchestration, no new endpoint

The new-file intake form composes existing endpoints in sequence (Option A, file-first;
ADR-105) — there is **no** atomic intake endpoint:

## Documents (LP-36) — nested upload/list, flat get/download/delete

Where documents enter the system. Upload and list are **nested** under a loan file;
single-document operations are **flat** under `/documents/{id}`. The bytes live in the
LP-35 storage backend (the `Document` row holds only an internal `storage_path`, **never
exposed**); the only way to fetch them is the auth'd `/download` route. Uploaded documents
start at status **`pending`** (the processing pipeline, LP-42, picks them up). Relevant
ADRs: **ADR-114** (URL shape + flat-route scoping), **ADR-115** (upload validation +
auth'd-download), **ADR-116** (soft-delete preserves bytes, PENDING on upload).

| Method | Path | Success | Notes |
| --- | --- | --- | --- |
| POST | `/loan-files/{file_identifier}/documents` | `201` `DocumentResponse[]` | multipart, **one or many** files; nested (file gate) |
| GET | `/loan-files/{file_identifier}/documents` | `200` `DocumentResponse[]` | the file's active documents, newest-first |
| GET | `/documents/{document_id}` | `200` `DocumentDetailResponse` | + current extraction (or `null`); flat scoping |
| GET | `/documents/{document_id}/download` | `200` bytes | auth'd byte stream; `Content-Disposition: attachment` |
| DELETE | `/documents/{document_id}` | `204` | soft delete; **stored bytes preserved** |

### Two scoping shapes (the crux)

- **Nested routes** (upload/list) scope-check the parent file **first** via the
  `ScopedLoanFile` gate (LP-29) — a Company B user uploading to / listing a Company A file
  gets `404`.
- **Flat routes** (get/download/delete) — a document has **no `company_id`** of its own, so
  `get_document_for_company` resolves it by **joining `Document → LoanFile`** and filtering
  on the file's company. A Company A user can **never** get/download/delete a Company B
  document by id (`404` each — indistinguishable from missing; anti-enumeration). A flat
  route never loads a document by id alone. `company_id` always comes from `current_user`.

### Upload validation

Each file is validated before any are stored (an invalid file rejects the **whole
request**, so a batch is all-or-nothing and never partially persisted):

- **Size** — max **50 MB**; read in chunks and aborted at the cap (an oversized upload is
  never fully buffered) → **`413`**.
- **Type** — `application/pdf`, `image/jpeg`, `image/png` only, by **content-type allowlist
  AND magic-byte signature** (`%PDF`, `\x89PNG…`, `\xff\xd8\xff`); the detected type must
  match the declared one, so content-type spoofing is rejected → **`415`**. Pairs with the
  LP-35 extension sanitization (defense in depth).

### Schemas

- **`DocumentResponse`** — `id`, `loan_file_id`, `original_filename`, `mime_type`,
  `file_size_bytes`, `document_type`, `category`, `classification_confidence`, `status`,
  `upload_source`, `uploaded_by_user_id`, `created_at`, `updated_at`. **No `storage_path`.**
- **`DocumentDetailResponse`** — `DocumentResponse` + `current_extraction`
  (`ExtractionPublic` `{ id, version, extracted_data, extraction_status, model_used,
  created_at }`) or `null` (always `null` until extraction runs, Phase 2).

## Intake (LP-32) — client orchestration, no new endpoint

The new-file intake form composes existing endpoints in sequence (Option A, file-first;
ADR-105) — there is **no** atomic intake endpoint:

1. `POST /loan-files` (the gate — on failure the form stays, retryable).
2. `POST /loan-files/{id}/borrowers` (primary borrower) — best-effort.
3. `POST /loan-files/{id}/property` — best-effort.

If the file is created but step 2/3 fails, the client navigates to the file anyway with
a non-blocking warning (a created DRAFT with partial info is usable); no rollback. The
SSN is sent once to the borrower endpoint (encrypted at rest), returned only as
`masked_ssn`, and never logged.

## What's next

- **LP-30** — loan file service layer (consolidating/extending the service functions).
- Later — loan-file frontend pages (list + detail) in the LP-27 shell; documents; needs
  list, verification, and conditions APIs.
