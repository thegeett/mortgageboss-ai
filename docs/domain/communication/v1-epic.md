# Communication v1 — draft only · the epic index

Split out of `comm-v1-tickets-LP-850-857.md`. Tickets live in `docs/tickets/LP-85x.md`;
the screens are `v1-screens.md`.


Spec: `docs/domain/communication/comm-v1-draft-only-spec.md`.
Screens: artifact **"Draft Only Screens"**. Rationale: artifact **"Draft Only"**.

## The fence

**One version that does one thing: it writes drafts.** Nothing sends, nothing arrives, nothing
reminds. Delivery is a person with their own mail client, and every screen says so.

Out, and returning next phase: sending, receiving and inbound parsing, replies and threading, the
secure upload link, reminders (LP-814), `delivered` / `failed`, and anything that claims to know the
borrower received it.

## The eight

| # | Ticket | Blocked by | Size |
|---|---|---|---|
| LP-850 | Outstanding means outstanding, and one draft per party | — | large |
| LP-851 | One dialog, three doors | 850 | medium |
| LP-852 | A draft nobody knows about | 850 | small |
| LP-853 | The body becomes HTML the moment a person touches it | — | large |
| LP-854 | The toolbar Gmail has | 853 | medium |
| LP-855 | Copy and open, in one click | 853 | medium |
| LP-856 | A draft about nothing, and a button that makes it presentable | 853 | medium |
| LP-857 | Take the next phase off the page | — | small |

## Two independent chains, and one that can go first

```
LP-850 ──┬── LP-851 ── (LP-851 + LP-853 must ship together, see below)
         └── LP-852

LP-853 ──┬── LP-854
         ├── LP-855
         └── LP-856

LP-857 ── independent, start any time
```

**LP-850 and LP-853 are the two roots and touch nothing in common** — one is the draft lifecycle in
`email_draft.py`, the other is the body column and the editor. They can run in parallel from day
one, which is the whole reason the epic is cut this way.

**LP-857 is a net deletion and unblocks nothing**, so it is the safe thing to give a spare hand.

## The one coupling to watch

**LP-851 removes the per-document note form. LP-853 is what makes the draft body keep an edit.**

LP-839 built that note field *and* made it render — it is how a processor says "the March statement
specifically, not February". Remove it while `_regenerate` still overwrites the body on every append
and the feature is a regression, not a simplification.

**Ship them together or ship neither.**

## The decisions these encode

Recorded here so nobody re-litigates them from a screenshot:

1. **Draft membership is not the source of truth for what is outstanding.** The needs list is.
   Both of the flow defects trace to this one confusion (LP-850).
2. **One open draft per party, enforced in the service.** Not a warning, not a convention — the
   second open draft cannot be created (LP-850).
3. **"Mark as sent" is a claim, not an event.** Nothing observed a send, so the record is attributed
   — `Marked sent by Priya · Tue 16:41` — and it never moves a need to `received` (LP-850, LP-855).
4. **Generated bodies stay plain; a human edit makes them HTML.** `body_format` is also the
   `body_edited` flag. One fact, one place (LP-853).
5. **Three of Gmail's controls are declined** — font family, text colour, alignment — and the
   reasons are in LP-854, not in somebody's memory.
6. **No compose route carries formatting.** So the button copies *and* opens, with the body left
   empty (LP-855).
7. **No Send button, not even disabled** (LP-855, LP-857).
8. **The party is a column, never a heading.** A heading is a region that can be scrolled past
   (LP-852).

## What "done" looks like

A processor opens a file, clicks Request all, gets one dialog that tells them a draft is already
open and what is in it, adds to it, writes two sentences of their own in a real editor, clicks
**Copy & open Gmail**, pastes, sends, comes back and marks it sent — and the next request knows
which documents have since arrived.

Nothing in that sentence requires the app to send or receive anything.
