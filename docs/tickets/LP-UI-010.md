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

## Review pass — a column the readonly view never learned about

Reviewed on request from the session running the epic. Five defects, one of them
already failing in the suite at the commit.

### `users.density` was invisible to the readonly views — and the suite said so

`test_no_model_column_drifts` was **red at 00fda59**. Its whole job is this: a
model column must be exposed by its readonly view or listed in the test's
`EXCLUDED` map, never neither, so the decision gets made while it is cheap. The
new column was neither.

It was missed because the pre-commit check ran 75 backend tests; this one is in
`tests/test_readonly_query.py`, outside that selection. The full suite is 5,932.

Exposed rather than excluded. `EXCLUDED["users"]` holds credentials and
identifiers — `hashed_password`, `email`, `first_name`, `last_name` — and density
is neither: a bounded three-value ergonomic preference with no identifying
content, whose sibling `default_aggression_level`, the other per-user preference
enum, has been in the view since C7.

Fixed in a **new** revision (b7f4a2d19c63) rather than by editing aaf8b36c61fa,
which is already committed: an edited migration is only correct in the world
where nothing has applied it yet, and a new one is correct in both. It follows
LP-631's shape — drop, recreate, re-grant, because a dropped view takes its grant
with it — and recreates rather than `CREATE OR REPLACE`, which in Postgres can
only APPEND a column and would have stranded `density` after `deleted_at`
instead of beside the preference it belongs with.

One trap worth recording, because the first attempt walked into it. The drift
guard reads later migrations as TEXT and treats everything before `def
downgrade(` as the live definition — precisely so a rollback's `CREATE VIEW` does
not win. Defining the old view as a module-level constant puts it above that
split, so the guard read the ROLLBACK shape as current and still reported
`density` unexposed. Its own docstring warns about this; a module-level constant
walks straight past the warning. The old definition is inlined inside
`downgrade()`.

### The write path had three defects, all in `choose`

- **A PUT per click, including re-picking the density already active.** Flagged
  in the hand-off; guarded. `pickLevel` in VerificationPanel already guards its
  own dial the same way, so the precedent was in the file next door.
- **A failed write left the screen claiming a preference the database does not
  hold.** The DOM and cookie change optimistically and nothing reverted them, so
  the change "worked" and then silently reverted on some later load, when the
  reconcile pulled the server's older answer. `onError` now snaps it back — the
  honest version of the same outcome, and immediate.
- **The reconcile could revert the choice while the write making it true was
  still in flight.** The effect depends on the mutation's pending flag, so it
  re-ran the moment the PUT started, read the server's still-old value, and
  reverted. Guarded on `isPending`. This was not a narrow race — it was the
  common path.

### `density` state was read as truth where the attribute is the truth

`choose` compared against the React value, which starts at the default and only
catches up in an effect, so on a first render it answers "compact" for a relaxed
user. `currentDensity()` reads `data-density` — the attribute the CSS hangs off,
and therefore what is actually on screen. The React value stays a mirror for
rendering the menu's checkmark.

### The tests the hand-off asked for

Both gaps it named, filled and mutation-checked:

- `tests/api/test_preferences_endpoints.py` (7): both fields at their defaults,
  density-alone preserves thoroughness, thoroughness-alone preserves density,
  both together, an empty body, an unknown density rejected at 422, and an
  explicit null treated as omission. The partial update is the reason both fields
  became optional and nothing was asserting it — that is a data-loss shape.
- `hooks/use-density.test.ts` (8), mocked at the TRANSPORT rather than at the
  preferences module's exports: `usePreferences` and `useUpdatePreferences` reach
  `fetchPreferences`/`updatePreferences` through module-internal references, so
  mocking those exports changes nothing the hooks actually call. The first
  version did exactly that and three tests failed for the wrong reason.

### Checked and found correct

- **The migration.** Verified by emitting the SQL offline rather than by reading
  it: `ALTER TABLE users ADD COLUMN density VARCHAR(32) DEFAULT 'compact' NOT
  NULL` followed by `ALTER TABLE users ADD CONSTRAINT ck_users_rowdensity CHECK
  (density IN (...))` — the same shape, and the same constraint-naming
  convention, as the LP-79 precedent for the identical pattern. The
  `server_default` matches `DEFAULT_DENSITY.value`, so it cannot fight the model
  default, and `drop_column` takes the constraint with it on downgrade.
- **`UserPreferencesUpdate` accepting `{}`.** Left as-is: "only the provided
  fields change" and none were. Pinned by a test so it is a decision.
- **The other `updatePreferences` caller.** `verification-panel.tsx` sends only
  `default_aggression_level`, so the partial shape is right there too.
- **The reconcile logic itself.** Correct including the compact case, where the
  attribute is absent rather than set to a value.

### Two things for someone else

- **Two backend tests fail on this machine and are not this ticket's.**
  `test_model_selection_lp457.py` asserts `anthropic_model_analysis ==
  "claude-haiku-4-5"`, which is the code default, but the local `.env` sets
  `ANTHROPIC_MODEL_ANALYSIS=claude-sonnet-4-5` and settings load from it. A local
  environment difference, not a regression — but a test that a developer's `.env`
  can turn red is worth revisiting.
- **The model-vs-database drift is still open** and is a DIFFERENT thing from the
  drift guard above: this one is the local database lagging the models, which is
  what made `--autogenerate` propose eighteen destructive operations. Not touched
  here, correctly. Worth its own ticket before someone accepts an autogenerated
  migration without reading it.

### Verification

Frontend: `tsc` clean, `biome` clean over 216 files, 563 tests (from 555), build
compiles. Backend: `ruff` clean, `ruff format` clean, `mypy` clean over 443
files, **5,930 pass** with the two `.env` failures above. Every fix
mutation-checked:

| mutation | result |
| --- | --- |
| remove the re-pick guard | 1 test fails |
| remove the `onError` revert | 1 test fails |
| reconcile while a write is in flight | 1 test fails |
| hoist the rollback view to module level | drift guard fails |

Two of those mutations passed on the first attempt and the tests were rewritten
until they did not: the re-pick test asserted "not called" synchronously, before
the mutation's request happens a microtask later, so it passed with the guard
deleted; and the in-flight test never had preferences loaded, so the reconcile
bailed at its own null check before reaching the code under test.
