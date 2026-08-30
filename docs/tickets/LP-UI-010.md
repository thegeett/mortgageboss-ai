# LP-UI-010 — Density preference, persisted

- **Ticket:** LP-UI-010 — per-user row density
- **Epic:** Ledger redesign → Epic B (Primitives and shell)
- **Status:** Completed
- **Date:** 2026-08-30

## Summary

`[data-density]` on `<html>` drives `--row-h` / `--row-px`, which LP-UI-001
shipped and LP-UI-007's table already reads — so every dense surface follows one
attribute. Compact (28px) is the default; comfortable is 36px and relaxed 44px,
all three measured in the browser.

**The first LP-UI ticket to touch the backend.** The ticket is sized S and reads
as frontend work, but "persisted per user" means a column, a migration and a
schema change. Worth noting for the epic's remaining estimates.

## What Changed

**Backend**

- `RowDensity` (`compact` / `comfortable` / `relaxed`) and `DEFAULT_DENSITY` in
  `models/user.py`, plus the `users.density` column.
- Migration `aaf8b36c61fa`, **hand-written** — see Findings.
- `UserPreferences.density` on the read schema; on the update schema **both**
  fields became optional.
- `PUT /users/me/preferences` now applies only the fields that were sent.

**Frontend**

- `lib/api/preferences.ts` — `RowDensity`, labels, the cookie name, and
  `updatePreferences` taking a partial object rather than a bare level.
- `hooks/use-density.ts` (new).
- `app/layout.tsx` — stamps `data-density` from the cookie on the server.
- `components/layout/user-menu.tsx` — the switcher, with a check on the active
  option.
- `verification-panel.tsx` — the one existing caller, updated for the new shape.

## Where the preference lives, and why it lives in two places

The durable store is the **user row in the database**. Density is a per-person
ergonomic preference, so it has to follow the person to another machine; a
cookie alone would make it per-browser, which is the thing the SPEC explicitly
rules out ("per-person, persisted per user — not per view, not per screen").

But the acceptance also says it must **apply on the server render**, and the
server cannot read the database before it knows who is asking — auth resolves
client-side here. So the cookie is the fast path that makes the first paint
right, exactly as `ledger-nav` does for ⌘B in LP-UI-008.

The two can legitimately disagree, when the preference was changed on another
machine. `useDensity` reconciles: the server's answer wins once the preferences
query resolves, and the cookie is rewritten to match.

## Verification

Driven through the real user menu with real mouse events (Radix opens on
pointerdown — a synthetic `.click()` silently does nothing, which is what my
first probe did and why it reported "menu item not found"):

| choice | `data-density` | `--row-h` | measured row | cookie |
|---|---|---|---|---|
| Compact | *(absent)* | 1.75rem | **28px** | *(deleted)* |
| Comfortable | `comfortable` | 2.25rem | **36px** | `comfortable` |
| Relaxed | `relaxed` | 2.75rem | **44px** | `relaxed` |

**Survives reload, applied on the server render.** With relaxed set, a hard
reload was sampled at 1s — before hydration could have corrected anything — and
already read `data-density="relaxed"` with `--row-h: 2.75rem`.

**Persisted per user, and the other preference is intact.** After switching,
the database holds `density = relaxed` **and `default_aggression_level =
balanced`** — the value nobody touched. That is the partial-update fix working;
before it, a density change could not be sent without also sending a
thoroughness.

**No layout thrash.** The grid and its first row were tagged, density flipped,
and both nodes were still there afterwards at the new height (44px → 36px).
A density change is one custom-property write, not a re-render.

**CI.** Frontend: biome, tsc, 555 tests, build. Backend: ruff, mypy, 75 tests.

## Findings raised

1. **`alembic --autogenerate` proposed eighteen destructive operations, and I
   nearly shipped them.** Asked for one column, it produced that column plus:
   `drop_table('finding_prose')`, five `borrowers.current_*` column drops,
   `properties.county`, `documents.borrower_match_note`,
   `verifications.fact_snapshot`, the documents FTS index, and several type and
   server-default changes on `validation_verdicts`.

   The cause is real drift between the models and the local development
   database — the models no longer declare things the database still has. The
   migration is therefore **hand-written**, containing only `add_column` /
   `drop_column`, with the reason recorded in its docstring.

   Two things follow. Nobody should run `--autogenerate` on this repo without
   reading every line of the output. And the drift itself is worth chasing: it
   means the local database and the models disagree about seven objects, so the
   next person to autogenerate meets the same loaded gun.

2. **`UserPreferencesUpdate` did not do what its docstring said.** It read
   "Only the provided fields change" while requiring `default_aggression_level`,
   so there was no way to change one preference without restating the other —
   and restating a stale copy is how a preference silently reverts. Both fields
   are optional now and the endpoint applies only what it was sent.

## Assumptions and decisions

- **Decided** the switcher lives in the user menu, not a view toolbar. It is a
  property of the person; putting it in a toolbar would imply it applies to that
  view only, which is the misreading the SPEC calls out.
- **Decided** compact deletes its cookie rather than writing `compact`. Same
  reasoning the LP-UI-008 review applied to `ledger-nav`: a value that means
  "the default" is a second spelling of "no cookie", and the two eventually
  disagree about which is canonical.
- **Decided** an unrecognised cookie value falls through to compact rather than
  being stamped. The server validates against the two non-default values.
- **Assumed** the `[data-density]` blocks already in `globals.css` are the
  intended scale (36px / 44px). They shipped in LP-UI-001 and this ticket only
  connects a preference to them.

## Files

- backend: `models/user.py`, `schemas/preferences.py`, `api/preferences.py`,
  `alembic/versions/…aaf8b36c61fa…py`
- frontend: `lib/api/preferences.ts`, `hooks/use-density.ts` (new),
  `app/layout.tsx`, `components/layout/user-menu.tsx`,
  `components/file/verification/verification-panel.tsx` (+ its test)
