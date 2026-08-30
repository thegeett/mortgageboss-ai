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
