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
