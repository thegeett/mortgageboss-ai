# LP-UI-015 — Saved views (backend)

- **Ticket:** LP-UI-015 — company-scoped saved views
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Blocks:** LP-UI-014 (saved views, frontend)

## Why this came before LP-UI-014

The suggested order lists 014 next, but 015's own header says **"Blocks 014"**
and there was no saved-view backend of any kind — no model, no endpoint, no
table. Building the UI first would have meant writing it against an API that did
not exist and rewriting it a day later, so 015 was taken first. 014 is now
unblocked.

## What Changed

- **`app/models/saved_view.py`** (new) — `SavedView`, `SavedViewSort`.
  Company-scoped, user-owned, soft-deletable, with a JSON filter payload.
- **`app/schemas/saved_view.py`** (new) — create / update / public shapes and
  `SavedViewFilters`, which **validates** the payload rather than storing
  whatever arrives.
- **`app/api/saved_views.py`** (new) — list, create, patch, delete.
- **Migrations** `c1e5a97b3d42` (the table) and `d4b8e2f61a05` (the
  `readonly.saved_views` view), both hand-written.
- **`frontend/lib/api/saved-views.ts`** (new) — the client 014 will use.
- **`tests/api/test_saved_views_endpoints.py`** (new) — 9 tests.

## The finding that matters: "current user" cannot be built

LP-UI-014 asks for **"current user" as a filter value so one shared view ("My
files in processing") serves the whole team**, and the Pipeline mockup shows
saved views called *"My files 18"* and *"Unassigned 2"*.

**A loan file has no owner.** Checked before designing the payload, not after:

- no `assigned_to_user_id`, `owner_user_id` or `processor_id` on `LoanFile`;
- no association table joining `users` to `loan_files`;
- `loan_officer_name` / `loan_officer_email` are free text for an **external**
  contact — the loan officer at the originator, not a processor in this company;
- `uploaded_by_user_id` is per **document**, and says who uploaded a file, not
  who owns the loan.

So "my files" has nothing to resolve against, and neither does "unassigned".
`SavedViewFilters` therefore carries `statuses` and `search` — exactly what
`list_loan_files` can actually apply — and sets `extra="forbid"`, so a client
sending `{"assigned_to": "current_user"}` gets a 422 instead of a view that
silently ignores half of what it claims to filter on.

**File assignment is its own feature**, not a line in a saved-views ticket: it
needs a column, a migration, an assignment UI, a default for the ~19 existing
files, and a decision about whether assignment is one processor or several.
Until it exists, LP-UI-014's third acceptance criterion ("Current user resolves
per viewer") cannot be met, and the mockup's first two saved views cannot be
built. Raised rather than stubbed.

## Verification

**9 endpoint tests, all mutation-checked.** Each of the ticket's criteria was
broken deliberately to confirm the test fails:

| mutation | test that caught it |
|---|---|
| drop `company_id` from the list query | tenant isolation |
| drop `deleted_at.is_(None)` | a soft-deleted view never reappears |
| let anyone edit a shared view | visibility is not ownership |
| partial update resets omitted fields | updating one field leaves others alone |

**Tenant isolation returns 404, not 403** — on list, patch and delete. A 403
confirms the row exists, which is the thing the isolation is for.

**The readonly view.** A new base table with no `readonly.*` view is *not*
caught by `test_no_model_column_drifts` — that guard walks the columns of tables
which already have a view, so a whole table can go missing silently. Added
deliberately, by the same reasoning the LP-UI-010 review used for
`users.density`: `EXCLUDED` is for credentials and identifiers, and a saved view
holds neither. `filters` goes through `readonly.scrub_json()`.

**CI.** ruff, ruff format, mypy clean over 447 files. Full backend suite run.

## Assumptions and decisions

- **Decided** the filter payload is validated JSON, not columns. The set of
  things a processor filters on will grow, and a column per filter means a
  migration per idea — but JSON here means *extensible*, not *unchecked*.
- **Decided** the unique key is `(owner_user_id, name, deleted_at)`. One person
  should not have two views of the same name; two people in a company may; and
  including `deleted_at` means deleting a view frees its name.
- **Decided** shared views are readable company-wide and writable only by the
  owner. A processor can use a colleague's "Blocked to submit" without changing
  it underneath them.
- **Decided** `is_mine` is computed server-side. The client needs it to decide
  whether to offer edit and delete, and computing it once beats every consumer
  re-deriving it.
- **Assumed** the four sort options (`attention`, `updated_desc`, `updated_asc`,
  `amount_desc`) are enough. `attention` is the pipeline default from LP-UI-013.
  Note the LP-UI-013 finding still stands: attention ordering is applied
  client-side over one page, so a view sorted by attention inherits that limit.
- **Noted** `--autogenerate` was not used. It proposes eighteen unrelated
  destructive operations on this repo (see the LP-UI-010 migration docstring),
  so both migrations here are hand-written.

## Files

- backend: `app/models/saved_view.py`, `app/schemas/saved_view.py`,
  `app/api/saved_views.py`, `app/models/__init__.py`, `app/main.py`,
  two migrations, `tests/api/test_saved_views_endpoints.py`
- frontend: `lib/api/saved-views.ts`
