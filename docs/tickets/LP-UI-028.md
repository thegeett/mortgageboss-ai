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

## Review pass — one vocabulary, and one list beside it

Reviewed on request from the session running the epic. One defect; three
judgement calls confirmed, one of them the tone question.

### The statuses were enumerated twice

Consolidating `STATUS_BADGE` into `VALIDATION_STATUS` is right and the typing is
right: `Record<ValidationStatus, StatusMeta>` is exhaustive over a real union, so
a fifth status is a compile error there.

Eleven lines below it, the status filter's options were a hardcoded array of the
same four strings. A fifth status would fail the map and stay green here — and
the consequence is a status a reviewer cannot filter for, on the screen whose job
is finding the items that need attention, discoverable only by noticing an
absence.

That is the eighth vocabulary's own shape repeating one scroll further down: not
a second *map*, a second *list*. Derived from `Object.keys(VALIDATION_STATUS)`
now, with a test that fails when a status is missing from the options.

### `grounded_starter` taking the `ai` tone is right

Checked against what the status asserts rather than judged on the name. From
`rules/conventional/_base.py`: a grounded starter is *"researched against the
current Fannie Mae Selling Guide (retrieved 2026-06) with real B-section
citations, clearly marked `starter=True` and pending the domain expert's
validation."*

So it records **where the value came from** — model research against a cited
source — and not whether it is correct. That is the `ai` tone's own definition in
`lib/status.ts`: *"provenance, NOT a status. Never means 'bad'."* It is the same
meaning the tone already carries for an AI-proposed need, so it is consistent
rather than overloaded.

And `neutral` would have been actively wrong here for the reason given: on a
screen that exists to surface what nobody has confirmed, "nothing to do here" is
the one thing the default state must not read as. 121 of 121 items are in it.

### Confirmed, not changed

- **The heading alignment.** Take it. A screen one row below Lenders in the same
  column, rendered in a different idiom, is a defect in the same sense a
  mislabelled number is — it tells the reader they are somewhere else. Matching
  the section label the other two admin screens use is a repair, not a
  redecoration, and it is smaller than the ticket it would otherwise wait for.
- **The changed test.** Honest. It asserted `"grounded starter"` — the raw enum
  with its underscore replaced — which stopped being what the screen says when
  the status joined the vocabulary and took the vocabulary's words. The property
  (nothing is validated by default) is unchanged and still asserted, and scoping
  it to the list so the new strip's label does not inflate the count is the
  correct adjustment rather than a loosening.

### The mutation that did not apply

Worth recording as the third route to one hazard. A mutation edited the page
while the constant it targeted lives in `lib/status.ts`; the anchor assertion
fired, nothing changed, and the suite passed — which reads identically to
"caught nothing".

The family so far: a wrong path (`$C.test.tsx` against a file that did not
exist), a filter that excluded the guarding file (`-k "activity_log or overlay"`,
mine), and now a wrong target file. All three produce a green run that means
nothing, and all three are invisible in the result. The check that covers all of
them is the same one: confirm the edit landed and confirm which tests ran, before
reading the outcome at all.

### Verification

`tsc` and `biome` clean over 242 files, **716 tests** (from 715), build compiles
into `.next-review`. No backend changes.

| mutation | result |
| --- | --- |
| hardcode the filter options, omitting one status | 1 test fails |
