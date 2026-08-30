# LP-UI-014 — Saved views (frontend)

- **Ticket:** LP-UI-014 — saved views replace the hard-coded pills
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed, **minus one criterion that cannot be built** (below)
- **Date:** 2026-08-30
- **Mockup:** Pipeline — the left column

## Summary

The four hard-coded filter pills are gone. Saved views live in the context
column with live counts, and the pipeline's filter state now lives in the URL,
so a processor can paste what they are looking at to a colleague.

## What Changed

**Frontend**

- `components/dashboard/saved-views.tsx` (new) — the list, grouped into the
  caller's own views and the company's shared ones, each a **link** rather than
  a button.
- `lib/loan-files/view-url.ts` (new, + 6 tests) — read/write the filter state as
  `?status=…&status=…&q=…&view=…`.
- `app/(protected)/dashboard/page.tsx` — filter state read from the URL.
- `components/layout/context-column.tsx` — renders saved views on `/dashboard`,
  restoring the column LP-UI-011 removed now that it has real contents.
- `components/dashboard/filter-pills.tsx` — **deleted**, with `FILTER_PILLS`,
  `FilterKey` and `statusesForFilter` (see Decisions).

**Backend** (small, and justified — see below)

- `count_loan_files()` in `services/loan_files.py`, built on a new
  `_apply_filters()` extracted from `list_loan_files` so a count cannot drift
  from the list it counts.
- `GET /saved-views?with_counts=true` — one COUNT per view, on one round trip.

## "Live counts" would otherwise have rebuilt what LP-UI-013 deleted

The naive implementation of "views listed with live counts" is one
`useLoanFiles({ pageSize: 1 })` per view — which is *exactly* the `StatsCards`
pattern LP-UI-013 removed, reintroduced through a different door. With six views
that is six requests to render a sidebar.

So counting moved to the server, opt-in via `with_counts`. `_apply_filters` was
extracted rather than reimplemented: a saved view showing "4" beside a list of
six is worse than showing no number at all, and two copies of a filter is how
that happens.

## The criterion that cannot be built

> - [ ] "Current user" resolves per viewer

**Not implemented, and not implementable.** LP-UI-015 established that a loan
file has no owner in the data model — no `assigned_to_user_id`, no association
table; `loan_officer_name` is free text for an external contact and carries the
comment *"the LO is not a system user"*. Confirmed independently in the LP-UI-015
review.

So "My files" has nothing to resolve against, and the mockup's first two saved
views — *"My files 18"* and *"Unassigned 2"* — cannot be built. `SavedViewFilters`
sets `extra="forbid"`, so a client sending `assigned_to` gets a 422 rather than a
view that looks configured and silently returns everything.

**File assignment is its own feature and deserves its own ticket:** a column, a
migration, an assignment UI, a default for the existing files, and a decision
about whether a file has one processor or several.

## Verification

Driven through the real UI against the real API, signed in as a processor.

**Views with live counts, in the context column:**

| view | count | href |
|---|---|---|
| All files | — | `/dashboard` |
| Drafts | **7** | `/dashboard?status=draft&view=67f848d1…` |
| Ready to submit | **1** | `/dashboard?status=ready_to_submit&view=eee735e6…` |

Clicking "Ready to submit" filtered the table to **1 row**, stage `Ready to
submit`, with `aria-current="page"` on the view — and the count matched the
result, which is the thing a wrong count would break.

**The URL round-trips**, opened cold as a colleague would:

| pasted URL | rows | stages | search box |
|---|---|---|---|
| `?status=draft` | 7 | Draft | *(empty)* |
| `?q=Mahesh` | 2 | Draft | `Mahesh` |
| `?status=draft&status=ready_to_submit&q=e` | 7 | Draft, Ready to submit | `e` |

The search box is populated from the URL, so the pasted state is complete rather
than partial.

**CI.** Frontend biome, tsc, 597 tests, build. Backend ruff, mypy, full suite.

## Defect found and fixed during verification

**"All files" was marked current while filters were applied.** `activeViewId ===
null` is true for a hand-edited filter as well as for no filter, so a URL like
`?status=draft` highlighted "All files" — telling the reader they were looking at
everything when they were looking at seven of nine. Now gated on nothing being
filtered.

## Assumptions and decisions

- **Decided** views are links, not buttons. The filter state lives in the URL, so
  a view is a place you can navigate to, bookmark and paste. Buttons would put
  the state back in React where nobody else can see it.
- **Decided** to delete `FILTER_PILLS` / `statusesForFilter` rather than leave
  them orphaned. Their value was the groupings, and those are recorded here as
  the obvious defaults to seed:
  - **Active** — draft, in_processing, ready_to_submit, submitted, clear_to_close
  - **Action needed** — in_conditions
  - **Completed** — closed, withdrawn
- **Decided** the search box keeps local state for what has been typed but not
  committed, and syncs to the URL on the existing 300ms debounce. Pushing a route
  per keystroke would fill the back button with fragments.
- **Decided** `contextSection("/dashboard")` returns a section with **no items**.
  The pipeline's column is data, not routes — but the rail's ⌘B toggle is gated
  on a section existing (LP-UI-011 review), so returning `null` would hide the
  toggle on a screen that now has a column.
- **Noted** a test moved rather than being relaxed: the LP-UI-011 review's "the
  toggle is not rendered where there is no context column" pointed at
  `/dashboard`, which now *has* one. The property is unchanged and still
  asserted — against `/dev/extraction-bench` — and a new case asserts the toggle
  **is** present on the dashboard.

## Files

- frontend: `components/dashboard/saved-views.tsx` (new),
  `lib/loan-files/view-url.ts` (+ test, new), `dashboard/page.tsx`,
  `context-column.tsx` (+ test), `lib/api/saved-views.ts`,
  `lib/loan-files/status.ts` (+ test); `filter-pills.tsx` deleted
- backend: `services/loan_files.py`, `api/saved_views.py`,
  `schemas/saved_view.py`, `tests/api/test_saved_views_endpoints.py`
