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

## Review pass — a constraint that enforced nothing, and the guard that could not see it

Reviewed on request from the session running the epic. The hand-off's own
suspicion about the unique constraint was right, and the guard gap it noticed in
passing turned out to be hiding two other tables.

### The name constraint enforced nothing it documented

`UniqueConstraint("owner_user_id", "name", "deleted_at")`. In Postgres a unique
key containing a NULL treats every such row as distinct, so two LIVE views —
both with `deleted_at` NULL — never collided. Proven before changing anything by
inserting the duplicate: two rows, same owner, same name, no error.

Replaced with a partial unique index over `(owner_user_id, name) WHERE
deleted_at IS NULL`, which is what the comment described and what
`uq_findings_loan_file_rule_subject` already uses for the same reason. It still
frees the name on delete — both halves are now asserted, one test per half.

Migration `e2c9f47a80b1` recreates it under the same name, so nothing else has to
learn a new one.

### The drift guard could not see a missing view for a whole table

Raised in the hand-off as worth knowing independently, and it was.
`test_no_model_column_drifts` walks VIEWS and asks what columns they are missing,
which by construction cannot see a table that has no view at all.

Added the other direction. It immediately found **two** tables shipped without a
readonly view — `needs_prose` and `finding_prose`, both LP-634's caches —
neither of which is a small omission: both hold model-authored prose about a
finding or a need, which names creditors and amounts. `saved_views` would have
been the third. Both now exposed with their prose columns scrubbed, matching
`needs_items.reasoning`, which goes through `scrub` for exactly that reason
(migrations `f3a1b62c95d7`, `a8d3f70b41c2`).

### The guard was green alone and red in the full suite

Worth recording, because the first version of the new check had the defect it
was written to prevent. `Base.metadata` knows only the models something has
imported, and `app/models/__init__.py` does not export all of them —
`finding_prose` registers only when a test that uses it runs. So the check
reported one missing table in isolation and two in the full suite: an answer that
depended on test ordering.

`_all_tables()` imports every module under `app/models/` first. The
pre-existing `test_every_view_targets_a_real_table` had the same flaw pointing
the other way — it would have called a perfectly real table unknown — and now
uses the same helper.

### Nothing asserted that the readonly view scrubs

Every other assertion about a view checks a column is MENTIONED before the FROM.
An unscrubbed `SELECT filters` mentions it too, so "exposed" and "safe" are
different claims and only one was being made. A saved view's filter payload is
user-authored — a `search` string is whatever someone typed, which is exactly
where an identifier ends up.

The new test runs the SHIPPED view SQL over a real row rather than a restatement
of it: create the company, user and view, install the scrub functions, execute
the migration's own projection, and assert an SSN in the filter payload comes
back redacted. Mutation-checked by removing `scrub_json` from the migration.

Two things that cost a few minutes and are worth knowing before writing another
of these: `_view_bodies()` returns the SELECT BODY only, with `{_SCHEMA}` still a
literal placeholder — both deliberate, because that is what lets the guard read
migrations as text without importing `alembic.op`.

### Confirmed, not changed

- **`sa.JSON` rather than JSONB is right here.** It is the tree's majority
  convention (JSONB appears only on `finding_event.payload` and one `finding`
  column). JSONB earns its cost when the column is queried INTO; `filters` is
  stored and returned whole. Worth revisiting the day a view is searched by its
  filter contents, not before.
- **The PATCH ownership 404 is indistinguishable from the scoping 404** — more
  strongly than "verified equivalent". Both branches `raise _NOT_FOUND`, the
  *same module-level exception instance*, so the status and body cannot diverge:
  there is no second object to drift. The remaining difference is one Python
  attribute comparison, which is not a timing oracle over a network.
- **File ownership really does block LP-UI-014's third criterion.** Checked
  rather than taken on trust: `LoanFile` has no assignment column, the only
  "assign" mention in the model is about the *lender*, and `loan_officer_name`
  carries the comment "the LO is not a system user". So "My files" and
  "Unassigned" have nothing to filter on. `extra="forbid"` is the right call —
  a 422 says the filter is not supported, where silently dropping `assigned_to`
  would give a view that looks configured and returns everything. File
  assignment is a feature, and LP-UI-014 should ship without those two views
  rather than fake them.

### Verification

`ruff`, `ruff format`, `mypy` clean over 447 files; **5,961 pass** (from 5,956)
with the two known `.env` failures. Every fix mutation-checked:

| mutation | result |
| --- | --- |
| revert to the `UniqueConstraint` | 1 test fails |
| remove the `needs_prose` view migration | guard fails |
| drop `scrub_json` from the saved-views view | 1 test fails |

Both new migrations were checked by emitting their SQL offline, and the partial
index reads `CREATE UNIQUE INDEX uq_saved_views_owner_name ON saved_views
(owner_user_id, name) WHERE deleted_at IS NULL`.
