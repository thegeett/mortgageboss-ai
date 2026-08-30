# LP-UI-011 — Delete the `/loan-files` stub, and decide the root route

- **Ticket:** LP-UI-011 — remove the placeholder routes
- **Epic:** Ledger redesign → Epic B (Primitives and shell) — the last of six
- **Status:** Completed
- **Date:** 2026-08-30
- **Scope note:** widened by [`AMENDMENTS.md`](../design/ledger/AMENDMENTS.md) to
  cover the root route as well. **ADR-390** records the decision.

## Summary

Two routes existed only to say "not built yet", and both had outlived that.

`/loan-files` was a stub reading *"Loan-file management arrives in the next phase
(Epic 4). This is where your files will live"* — true when written, still
shipping long after Epic 4 delivered the dashboard with its search, filters and
pipeline table. The rail therefore offered two destinations: the real list, and
a promise that the real list was coming.

`/` — the first URL anyone types — was a 199-line developer splash with a
backend health check and dependency rows for Postgres and Redis. Never a
processor screen, deliberately never designed.

Both now redirect to `/dashboard`. The health page **moved rather than being
deleted**, to `/dev/health` beside `/dev/extraction-bench`.

## What Changed

- `app/(protected)/loan-files/page.tsx` — the stub becomes `redirect("/dashboard")`.
  **`/loan-files/[id]` is untouched**; the prefix is still the file workspace.
- `app/page.tsx` — 199 lines to a redirect.
- `app/(protected)/dev/health/page.tsx` (new) — the splash, unchanged, relocated.
- `lib/navigation.ts` — "Loan Files" removed from `NAV_ITEMS`; the pipeline
  context section removed (see Decisions).
- `lib/navigation.test.ts` — updated; `lib/navigation.redirects.test.ts` (new).
- `decisions.md` — ADR-390.

## Verification

**The route table**, from `pnpm build`: `/` and `/loan-files` are now 152 B
each — the size of a redirect — `/dev/health` is present at 4.74 kB, and all
seven `/loan-files/[id]/…` routes are unchanged.

**Followed in a browser**, signed in as a processor:

| requested | landed on |
|---|---|
| `/` | `/dashboard` |
| `/loan-files` | `/dashboard` |
| `/dev/health` | `/dev/health` (renders) |
| `/loan-files/<id>` | unchanged |

**The rail** now offers the wordmark and `Dashboard` — no "Loan Files".
Administration stays role-gated and is correctly absent for a processor.

**No dead links:** every `href` in `lib/navigation.ts` still resolves to a real
route, re-checked against the filesystem as in LP-UI-008.

**CI.** biome, tsc, 566 tests (up from 563), build — green. Frontend-only
ticket; no backend files changed.

## Decisions

- **`/` goes to `/dashboard`, not `/login`.** This keeps one rule instead of
  two: the protected layout is the only place that decides who is allowed in,
  and it already redirects an unauthenticated visitor to `/login` once the
  silent refresh settles. Routing `/` straight to `/login` would duplicate that
  judgement and would bounce an already-signed-in user through a screen they do
  not need. Recorded as ADR-390.
- **The health page moved rather than being deleted.** It is genuinely useful,
  and `/dev` is already where developer-only surfaces live. The cost is that it
  now requires a session; a developer checking whether the stack is up should
  use the API's own unauthenticated `/health`, which is the better tool anyway.
- **The dashboard's context column is gone for now.** `PIPELINE_SECTION` held
  two items, one of which was the stub. Removing it leaves a single link to the
  screen you are already on, and an empty 216px column is worse than none. Its
  real contents are LP-UI-012's saved views — which is what the ticket says the
  pipeline column is for.
- **The redirects are pinned by a test.** Both are now one-line files, which is
  exactly the kind of thing that gets tidied away by someone who cannot see why
  it exists — and a redirect that silently becomes a 404 is invisible until a
  user follows an old bookmark.

## Assumptions

- **Assumed** no external bookmarks depend on `/` rendering the health page. It
  was a development aid, and the redirect preserves the URL either way.

## Files

- `app/page.tsx`, `app/(protected)/loan-files/page.tsx` (both now redirects)
- `app/(protected)/dev/health/page.tsx` (new — relocated)
- `lib/navigation.ts`, `lib/navigation.test.ts`,
  `lib/navigation.redirects.test.ts` (new)
- `decisions.md` — ADR-390

## Review pass — what the removed nav item was still doing

Reviewed on request from the session running the epic. Four defects, and three
of the ticket's own judgement calls confirmed.

### Nothing marked the rail while you were inside a file

Removing "Loan Files" from `NAV_ITEMS` is right — it pointed at a stub and
`/loan-files` now redirects to the dashboard, so two rail destinations meant one
screen. But that item was also the only thing marking the rail in the FILE
workspace, and nothing replaced it. Measured on `/loan-files/abc`: zero rail
items carry `aria-current="page"`, and `Header`'s `current` resolves to
`undefined`, so the top bar falls back to the wordmark.

That is the screen the product is mostly used on. A persistent nav that shows
nothing current there is worse than one destination too many.

`NavItem` now takes an optional `owns` — extra path prefixes a destination
represents without linking to — and Dashboard owns `/loan-files`. ADR-390 says
the dashboard IS the loan-file list, so a file is inside its territory; `owns` is
that sentence made true in the rail. `isNavItemActive()` replaces the bare
`isActivePath(item.href)` in both `IconRail` and `Header`.

### The sidebar toggle controlled nothing on the primary screen

Raised in the hand-off, and it is a defect. With `PIPELINE_SECTION` gone,
`contextSection("/dashboard")` is null and `ContextColumn` renders nothing — but
the rail's toggle still rendered, still took focus, and still announced
`aria-expanded`. A disclosure button that discloses nothing is a control that
lies, and after this ticket that is the dashboard, not an edge case.

The button is now rendered only where there is a column, and ⌘B is gated the same
way through a new `enabled` option on `useNavCollapse`. Gating both matters: a
shortcut that silently flips hidden state from a screen that cannot show the
result is just an invisible one, and it would disagree with the affordance beside
it. Hidden rather than disabled — the rail is a column of icons behind a spacer,
so one fewer at the bottom reads as "nothing to toggle here" without adding a
dead stop to tab through.

This also simplifies the LP-UI-008 review's fix: `aria-controls` was conditional
because the column might not exist, and now the button itself does not exist in
that case, so the attribute is unconditional again.

### The redirect test could not fail

Correctly identified in the hand-off, and there is a better idiom. Asserting
`readFileSync(...).toContain('redirect("/dashboard")')` passes on the string
appearing anywhere — a comment, a disabled branch, a copy-pasted docstring — so
it could not tell a page that redirects from one that mentions redirecting.

The tests now CALL the pages with `redirect` mocked, which is the supported way
to assert on the destination: the real one throws `NEXT_REDIRECT` by design, and
the destination is the whole behaviour. Mutation-checked — pointing `/` at
`/login` fails, where before it would not have. A third case asserts neither page
returns markup, since a redirect page that also renders is one that flashes
content before it moves. The health-page check imports the route module rather
than grepping it for a function name.

### Confirmed, not changed

- **Moving the health page from a public route to a protected one is right, and
  is a small security improvement rather than a neutral move.** It rendered
  backend health and dependency rows to anyone who loaded `/`, signed in or not.
  The API already exposes its own unauthenticated `/health`, `/health/live` and
  `/health/ready` for the uses that genuinely need no session, so nothing is lost
  by putting the UI behind auth. Worth noting separately: `/dev/*` carries no
  role gate, so any authenticated user reaches it — that is the existing
  convention (extraction-bench was already there) and not this ticket's to
  change, but it is a ticket someone should write.
- **Removing `PIPELINE_SECTION` rather than leaving a one-item column.** Right. A
  column whose only content is a link to the screen you are already on is noise
  with a border.
- **Changing `contextSection("/loan-files/new")` from "Pipeline" to null.**
  Flagged in the hand-off as "changing a test to match my code", which is the
  move that hides regressions — but this one is honest. The section it asserted
  no longer exists, so the old expectation could not be kept under any
  implementation; and the property the test is actually for, that `/loan-files/new`
  is not treated as a FILE, is still asserted. A test updated because the
  behaviour deliberately changed is different from a test relaxed until it
  passed, and the tell is whether the load-bearing assertion survived. It did.

### Verification

`tsc` clean, `biome` clean over 218 files, 577 tests (from 566), build compiles.
The route table still shows `/` and `/loan-files` at 152 B — redirects, not
pages — and `/dev/health` present at 4.74 kB. Every fix mutation-checked:

| mutation | result |
| --- | --- |
| drop `owns` from Dashboard | 1 test fails |
| revert the rail to `isActivePath(item.href)` | 1 test fails |
| render the toggle unconditionally | 1 test fails |
| point the root redirect at `/login` | 1 test fails |

The second of those is the one worth recording. It passed at first: the new
`isNavItemActive` tests covered the helper, leaving `IconRail` free to go on
calling `isActivePath(item.href)` with nothing noticing. The helper was never
what regressed — the wiring was — so the assertion moved onto the rendered rail.
