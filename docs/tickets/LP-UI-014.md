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

## Review pass — a URL that could break the page it describes

Reviewed on request from the session running the epic. Four defects, and both
judgement calls confirmed.

### An unknown status in the URL broke the dashboard

`readPipelineUrl` cast `params.getAll("status")` to `LoanFileStatus[]`. The
endpoint types it as `list[LoanFileStatus]`, so FastAPI answers an unrecognised
one with a **422** and the dashboard renders its error state. A URL here is a
paste-able, bookmarkable artifact — the entire premise of putting filter state in
it — so a typo in one should drop the filter, not break the screen.

The sharper case is the one nobody types: the day a status is retired, every
saved view and every bookmark carrying it starts failing rather than quietly
widening.

Filtered rather than cast, against `LOAN_FILE_STATUS` — the map LP-UI-005 already
made exhaustive over the union. Not a second list of statuses; a second list is
how the two drift.

### Changing the filter left you on page 3 of a two-row result

`setPage(1)` was keyed on `urlState.search` alone. Selecting a saved view changes
`?view=` and `?status=`, not `q`, so switching from "All files" on page 3 to a
view with two matches left `page` at 3 — an empty table under "Showing 41–60 of
2". Now keyed on the serialised filter, so statuses and the selected view count.

Adjusted **during render** rather than in an effect. React documents the pattern
for exactly this, and it is not a style preference here: an effect resets after a
paint, so the wrong page is fetched and rendered first and the corrected one
arrives behind it. It also takes the reset off the effect graph, which answers
the hand-off's own worry — the search sync is now the only effect writing state,
so there is no second one to feed it.

On the loop the hand-off could not reproduce: it converges, and the trimming
asymmetry is why it looks like it should not. `debouncedSearch` is trimmed and
`urlState.search` is not, so `?q=%20smith%20` does take one extra `replace` — and
then settles, because `writePipelineUrl` trims too and the second pass agrees.
`?q=%20%20` settles the same way, via the empty string. Traced rather than
assumed, but it is one extra history-free navigation, not a cycle.

### Two parsers of one URL

The dashboard and the context column each built a `URLSearchParams` and parsed
it. The same many-producers shape flagged twice before, and the cost here is only
that they can drift — which is enough. `usePipelineUrl()` is now the one reader,
memoised on the query string.

### `view-url.ts` had six tests and its consumer had none

The hand-off named this as the wrong half to have covered, and it is exactly
LP-UI-011's lesson: a helper stays green while the component stops calling it.
Seven tests on the rendered `SavedViews`, including two properties worth naming:

- **"All files" is not current on a hand-edited filter.** The defect the ticket
  caught on the way; now it cannot come back.
- **A failed request says "unavailable", not "No saved views yet."** Those are
  different facts. Telling a processor they have no saved views when the request
  failed is a lie about their own data.

Plus three dashboard-paging tests, on the rendered page rather than the reset
logic, including one asserting it does NOT reset when the URL is unchanged — a
reset keyed on object identity would send the reader back to page 1 every render.

### Confirmed, not changed

- **`useSavedViews` does not run on every route with a column.** `SavedViews` is
  behind `pathname === "/dashboard"` in `ContextColumn`, so the hook mounts only
  there. Checked, because the hand-off was right that it would have been a real
  cost if true.
- **`router.replace` for the debounced search is right**, and the consequence the
  hand-off worried about is the intended one. A keystroke is not a destination;
  filling the back stack with `?q=s`, `?q=sm`, `?q=smi` makes the back button
  useless, which is a worse loss than not being able to reverse a search by
  going back. Saved views navigate with a real link and so DO land in history,
  which is the coarse-grained half that should.
- **Deleting `FILTER_PILLS` / `statusesForFilter`.** Genuinely orphaned —
  nothing under `app/`, `components/` or `lib/` references either. Recording the
  groupings in the ticket as views worth seeding is the right disposal.
- **Moving the "toggle is not rendered where there is no column" test.** It
  preserves what it was for. The property is "a disclosure button that discloses
  nothing is a control that lies"; `/dashboard` was only ever an EXAMPLE of a
  column-less route, and it stopped being one when this ticket gave it saved
  views. Moving it to `/dev/extraction-bench` keeps the property with a valid
  example, and the added case asserting the toggle IS present on the dashboard is
  a better test than the original — it pins both directions where the original
  pinned one.
- **`_apply_filters` is genuinely shared.** Both `count_loan_files` and
  `list_loan_files` build on it, so a count cannot drift from the list it counts.
  This is the LP-UI-013 lesson applied before the fact rather than after, which
  is the first time in this epic that has happened.

### Verification

Frontend `tsc` clean, `biome` clean over 227 files, **611 tests** (from 597),
build compiles. Backend unchanged by this review and still green. Every fix
mutation-checked:

| mutation | result |
| --- | --- |
| revert to the unvalidated status cast | 2 tests fail |
| key the page reset on search alone | 2 tests fail |
| mark "All files" current on a hand-edited filter | 1 test fails |
| show "no saved views yet" on a failed request | 1 test fails |
