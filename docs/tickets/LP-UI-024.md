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

## Review pass — the guarantee that only ran in one direction

Reviewed on request from the session running the epic. Two defects, and the
scope call confirmed.

### `coerce` handled old rows read by new code, and not the mirror

The legacy path is right and the reasoning behind it is right: `parse_warnings`
is JSON, rows written before this change hold bare strings, and they are still
true and still worth showing. `coerce` reads them as `other` rather than dropping
them or crashing.

It handles one direction. A stored `subject` this build does not recognise —
which is what a rollback produces, a newer version writing a member an older one
then reads — reached `model_validate` and raised `ValidationError`, 500ing the
stated-financials response. Confirmed by calling it before changing anything.

Handling only the backward direction is half a guarantee, and the half that was
missing fails harder: a missing link is a degraded panel, a `ValidationError` is
a dead screen. It now falls back to `other` and keeps the message, which is the
same answer the legacy path gives for the same reason.

### Every warning on an existing file lost its instructions

Deleting the old block was right — two renderings of one thing is the
`UnresolvedAlert` argument, and the hand-off applied it correctly. Dropping *"the
file was created — use Edit to fill these in"* as redundant beside a link is also
right, **for a warning that has a link**.

`other` has none, by design. And every warning stored before this change coerces
to `other`. So on any file imported before today the panel is a list of sentences
with no destination and no guidance — strictly less useful than the block it
replaced, which at least said what to do. The two correct decisions composed into
a regression on exactly the data the `coerce` fallback exists to keep visible.

A single line now appears when — and only when — something on screen actually
lacks a destination. Not restored wholesale: for a linked warning the link is
still the better answer, and the old copy would be the noise it was removed for.

### Confirmed, not changed

- **The scope.** Parser, schema, model and two response schemas is a lot of
  backend for an "S" frontend ticket, and it is the right call. "Link a warning
  to the field it concerns" is impossible from a bare sentence without the UI
  parsing its own prose, and the parser already knows which section it was
  reading when it gave up. That is LP-UI-021's override-attribution shape again:
  data that exists at creation and is dropped on the way out. The alternative —
  inferring the subject from the message text in the frontend — is the version
  that looks smaller and is worse.
- **No missed writer.** Checked independently rather than trusting the grep.
  There is one writer (`import_service.py:348`, `model_dump(mode="json")` beside
  `catch_all`), one reader of the stored column (`stated_financials.py:147`, via
  `coerce`), and one response path carrying fresh in-memory warnings
  (`api/loan_files.py:201`), whose schema declares `list[ParseWarning]`. The
  inventory is complete and consistent.
- **`other` as a real member rather than a fallback.** Correct, and it is the
  distinction that made the `FindingBreakdown` classifier sound: an `other`
  assigned explicitly can be reasoned about, an `other` that is an else-branch is
  a hiding place.
- **Naming the stray files.** LF-ZKPK and LF-68D5 are real imports left in the
  dev database by the end-to-end verification. Naming them is the right
  disposition — a reviewer who finds two unexplained files later cannot tell them
  from a bug. Left in place: they are dev data, the verification that produced
  them is the reason to trust this ticket, and deleting the evidence to tidy up
  is a worse trade. Worth removing when the dev database is next reset.

The end-to-end verification is worth recording as the standard: stripping two
elements from the fixture, importing it, and reading the result on screen caught
that the first attempt's regex removed the wrong one of twelve
`PropertyEstimatedValueAmount` elements. A fixture-level test would have passed
on the same mistake.

### Verification

Backend `ruff` and `mypy` clean over 449 files, **6,020 pass** with the two known
`.env` failures. Frontend `tsc` and `biome` clean over 240 files, **699 tests**
(from 696), build compiles into `.next-review`.

| mutation | result |
| --- | --- |
| drop the `ValidationError` guard | 2 tests fail |
| drop the no-link guidance | 3 tests fail |
