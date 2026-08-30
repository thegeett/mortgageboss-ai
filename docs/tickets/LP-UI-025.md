# LP-UI-025 — Admin: lenders list

- **Ticket:** LP-UI-025
- **Epic:** Ledger redesign → Epic D (Admin)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-007, LP-UI-008
- **ADR:** none new.

## Summary

An overlay is the highest-leverage thing an admin touches — one change moves every
file at that lender — so the list now leads with how many rules are overridden and
when that last changed, rather than with programs and contact details.

Seen on the running app, both states together:

| Lender | Overlay | Last changed | Programs |
|---|---|---|---|
| Sun-West | ✓ Agency guideline, unchanged | Never edited | Fha |
| UWM | 1 rule overridden | 1 minute ago | Conventional, Fha |

## Zero overrides is an answer, not a gap

The ticket is explicit and it drove the design: a lender with no overrides means
the agency guideline applies unchanged there. So the row says that in words with a
`verified` tone, rather than printing "0" and leaving the reader to wonder whether
the data failed to load. The tone is deliberate — this is a good state to be in,
not a neutral absence and certainly not a warning.

The same rule applies one level up: an admin index of zeroes reads as a page that
failed, so it carries the sentence "No lender deviates from the investor default,
so the agency guideline applies unchanged on every file."

**"Never edited" is not an em dash.** Never edited and edited long ago are
different facts, and a dash for both merges them.

## The data was already on the row

`lenders.lender_overlays` is a JSON blob carried by the row the list query already
loads, and the endpoint dropped it — returning `LenderSummary` (id, name,
programs). Fetching each lender's overlay to count them would have been one
request per row: the StatsCards pattern LP-UI-013 deleted.

`build_lender_summary` computes both numbers through `_stored_overrides` and
`_stored_audit` — the **same accessors the editor uses** — so the list's count and
the editor's list cannot disagree about what an override is. A test pins that: an
entry without a `rule_id` is dropped by both.

Two details that are defensive on purpose, because overlays were hand-edited JSON
before LP-87: `max()` over the audit timestamps rather than `[-1]`, since a
hand-edited blob carries no ordering guarantee; and an unparseable `at` costs the
"last changed" line rather than the whole list.

## `/admin` is real now

It was a "user management is coming" panel whose two links duplicated the context
column. It now shows the state of the one thing an admin configures — lenders,
how many carry an overlay, how many rules in total, when anything last changed —
read from the same query key the lenders page uses, so opening Lenders next costs
no request and the two screens cannot disagree.

The deferred-user-management note is **kept**, as a line rather than the page.
Dropping it would leave an admin wondering where user management went, which is
the composition mistake the LP-UI-024 review caught: removing copy because
something else supersedes it, in a case where nothing does.

## Tests

706 frontend (from 699) and the backend suite green. Six mutations verified to
fail: zero overrides rendering a bare count, "never edited" shown as a dash, the
role gate removed, the audit assumed ordered, an unparseable timestamp raising,
and the count ignoring the editor's own filter.

## Verified by changing real data, then changing it back

No seed lender had an overlay, so the populated row could not be seen. I set one
override on UWM through the admin endpoint, captured both states, and reverted it
— an overlay alters rule thresholds for **every file at that lender**, so leaving
a fabricated one would have quietly moved verification outcomes on seed files.

The audit trail keeps both entries, which is correct: it exists to record changes,
including this one. That left a third state visible in the data that I had not
designed for — **zero overrides with a last-changed timestamp**, i.e. edited then
cleared — and the row reads it correctly ("Agency guideline, unchanged" beside a
real date).

## Review pass — the column the editor writes, the engine does not read

Reviewed on request from the session running the epic. No code defect in this
ticket; one finding above it, and three judgement calls confirmed.

### The second definition is not in the admin path — it is between the admin and the engine

The check asked for passes. Every read of `lenders.lender_overlays` in the admin
path goes through `_stored_overrides` / `_stored_audit`, all inside
`services/overlay_admin.py`, so the list's count and the editor's list cannot
disagree about what an override is. That was the right instinct and the right
place to look.

The disagreement is one layer out, and it is larger. **The verification engine
does not read that column at all.**

- `registry.py:127` builds `RuleRegistry(overlays={**SAMPLE_OVERLAYS,
  **STARTER_OVERLAYS})` — two hardcoded dicts of Python constants, keyed by
  lender slug.
- `LenderOverlay` is only ever constructed in `overlays/samples.py` and
  `overlays/starter.py`. Nothing builds one from the database.
- `effective_rules` resolves `self.overlays.get(lender_slug)`, so a file's
  overlay comes from those constants and nowhere else.
- ADR-193's own words are still literally true of the engine: the
  `lenders.lender_overlays` column is *"currently unused"*.

LP-87 closed half of that deferral. It built the editor that writes the column
and, per its docstring, "makes each override's effect legible (the investor base
threshold → the lender's effective threshold by composing against the base
rule)". That effective threshold is computed against the base rule and is not
what any file is evaluated against.

**This ticket did not introduce it, and it is what makes it visible.** Leading
the lenders list with the overlay count promotes a stored blob to a lender's
headline configuration. An admin who sets an override now sees it stored,
audited, and counted on the list — and no verification outcome changes.

Not fixed here, deliberately: wiring the column into the registry is a
substantial backend change and a sequencing decision about LP-87's remaining
half, not a repair a review should make on its way past. Raised to the user with
this review.

### The seed-data reasoning was right on a false premise

Worth separating, because the conclusion and the reason came apart. The stated
reason for reverting was that *"an overlay alters rule thresholds for EVERY file
at that lender, so a fabricated one would quietly move verification outcomes on
seed files"*. It would not — for the reason above, it would move nothing.

Reverting was still correct, and for a better reason: the wiring is a matter of
when, not whether, and a fabricated override left in seed data becomes wrong the
day it lands, silently, in a way nobody will connect to a screenshot taken
months earlier.

This is the same shape as the false grep evidence in LP-UI-022 — a sound
conclusion resting on a premise that does not hold. It is worth catching because
the next one may not survive its premise being wrong.

### Confirmed, not changed

- **`max()` over audit timestamps rather than `[-1]`.** Keep. Not cargo: the
  blob predates the writer, was hand-edited config before LP-87, and a JSON array
  carries no ordering guarantee anyone can enforce retrospectively. The cost is
  one function call; the failure it prevents is a "last changed" date that is
  quietly the wrong one.
- **An unparseable `at` costing the line rather than raising.** Keep, and it is
  the same discipline as LP-UI-024's `coerce`: on a JSON column the reader meets
  what a past writer left, and a missing line is a degraded row where an
  exception is a dead screen.
- **Reverting the seed overlay and keeping the audit.** Right on both halves.
  Scrubbing an audit trail to tidy up is worse than an entry that needs
  explaining, and the entry is true — the edit did happen. The state it produced
  is worth the note it was given: zero overrides with a real last-changed date is
  what every lender looks like after an overlay is removed, and it now has
  evidence that the row renders it correctly.

### Verification

No changes made. Confirmed the tree as handed over: backend `ruff` and `mypy`
clean over 449 files, **6,028 pass** with the two known `.env` failures; frontend
`tsc` clean, **706 tests**.
