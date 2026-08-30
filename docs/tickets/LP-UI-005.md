# LP-UI-005 — One status vocabulary

- **Ticket:** LP-UI-005 — collapse six status maps onto one tone vocabulary
- **Epic:** Ledger redesign → Epic A (Foundation) — the last ticket in it
- **Status:** Completed
- **Date:** 2026-08-29

## Summary

Six independent maps each invented their own colour language. They now resolve
onto six tones in `lib/status.ts`, rendered one way by `<StatusToken>`: colour +
glyph shape + word. The six old maps are gone, not orphaned.

The labels did not move — with one exception the review caught before it shipped,
described below. Only the colour vocabulary was unified, which is what the SPEC
asks for and what makes this safe to do to a compliance tool.

## What Changed

**New.** `lib/status.ts` (six maps + `resolveStatus`) and
`components/status-token.tsx` (`StatusToken`, `StatusRail`, `railClass`), both
dropped in from `assets/` and byte-identical to them.

**Deleted, with their call sites moved:**

| gone | was in | replaced by |
|---|---|---|
| `STATUS_META` | `lib/loan-files/status.ts` | `LOAN_FILE_STATUS` |
| `DOCUMENT_STATUS_META` | `lib/loan-files/documents.ts` | `DOCUMENT_STATUS` |
| `STATE_META` | `lib/loan-files/needs.ts` | `NEEDS_STATUS` + `NEEDS_GROUP` |
| `PRIORITY_META` | `lib/loan-files/needs.ts` | `NEEDS_PRIORITY` |
| `OUTCOME_META` | `lib/verification/rule-findings.ts` | `EVALUATION_OUTCOME` + `OUTCOME_BLURB` |
| `STATUS_DOT` / `STATUS_TONE` | the two calculator components | `CALCULATOR_STATUS` |

Three of them carried domain data alongside the colours, and that data stayed
where it belongs rather than being dragged into the shared vocabulary:

- **`inProgress`** drove the spinner, the polling and `isTerminalStatus`. It is
  now `spin`, which `StatusMeta` documents as marking in-flight pipeline states
  and which covers exactly the same four statuses — one source instead of two
  that could drift.
- **`group`** (which needs bucket a state rolls into) is now `NEEDS_GROUP`, a
  pure grouping map in `needs.ts`. It is a needs-list concern, not a visual one.
- **`blurb`** — the LP-583 and LP-581 prose — is now `OUTCOME_BLURB`, with both
  ADR comments carried across verbatim. It is domain writing, not presentation.

**Rendering.** `StatusBadge`, `DocumentStatusBadge`, the needs state and priority
pills, the rule-finding outcome badges and the calculator tile dots all go
through `StatusToken`. Two rows also gained the left rail (SPEC rule 5): the
need card and the rule-finding row, both of which are scanned down a long list.

## The label the review caught

An earlier draft of the asset renamed four document statuses — `pending`,
`classifying` and `extracting` from "Processing" to "Queued" / "Classifying" /
"Extracting", and **`completed` from "Completed" to "Verified"**.

The last one mattered. `completed` is the terminal state of the *processing*
pipeline (`PENDING → CLASSIFYING → CLASSIFIED → EXTRACTING → COMPLETED`,
`backend/app/models/document.py:87`). It means extraction finished — the document
has been read by a model and checked by nobody. This product tracks stated vs
verified data as a first-class distinction (CLAUDE.md), verification is a separate
subsystem, and `NEEDS_STATUS.verified` already uses "Verified" for the case where
something actually was verified. Shipping it would have told a processor something
false, in a compliance tool, in the one word that already means the true thing.

Held to the shipping wording and raised; the asset has since been corrected and
`lib/status.ts` is byte-identical to it again. Every other map was verbatim
already — loan file 8/8, needs 6/6, priority 3/3, and the LP-583/581 outcomes 7/7.

## Two outcomes changed tone. No outcome changed words.

`needs_review` and `pending_automation` were `info` and are now `attention`.
Both mean a human has to look, which is what `attention` means, and both were
already bucketed into the governed **attention** tab by `ATTENTION_ORDER` — so
the colour now agrees with the tab a processor finds them in. This is the colour
unification the ticket is for, and it is visible: two outcomes move from blue to
amber.

## Verification

**Greyscale, which is the criterion colour cannot fake.** The four screens were
captured with `filter: grayscale(1)` on the document element. The calculator
tiles are the clearest case: six tiles that were bare coloured dots now read as
four distinct glyphs with zero colour — `CircleX` on the over-limit DTI,
`CircleCheckBig` on LTV and reserves, `TriangleAlert` on mortgage insurance and
maximum loan, `CircleDashed` on the absent self-employed income. The finding rows
read `⊗ Must fix` with a left rail. Nothing depends on hue.

**`lib/status.test.ts`** (20 tests) pins the parts a screenshot cannot:

- every status in all six maps has a non-empty label and a valid tone;
- **every tone has a *different* glyph** — parsed out of `status-token.tsx`, so
  if two tones ever shared a shape they would be separable by colour alone, which
  is precisely what rule 4 forbids. `blocking` vs `attention` is asserted
  separately: it is the pair that decides whether a file can move;
- `resolveStatus` on an enum the backend grew returns `Awaiting investor response`
  at tone `attention` — surfaced as work, never hidden, never thrown;
- an absent status renders "—" rather than blank;
- the seven LP-583/581 labels, asserted literally, and `completed` = "Completed"
  alongside `NEEDS_STATUS.verified` = "Verified".

**LP-375 held.** `OUTCOME_TAB`, `TabId`, `GovernedTabId`, `bucketRuleFindings`
and the legacy quarantine are untouched — the only change to that region of
`rule-findings.ts` is a comment. Confirmed in the browser: "Old findings" is
still its own tab with its own count, never summed with the governed tabs.

**A duplicate announcement, found and removed.** My first pass put a `dot`
`StatusToken` beside the need title *and* a `chip` below it. Both carry the word,
so a screen reader announced "Pending" twice per card — three tests failed on
"Found multiple elements", which is the accessibility bug showing up as a test
failure. The dot is gone and the card's state moved to the rail instead, which is
what SPEC rule 5 asks for anyway.

**CI.** biome (no fixes), tsc, **480 tests** (up from 460), build — all green.

## Findings raised

1. **Status-shaped rendering still exists outside the vocabulary.** The ticket
   named six maps and those six are done, but roughly a dozen components still
   build a tinted pill inline from `bg-<tone>/10 text-<tone>`. The ones that read
   as statuses to a processor: `stalenessBadge` ("May be stale", "Staleness
   waived" — colour and word, no glyph, and it sits in `documents.ts` beside the
   map that was just replaced), the "Over limit" / "Insufficient" badges in the
   DTI and LTV calculators, the provenance and count chips in `finding-card.tsx`
   and `rule-findings-tabs.tsx`, and `snapshot-findings-tab.tsx`. None is wrong
   today; all are outside the one vocabulary, so they will drift. Worth a
   follow-up ticket rather than widening this one.

2. **`StatusRail` has no consumers; `railClass` has two.** Both ship in the
   asset. The rail is the right mechanism for the reviewer and the pipeline table
   in Epic C, so this is an observation rather than a defect — but it is the same
   shape as `--skeleton` and `--ai` in LP-UI-004, both of which shipped with zero
   consumers and needed finding later.

## Assumptions and decisions

- **Decided** to keep `spin` as the single source for "the pipeline is still
  working" rather than reintroduce `inProgress`. The two sets are identical
  today; one flag cannot disagree with itself.
- **Decided** the needs card's `proposed` accent keeps the left rail when a need
  is proposed, and the state tone takes it otherwise. `proposed` is provenance,
  not state, and provenance is the rarer, louder signal on that card.
- **Assumed** the `attention` tone for an unrecognised enum is right. It is what
  the asset specifies and it matches the existing `tabForOutcome` fallback, which
  also routes the unknown to attention — an unrecognised verdict must surface
  where the work is.

## Files

- new: `lib/status.ts`, `components/status-token.tsx`, `lib/status.test.ts`
- rewritten call sites: `status-badge.tsx`, `document-status.tsx`,
  `need-card.tsx`, `rule-finding-row.tsx`, `rule-findings-tabs.tsx`,
  `calculators-section.tsx`, `calculator-card.tsx`
- maps deleted from: `lib/loan-files/status.ts`, `lib/loan-files/documents.ts`,
  `lib/loan-files/needs.ts`, `lib/verification/rule-findings.ts`
- tests updated: `status.test.ts`, `needs.test.ts`
