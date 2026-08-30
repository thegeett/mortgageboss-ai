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
