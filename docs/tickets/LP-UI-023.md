# LP-UI-023 — New file: MISMO-first intake

- **Ticket:** LP-UI-023
- **Epic:** Ledger redesign → Epic D (Intake and admin)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-006
- **ADR:** none new.

## Summary

Two ways in, honestly ranked — and ranked by **order and weight**, not by
concealment. The MISMO drop leads because it fills in everything the form below
asks for; the form sits under it, complete, for the files that arrive without one.

Manual entry used to be a toggle: choosing it *replaced* the dropzone, and
choosing the dropzone hid the form. That made the second path look like a
different screen and put the primary one behind a decision a processor had to
make before seeing either. Both are on the page now.

## What changed

- `app/(protected)/loan-files/new/page.tsx` — the toggle removed; dropzone,
  divider, the sparse-file line, then the form.
- `components/layout/breadcrumb.tsx` + `lib/navigation.ts` — see below.

**The topbar said "Dashboard" on this page.** `/loan-files/new` is a page, not a
file, so `loanFileIdFromPath` returns null and `Breadcrumb` fell through to its
fallback — which is the *current nav item's* label, and the dashboard `owns`
`/loan-files`. So the one line that says where you are named somewhere else.
It reads "Pipeline / New file" now.

That fix had to land **before** the in-page "Back to dashboard" could go. The
heading and its back link were the duplication LP-UI-016 removed from the file
header, but they were also the only way back from this page: deleting them first
would have been LP-UI-016's own regression — a route you cannot leave.

**The sparse-file rule is stated before the form, not discovered inside it.**
"Only the borrower's first and last name are required" matches the model, and
knowing it up front is what makes a long form approachable rather than a wall of
blanks.

## The three criteria

- **Dropzone is the visual primary; the form is secondary but complete.** Done,
  and pinned by document order rather than by styling — the ranking *is* the
  order, so the test asserts `compareDocumentPosition`.
- **Field errors inline, in Ledger's error style.** Already true and untouched:
  `FormMessage` renders `text-sm font-medium text-destructive` beneath its field,
  and `destructive` is the Ledger token (LP-UI-002).
- **Import still navigates straight to the created file.** Untouched on both
  paths — `MismoUpload` pushes to `/loan-files/{display_id}` on import,
  `IntakeForm` does the same on create.

## Tests

689 frontend (from 686), tsc and biome clean, no backend changes. Three mutations
verified to fail: the form rendered above the dropzone, the sparse-file line
replaced with "complete every field below", and the breadcrumb falling back to the
nav label again.

**Two tests changed because the mechanism they pinned is the thing this ticket
removed.** They asserted that manual entry was hidden by default and that
choosing it hid the upload. The property — MISMO primary, manual secondary — is
unchanged and is what they still assert; only what "secondary" means in markup
moved, from hidden to below. A fourth test pins that neither path is behind a
choice any more, with a positive control beside the two negative assertions.

## Checked, and not a defect

The empty column left of the content is the page centering in a wide viewport, not
a context column failing to collapse: `contextSection("/loan-files/new")` returns
null and `ContextColumn` returns null with it. Measured before changing anything.

## Noted, not built

The mockup gives this screen a context column — "Two ways in" and "What import
fills", listing borrowers, property, loan terms, income/assets/liabilities. It is
not in the acceptance criteria and the column is genuinely absent for this route
rather than broken, so adding one is a design decision rather than a fix. Worth a
ticket if the list of what import fills is meant to be a promise on screen.

## Review pass — the way back now depends on a constant nothing checked

Reviewed on request from the session running the epic. Two gaps closed, three
judgement calls confirmed.

### `NEW_FILE_PATH` was the page's only exit, and nothing pinned it to a route

The sequencing was right, and the check the hand-off asked for passes: the
breadcrumb renders a real `Link` to `/dashboard` via `Trail`, it and the in-page
link removal are one commit, so there is no state in which the page has neither.
Verified in the markup rather than in the ordering, because within a single
commit "which came first" is not a property anything ships.

What it left is a dependency nothing guards. The page's own comment records it —
*"the topbar breadcrumb says 'Pipeline / New file' and links back"* — and the
breadcrumb finds that page by comparing the pathname to `NEW_FILE_PATH`. Rename
the route and the comparison stops matching, the breadcrumb falls through to a
plain heading with no link, and the page becomes a screen a processor can reach
and not leave. Nothing fails, because the dependency lives in a comment and both
the constant and the breadcrumb's test hardcode the same string independently.

That is the same shape as the note in `navigation.ts` that LP-UI-022 turned into
a guard, one screen along. `NEW_FILE_PATH` is now asserted to point at a
directory containing a `page.tsx` — the same instrument, mutation-checked by
renaming the route out from under it.

### The order assertion could not reject the alternative

`compareDocumentPosition` is the right instrument for "ranking is order, not
concealment", and it is a genuine improvement on asserting a toggle. But
`DOCUMENT_POSITION_FOLLOWING` is OR'd with `CONTAINED_BY` when one node is inside
the other, so a manual form nested INSIDE the dropzone satisfied it — which is
not "second", it is "part of the first". The test now also asserts the two are
not nested, which is what lets it reject the state it exists to forbid.

### The two changed tests are honest

The mechanism they pinned — manual entry hidden until chosen, the upload hidden
once it was — is precisely what this ticket removes, so keeping them would have
been keeping a test of a deleted feature. The property survives and is still
asserted: MISMO primary, manual secondary, now expressed as position rather than
visibility. That is the same standard applied to the LP-UI-014 toggle test and
the LP-UI-020 routing inversion — the property is what must survive, the
mechanism is allowed to change under it.

### Confirmed, not changed

- **The near-false-positive.** Measuring before touching is the good version of
  the instinct that has produced most of this epic's defects, and the reasoning
  is right: `contextSection` returns null for this route and `ContextColumn`
  returns null with it, so the empty space is page centring in a wide viewport
  and there is nothing to fix. Recording a non-defect with its evidence is worth
  as much as recording a defect — it stops the next reader re-investigating.
- **Not building the mockup's context column.** Correct. The column is genuinely
  absent for this route rather than broken, so adding one is a design decision
  and not a repair. Worth a ticket if that list is meant to be a promise on
  screen, which is exactly how it was flagged.

### Verification

`tsc` and `biome` clean over 238 files, **690 tests** (from 689), build compiles
into `.next-review` with the dev server left running. No backend changes.

| mutation | result |
| --- | --- |
| rename the new-file route out from under `NEW_FILE_PATH` | 1 test fails |
