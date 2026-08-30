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

## Review pass — what consolidation traded away

A `/code-review` over the LP-UI epic found six defects. Five of them are one
story: **unifying the six maps also widened them**. The maps this ticket replaced
were each exhaustive over their own union — `Record<LoanFileStatus, …>`,
`Record<DocumentStatus, …>`, `Record<NeedsItemStatus, …>`,
`Record<NeedsItemPriority, …>`, `Record<EvaluationOutcome, …>` — and
`lib/status.ts` typed all six as `Record<string, StatusMeta>`. Combined with a
`resolveStatus` that synthesizes a fallback for any key, that removed the
compile-time guarantee and the runtime one in the same move.

Two of this ticket's own decisions are reversed below. Both are recorded here
rather than edited above, because the reasoning that produced them is the useful
part.

### The exhaustiveness, at both levels

Deleting `withdrawn` from `LOAN_FILE_STATUS` and `waived` from `NEEDS_STATUS`
left `tsc --noEmit` silent and the whole suite green, after which a withdrawn
file rendered amber "Withdrawn" through the `attention` fallback. Two separate
nets had gone:

- **Compile time.** Each map is now typed to its own enum again.
  `CalculatorView.status` arrives as `string | null` and has no frontend union,
  so `CalculatorStatus` is declared in `lib/status.ts` and the map is held to it
  — every map is exhaustive over *something*.
- **Run time.** `status.test.ts` and `needs.test.ts` had been rewritten to assert
  through `resolveStatus`, which by construction cannot fail: it returns
  `{tone: "attention", label: humanizeUnknown(value)}` for anything it does not
  know, so `expect(meta.label).toBeTruthy()` holds for *every string*. Both now
  index the map directly, and each gained a second test asserting the map's keys
  equal the hand-written union list — so a new member cannot be silently skipped
  by a stale test array.

`resolveStatus` is now generic in the map's key, so passing `LOAN_FILE_STATUS`
does not launder it back into `Record<string, StatusMeta>` at the call site.
`value` stays `string`: the value the backend sent that this build has never
heard of is the entire point of the function.

### Reversed: `spin` as the single source for "still working"

> **Decided** to keep `spin` as the single source for "the pipeline is still
> working" rather than reintroduce `inProgress`. The two sets are identical
> today; one flag cannot disagree with itself.

The sets being identical today was true and was not the risk. Two things were:

1. `isTerminalStatus` fed `documentsRefetchInterval`, so an unrecognised status —
   no entry, therefore no `spin` — counted as **terminal**. A backend that grew
   an in-flight status (say `ocr_pending`) would have stopped the document list
   and drawer refetching, leaving the document parked at a non-terminal state
   until someone reloaded by hand. The pre-consolidation
   `DOCUMENT_STATUS_META[status].inProgress` would have thrown: loud, not silent.
2. It coupled polling to a **purely visual** property. `classified` carries its
   own label rather than "Processing"; dropping its spinner is a reasonable
   design edit that would have halted polling mid-pipeline.

`documents.ts` now declares an exhaustive `Record<DocumentStatus, boolean>` and
returns terminal only on an explicit `false`, so an unknown status keeps polling
— one extra request against a document that never refreshes again. A new
`DocumentStatus` is now a compile error in two places, `lib/status.ts` and this
table, which is the correct number: they answer different questions.

### Reversed: `attention` as the universal fallback

> **Assumed** the `attention` tone for an unrecognised enum is right. It is what
> the asset specifies and it matches the existing `tabForOutcome` fallback.

Right for a row in a work queue, wrong for a headline figure. `CalculatorCard`
colours the DTI/LTV number by tone, so an unrecognised calculator status painted
an amber warning across a figure with nothing wrong with it — in a compliance
tool, a backend enum addition shipping as a visible alarm. `resolveStatus` takes
a `fallbackTone` (still defaulting to `attention`); the two calculator surfaces
pass `neutral`. Both, deliberately: one amber dot beside a neutral figure
reporting the *same* status would be worse than either alone. That also made
`CalculatorCard`'s `data.status ? … : "text-foreground"` ternary redundant, since
`neutral` already resolves there.

### The `ai` token, again

`need-card.tsx` still painted its AI-reasoning panel with `primary`. `--info`
aliases `--primary`, so on a `received` need that panel and the "Documents
attached" info panel sat one above the other in the same hue meaning different
things. The 6% fills are near-white either way and were never the distinguishing
channel — the **glyph** was, and `text-primary/70` against `text-info` is one hue
at two lightnesses. Now `text-ai`, keyed off the `isAi` local that was already
computed and unused. A need whose reasoning is not the AI's gets `Info` rather
than `Sparkles`, because Sparkles is the `ai` tone's glyph in `StatusToken` and
claiming it for a floor need puts the wrong provenance on the row. The prose is
untouched — one voice, per LP-634.

This is the third instance of the pattern noted under "Findings raised": a token
introduced for a case, and the case shipping without it.

### Nit

`calculator-card.tsx` had `const TONE_TEXT` wedged **between two import
statements** — legal, since imports hoist, but it breaks the file's import block
and Biome's organiser will not move a statement across it. Moved below, with a
comment recording its one deliberate difference from `StatusToken`'s `TEXT` map:
`neutral` is `text-foreground`, not `text-muted-foreground`. A headline figure
with no status to report is ordinary text; muting it would read as "this number
matters less", which is the opposite of true on that card.

### Verification

`tsc --noEmit` clean, `biome check` clean over 206 files, 484 tests pass,
`pnpm build` compiles. Every exhaustiveness fix was mutation-checked against the
scenario that motivated it:

| mutation | before | after |
| --- | --- | --- |
| delete `withdrawn` from `LOAN_FILE_STATUS` | silent, suite green | compile error + 2 test failures |
| delete `waived` from `NEEDS_STATUS` | silent, suite green | compile error |
| backend grows an in-flight `DocumentStatus` | silent, polling stops | compile error in `documents.ts` **and** `status.ts` |
| drop `spin` from `classified` | polling halts mid-pipeline | polling unaffected |

Two tests added for the new behaviour: `resolveStatus` honours `fallbackTone`,
and `isTerminalStatus` keeps polling a status this build has never heard of. The
`bg-ai/[0.06]`, `bg-muted/60` and `text-ai` classes were confirmed against a
Tailwind CLI build rather than assumed.
