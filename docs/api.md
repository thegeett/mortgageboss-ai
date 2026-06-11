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

### List — pagination & filtering

Query params: `page` (default `1`, ≥1), `page_size` (default `20`, 1–100),
`status` (optional `LoanFileStatus`). Returns `PaginatedLoanFiles`:
`{ items: LoanFileSummary[], total, page, page_size }`, ordered newest-first
(`created_at desc`), excluding soft-deleted and other companies' files. `total`
is the full count for the filters, independent of the page.

### Summary vs detail

- **`LoanFileSummary`** (list items) — lean: `id`, `display_id`, `status`,
  `loan_program`, `loan_purpose`, `loan_amount`, `lender_id`,
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

## What's next

- **LP-29** — loan-file frontend pages (list + detail) inside the LP-27 shell,
  consuming these endpoints.
- Later — document/borrower/property management endpoints; needs list, verification,
  and conditions APIs.
