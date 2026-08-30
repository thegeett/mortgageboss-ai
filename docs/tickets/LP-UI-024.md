# LP-UI-024 — MISMO import warnings

- **Ticket:** LP-UI-024
- **Epic:** Ledger redesign → Epic D
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-023
- **ADR:** none new.

## Summary

"Imported with 6 fields to review" was a toast, and a toast is gone by the time a
processor is looking at the thing it described. The warnings now have a surface at
the top of the Overview: which fields, in the parser's own words, each linking to
the section it concerns.

Verified end to end on a real import. A MISMO file with `PropertyEstimatedValueAmount`
and `BaseLoanAmount` stripped produced `LF-68D5`, whose Overview reads:

> **THE IMPORT COULD NOT READ** — 2 fields to review
> ⚠ Loan is missing a base loan amount. *Go to the loan*
> ⚠ Subject property is missing an estimated value. *Go to the property*

and both links land on the blanks visible below them — Loan → Amount "—",
Subject property → Estimated value "—".

## The change that made the links possible

A warning was a bare sentence: `"Loan is missing a base loan amount."` Linking one
to "the field it concerns" from that means the UI recognising its own prose, which
breaks the first time anyone rewords a message — and it is the UI re-deriving
something the parser already knew.

**The parser knows exactly which section it was reading when it gave up**, and
discarded it. So `ParseWarning` now carries a `subject`
(`borrowers | income | loan | property | other`), recorded at each of the eight
sites that raise one. Same shape as LP-UI-021's override attribution: the data
existed at the point of creation and was dropped on the way out.

`other` is a real member rather than a fallback for a subject nobody thought of —
a warning belonging to no section still has to appear, and the panel renders it
without a dead link.

**The stored rows had to keep working.** `parse_warnings` is a JSON column and
every import before this holds bare strings. `ParseWarning.coerce` reads either,
so those rows still show their warnings (as `other`) rather than being dropped or
crashing the response. No backfill, no migration.

## One rendering, not two

`StatedFinancialsSection` already rendered these warnings — inside the card a
reader opens only if they already suspect something, with no links. That block is
gone. Two renderings of one list is how they drift, which is the same argument
that collapsed three copies of `UnresolvedAlert` in LP-UI-021.

The refinance warning ended with *"confirm it on the Overview"* — prose standing
in for a link. It carries `subject: loan` now and the sentence stops at the fact.

## The three criteria

- **Warnings reachable after the toast is gone.** They live on the import record,
  and the panel reads them from `stated_financials.mismo_import`.
- **Each links to the field it concerns.** Via the recorded subject, to anchors on
  the Overview (`#card-loan`, `#card-property`, `#card-borrowers`,
  `#stated-financials`). The cards carry `scroll-mt-24` so a linked card clears the
  sticky topbar — the same reason `[data-row]` has `scroll-margin-block`.
- **Zero warnings shows nothing, not an empty panel.** `return null`, and a test
  asserts the container is empty rather than that some heading is absent.

## Tests

696 frontend (from 690) and the backend suite green. Six mutations verified to
fail: an empty panel on a clean import, every subject linking to one place, an
unplaceable warning given a dead link, and — backend — a legacy string row
dropped, a subject lost across the JSON round trip, `other` folded away.

Seven backend tests changed because the shape they asserted is what this ticket
adds structure to. Each now asserts the message **and** the subject, so they pin
more than before rather than less. One frontend test moved: the stated-financials
section asserts the warnings are **not** there any more, with a positive control
beside it, so the move stays visible.

## Left in the dev database

Exercising the real import path created two files: `LF-ZKPK` (a first attempt
whose warning did not fire — the regex removed one of twelve
`PropertyEstimatedValueAmount` elements, and not the subject property's) and
`LF-68D5` (the verified one). Both are legitimate imports rather than hand-written
rows, and the seed script rebuilds the database, but they are strays and worth
naming rather than leaving for someone to find.
