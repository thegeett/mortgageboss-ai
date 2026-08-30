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
