# LP-UI-028 — Admin: rule validation

- **Ticket:** LP-UI-028 — the honesty screen
- **Epic:** Ledger redesign → Epic D (Admin)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-005, LP-UI-007
- **ADR:** none new.

## The defect the ticket's own words named

> Keep the reviewer's own words on a flagged rule — the reason a rule is wrong is
> worth more than the flag.

The note rendered **only when there was a corrected value**:

```tsx
{item.verdict?.corrected_value && (
  <p>Priya corrected → {item.verdict.corrected_value}
     {item.verdict.note ? ` (${item.verdict.note})` : ""}</p>
)}
```

So a rule flagged for removal showed the flag and lost the reason entirely — the
one verdict where the reasoning matters most, because "delete this rule" without
why is not actionable by anyone who wasn't in the room. The note now renders on
any verdict carrying one, quoted in the reviewer's own words, and the corrected
value is its own line rather than a parenthetical.

## An eighth status vocabulary

`STATUS_BADGE` in this file was another independent status map with its own colour
language — found the same way A21 found the seventh. `validation_status` now joins
`lib/status.ts` as `VALIDATION_STATUS`, typed against a real union rather than
`string`, and renders through `StatusToken`.

**`grounded_starter` is the `ai` tone, not `neutral`, and that is the point of the
screen.** A rule researched against real sources but not yet confirmed by a human
is exactly what that tone means — provenance, never "bad". Rendered neutral it read
as "fine, nothing to do here", which is the single thing this screen exists to
prevent. It is also what makes it distinguishable from `validated` in three
channels rather than by grey-versus-green.

On the running app: **121 of 121 items are grounded starters** and none is
validated, said plainly at the top of the screen.

## Five counts as a strip

They were five bordered cards, which gives five numbers equal weight and a card's
worth of chrome each. On a screen whose question is "how much of this has a human
actually confirmed", they should read as one sentence. Tones come from
`VALIDATION_STATUS`, so the strip and the rows cannot disagree about what a status
looks like.

The heading also dropped its 2xl icon title for the section label the other two
admin screens use — it looked like a different product from Lenders, which sits one
item above it in the same column.

## Tests

715 frontend (from 712), tsc and biome clean, no backend changes. Two mutations
verified to fail: the note gated on a corrected value again, and `grounded_starter`
taking the `verified` tone.

**One test changed:** it asserted the label `"grounded starter"` — the raw enum with
its underscore replaced. The status joined the one vocabulary, so the words are the
vocabulary's now; the property (nothing is validated by default) is unchanged and
still asserted, scoped to the list so the strip's own label does not inflate it.

**A mutation that did not apply, caught before it misled me.** My first attempt at
the tone mutation edited the page while the constant lives in `lib/status.ts`, so
nothing changed and the suite passed — which I would have read as "not caught". The
run has to be checked for whether the edit landed, not just for its result.
