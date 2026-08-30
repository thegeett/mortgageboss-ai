# LP-UI-022 — Needs as its own route

- **Ticket:** LP-UI-022
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed, with one acceptance criterion **not built** — see below
- **Date:** 2026-08-30
- **Depends on:** LP-UI-005, LP-UI-009
- **ADR:** none new.

## Summary

The self-maintaining checklist is the product's differentiator and it was the
third section on a page about something else, between the stated financials and
the activity feed. `/loan-files/[id]/needs` now exists, the list lives there at
the top level, and the Overview keeps a compact summary that links through.

`lib/navigation.ts` carried a note from LP-UI-016 saying Needs was *"deliberately
absent… listing it here would ship a link to a 404. It goes in with the route."*
This is that route, so the link went in with it.

On `LF-XKQ3` the Overview now reads: **22 Needs action · 10 Complete · 26 to
review**, with the proposals called out separately — an AI proposal is work to
*decide*, not work to chase.

## What changed

- `app/(protected)/loan-files/[id]/needs/page.tsx` (new).
- `components/file/needs/needs-summary.tsx` (new) — the Overview's compact view.
- `components/file/needs/needs-dashboard.tsx` — out of its `Card`, same lift as
  LP-UI-020's panel.
- `lib/navigation.ts` — Needs joins `fileSections`.
- `app/(protected)/loan-files/[id]/page.tsx` — dashboard → summary.

**The summary counts with `groupNeeds`**, the same function the list groups by. A
summary counting its own way is the LP-UI-013 defect: this number and the list one
click away must not be able to disagree.

## The criterion I did not build

> Batch "request all outstanding" composes one message

**There is no messaging in this product.** Checked properly rather than assumed:

- `/loan-files/[id]/communication` is a `TabPlaceholder` marked **Phase 4**.
- No message or email module exists under `backend/app/api/` or `app/services/`.
- `smtp_host`, `smtp_port`, `smtp_from_email` are defined in `core/config.py` and
  **referenced by nothing** — `grep -rn "settings.smtp" app/` returns nothing.
- The needs API has add, confirm, confirm-coverage, merge-duplicate,
  not-duplicate, not-covered, adjust, dismiss and waive. **There is no request
  endpoint**, and nothing sets `NeedsItemStatus.REQUESTED` — the status and its
  transition exist, unused.

The nearest existing mechanism is the verification tab's `request-docs-bulk`,
which creates **one needs item per document**. That adds to this list; it does not
send anything.

**And a shortcut worth naming so nobody takes it later:** marking the outstanding
needs `REQUESTED` without sending anything would satisfy the words and put a lie
in the data — the status would tell the next processor a borrower had been asked
when nobody had. The status is not the request.

So this is Phase 4 work, and the third acceptance criterion in this epic that
depends on a capability another phase builds (after A17's caching and
LP-UI-018's page anchor).

## The other three criteria

- **New tab in the file sections; the Overview keeps a compact summary that links
  here.** Done, and pinned: a test walks `fileSections` and asserts every href
  resolves to a real directory under `loan-files/[id]`. That is what stops the
  next link going in ahead of its page — the situation the note in
  `navigation.ts` described.
- **Grouping preserved.** `groupNeeds` and `NEEDS_GROUP` are untouched; the route
  renders the same four groups in the same order.
- **Proposed needs show confirm and dismiss, never a silent apply.** Already true
  and untouched — `NeedCard` gives a proposal its own left accent and a Confirm
  button, and `useConfirmNeed` / `useDismissNeed` are the only paths.

## Tests

686 frontend (from 678), tsc and biome clean, no backend changes. Three mutations
verified to fail: the summary counting its own way instead of `groupNeeds`,
proposals folded into the chase pile, and the nav pointing Needs at a route that
does not exist.

The proposals fixture used `source_attribution: "ai_proposed"` when `isProposed`
reads `disposition`. It type-checked and described a need the product never
produces — the same fixture-coherence trap as LP-UI-021's, in a new field.

## Review pass — a route test that tested folder names

Reviewed on request from the session running the epic. One defect, and the
unbuilt criterion upheld — with a correction to the evidence for it.

### The route-exists test asserted a directory, not a route

The instrument is right. Nothing else in the stack catches "a nav item points at
a page that does not exist": TypeScript does not know Next routes, and no test
renders them all. The `navigation.ts` note predicted this failure in words, and a
comment is not a guard — turning it into one is correct.

What it actually asserted was weaker than what it claimed. `readdirSync` filtered
to directories and checked the name, and a **directory is not a route**: Next
serves a segment only if it contains a `page.tsx`, so a folder holding just a
`layout.tsx` — or any stray directory that happens to match — satisfied the check
while still 404ing. That is the exact failure being guarded, passing the guard.

It now requires the `page.tsx`. Mutation-checked by adding a nav item pointing at
a directory containing only a layout: it fails, where before it passed.

On the coupling the hand-off was unsure about: the test does break if the App
Router convention changes, and that is the right trade. A convention change is
precisely when links break, so failing loudly and taking a one-line update is the
behaviour you want — the alternative fails silently at the moment of highest
risk.

### The unbuilt criterion is upheld, and the reasoning was righter than its evidence

"Batch 'request all outstanding' composes one message" cannot be built honestly,
and should not be faked. Checked independently, because the hand-off asked:

- `app/services/communications.py` **does exist** — the hand-off's stated check
  ("no message or email module under `app/api/` or `app/services/`") was wrong on
  that point. Worth recording, because the conclusion survived a false premise,
  and next time it might not.
- Its own docstring settles the question anyway: *"Just persists the message
  state — actually sending an email (outbound) and routing an inbound one are
  Phase 4."*
- It has **no production caller**. The only importer anywhere is its own test.
- No `smtplib` / `aiosmtplib` / `sendgrid` / `send_email` anywhere in `app/`.

So: nothing sends, and the conclusion holds.

**The shortcut analysis is right and is the important part.** Marking outstanding
needs `REQUESTED` without sending puts a lie in the data that outlives the
session: the next processor reads it as "the borrower was asked". A status is a
record of an event, and writing it without the event is not a partial
implementation — it is a false one.

One honest partial the hand-off did not mention DOES exist, and still should not
be built. `CommunicationStatus.DRAFT` means "outbound, not yet sent", so creating
draft records would claim nothing false. It fails for a different reason: the
Communication tab is a `TabPlaceholder`, so the drafts would be invisible, and a
button labelled "request all outstanding" that produces an artefact nobody can
see still tells the processor an action occurred. Not building it is right on
both counts.

### The Overview summary earns its place

Asked as a design question, and the test is whether the number changes what the
reader does next rather than whether it is smaller than the page it summarises.
"22 Needs action" answers "is this file close?" without a click, which is the
Overview's job — the same standard the reconciliation ledger's rows meet on the
same screen.

It is also reconcilable: counted with `groupNeeds`, the function the list groups
by, so the summary and the page cannot disagree. That is the property that makes
a summary worth having and is the one this epic has watched fail six times.

### The fixture trap, third instance

`source_attribution` where `isProposed` reads `disposition` — type-checked,
described a need the product never produces, and the test passed for the wrong
reason. Third time in three tickets, in a third shape: a wrong field name, an
incoherent field combination, and a state the type forbids.

The rule the hand-off wrote down covers all three — `tsc` proves the shape, not
the coherence — and the practical form is that a fixture asserting a behaviour
should be built through the helper that reads it, or checked against one, rather
than assembled field by field.

### Verification

`tsc` and `biome` clean over 238 files, **686 tests**, build compiles into
`.next-review` with the dev server left running. No backend changes.

| mutation | result |
| --- | --- |
| nav item pointing at a directory with no `page.tsx` | 1 test fails |
