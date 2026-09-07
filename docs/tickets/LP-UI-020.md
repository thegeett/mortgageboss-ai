# LP-UI-020 — Verification: outcome tabs and findings as rows

- **Ticket:** LP-UI-020
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-005 (one status vocabulary), LP-UI-009 (the context rail)
- **Carries:** the LP-UI-019 review's condition — the rail's two-vocabulary count
- **ADR:** none new.

## The condition first, because it was the worst thing on the screen

The LP-UI-019 review upheld deferring the rail's verification counts here, on the
condition that this ticket not close without them. On measuring, it was worse than
"two vocabularies":

The rail read `red_count` / `yellow_count` / `green_count` — which
`lib/types/verification.ts` says are the **legacy sweep's** severity counts — and
printed them under the **governed engine's words**. On `LF-96SV`:

| the rail said | the governed engine says |
|---|---|
| Must fix **0** | `open` — **10** |
| Needs attention 14 | `couldnt_check` 62, `needs_review` 3 |
| Satisfied **0** | `satisfied` — **14** |

A processor reading the rail was told there was **nothing to fix** on a file with
ten open violations. The two legacy numbers did not even agree with each other:
the run reports 14 yellow against a list of 13.

It now derives from `bucketRuleFindings` — the same function the tab strip buckets
with — so the rail and the tabs cannot drift. The legacy sweep keeps its own line
and its own word and is never added in (LP-375). The block had **no test at all**,
which is how it survived; it has five now, and the mutation that dropped the
"not loaded yet" guard from one metric escaped a version of that test which
inspected only the first, so every metric is asserted separately.

## The screen

**The tabs are at the top level.** `Card → CardHeader → CardContent` is gone. The
heading, the program badge, the version selector, the run button, the phase
readout and "Re-run anyway" all survive; only the box around them went. Nesting is
now finding row → tag panel, which is the two the ticket asks for.

**`couldnt_check` has its own tab.** "We could not check this" is a different job
from "this is wrong" — one is chased with a document request, the other with a
correction. On `LF-96SV` that is **62 against 10**, so sharing a tab was exactly
the drowning LP-333 warned about, one layer up. `alwaysShow`, because "nothing was
skipped" is an answer a processor needs rather than an absence worth hiding.

The tab strip now reads: Needs attention 13 · Couldn't check 62 · Satisfied 14 ·
No longer applies · Not applicable · Cross-checks · Old findings 13.

**Both banners are rails.** The failed-run and staleness banners were tinted boxes;
state goes on the left rule and the glyph, never on a fill. Their "and are
visible" half was already satisfied — LP-UI-002 defined `danger` as an alias of
`destructive`, and before that these two drew no border at all.

**The awaited documents are in the rail**, grouped by document and deduplicated:
62 `couldnt_check` findings on `LF-96SV` resolve to **15 distinct documents** and
one "Request all 15".

## What did not move, and why

**The in-tab request button stays.** The ticket asks for the batched action in the
context rail. The rail is `hidden xl:block`, so making it the *only* home would put
a primary action out of reach below 1280px — the regression class LP-UI-016 was
overruled on, and the reviewer's rule that a route "cannot be reached" waits for
nobody. Both entry points dispatch the identical `request-docs-bulk`, so this is
one mechanism with two doors rather than two mechanisms.

**`MissingVsPresent` is untouched.** The request/read split, the per-document
naming and the batched action already existed (LP-541 / 562 / 564). Only the
bucket it renders moved out from under "Needs attention".

**Every FindingCard action survives.** The legacy `FindingsList` and its action set
are unchanged inside the Old findings tab; the governed rows keep Sign off, Not an
issue, Accept risk and Note. Nothing in this commit touches either action path.

## Six tests changed, each because a signal moved

The largest test surface in the epic — 146 verification tests — and the split
moved where `couldnt_check` findings render. The factory's default
`evaluation_outcome` is `couldnt_check`, so every bare fixture moved with it.

- *"puts couldnt_check in Tab 1"* → *"gives couldnt_check its OWN tab, and no
  other tab absorbs it"*. The assertion inverted; the **property** — the outcome
  lands in exactly one bucket and never leaks — is unchanged and is what the test
  was always for. An `open` finding is seeded so the default tab has content, and
  the absence of the gap there is asserted against a tab that really rendered.
- *"distinguishes the three Tab-1 outcomes"* → *"two"*, plus an explicit assertion
  that "Couldn't check" is **not** there. The split is pinned as real, not cosmetic.
- *"never sums the two systems' counts"* now reads 1 / 1 / 7 rather than 2 / 7. The
  invariant is untouched: each tab reports its own list.
- Three tests moved to a `renderCouldntCheck` fixture that opens the new tab. Their
  assertions are byte-identical; only the tab they run against changed.
- The failed-run banner test asserted `border-danger/40 bg-danger/5`. It now asserts
  `border-l-destructive` plus a negative (`not border-l-border`), because the
  colour moved from a fill to a rail. The property it exists for — *a dead
  six-minute run must not announce itself in grey* — is unchanged.

## Tests

665 frontend tests pass (from 657), tsc and biome clean, no backend changes.
Eleven mutations verified to fail, read as counts. Two escaped first and both are
recorded because the escape is the useful part:

- Dropping the "not loaded yet" guard from **one** metric passed, because the test
  inspected only "Must fix". Every metric is asserted now.
- Requesting only the **five displayed** documents instead of all fifteen passed,
  because the test asserted the button's *label* and never its *payload*. The cap
  is display-only, so "requests all of them" is the load-bearing half and it is
  now asserted through the mutation call.

## Noted, not changed

- **Eight identical findings render in full.** `CollapsedFindings` auto-expands a
  group whose first member is `open`, so CR-1's eight subjects show eight identical
  sentences with four buttons each. Pre-existing and deliberate (the must-fix group
  carries weight), but the collapse exists to make N subjects one row and
  auto-expanding defeats it. Worth its own decision rather than a silent change here.
- **"91 unresolved findings"** in the DTI calculator's banner reconciles with
  nothing on the screen: the governed outcomes total 75 and the legacy list is 13.
  That is the same disagreement class, on the calculator strip — **LP-UI-021's**
  surface, and it should not close without it.

## Review pass — the rail stopped lying about one thing and kept lying about another

Reviewed on request from the session running the epic. One defect, six changed
tests judged, the judgement call confirmed, and the coordination problem fixed.

### Build and dev no longer fight over `.next` — this one was mine

Flagged in the hand-off after costing three restarts, and correctly attributed:
`pnpm build` and `next dev` share `.next`, so a reviewer's verification build
clobbers a running dev server's chunks and every request 404s. It presents as an
auth failure, which is why it took three occurrences to connect.

Fixed rather than negotiated, because "one of us stops doing something correct"
is the wrong trade. `next.config.ts` now takes `distDir` from `NEXT_DIST_DIR`,
defaulting to `.next` — CI, the container image and `pnpm dev` all behave exactly
as before, and a review build runs `NEXT_DIST_DIR=.next-review pnpm build`.
`.next-review/` is gitignored. Verified by running a full build against a live
dev server: it compiled and the dev server survived.

### The rail reported "Manual review" as "Needs review"

The ticket's own finding was right and the fix was right, and it left a second
version of the same defect one line below.

`needsReview` was `buckets.attention.length - mustFix`. But `attention` holds
**three** outcomes — `ATTENTION_ORDER` is `open`, `needs_review`,
`pending_automation` — plus anything `tabForOutcome` cannot place, which it
routes there deliberately so an unknown verdict surfaces rather than vanishing.

So a file with three `pending_automation` findings and no `needs_review` read
"Needs review 3". Those are different jobs: `pending_automation` is a rule that
could not be automated and is explicitly "NEVER a trusted pass/fail", where
`needs_review` is a result a human has to weigh. One number over two meanings, on
the rail that had just been fixed for exactly that.

Counted per outcome now, rendered from `ATTENTION_ORDER` with
`EVALUATION_OUTCOME`'s own labels, so adding a fourth attention outcome adds a
line rather than silently inflating an existing one. An unrecognised outcome gets
its own "Other" line — it is in the tab, so the rail must not disagree about the
total.

Subtraction is what made this invisible: `a.length - b` cannot be wrong about a
label, so nothing looked like a claim.

### The six changed tests, judged

All six are honest, and the hand-off's own account of each is accurate.

- **The four fixture moves** (the factory's default `evaluation_outcome` is
  `couldnt_check`, so the split relocated every bare fixture; three others open
  the new tab with byte-identical assertions). Not tests changed to match code —
  tests following a fixture default. No judgement needed.
- **The inverted routing assertion** is the interesting one and it is correct.
  It used to say "`couldnt_check` belongs in Tab 1" and now says it has its own
  tab; the property was never the destination, it was *the outcome lands in
  exactly one bucket and never leaks*. Seeding an `open` finding so the default
  tab has content is what makes it a real assertion rather than a vacuous one —
  the absence is now asserted against a tab that rendered. That is the companion
  a not-assertion needs, applied without being asked.
- **The banner colour** follows a fill to a rail. Same shape as LP-UI-012's
  notices; the test describes what it always described.

### Confirmed, not changed

- **Two doors to one action.** Keeping the in-tab button alongside the rail's is
  right, and for exactly the reason given: the rail is `hidden xl:block`, so
  making it the sole home puts a primary action out of reach below 1280px —
  LP-UI-016's rule, applied without prompting. Two entry points dispatching one
  `request-docs-bulk` is one mechanism, not duplication. Duplication would be two
  code paths that can disagree; there is one.
- **The two escaped mutations** are both the general form of the not-assertion
  rule, and the second is the sharper statement of it: *an assertion about the
  visible half says nothing about the half that acts*. Asserting the button's
  label while never asserting its payload is how "requests all fifteen" went
  untested while reading as covered.

### The two found and not fixed

- **`CollapsedFindings` auto-expanding an `open` group.** Correctly left for a
  decision rather than changed silently: the collapse exists to make N subjects
  one row, and auto-expanding defeats it for precisely the groups that are worst
  — CR-1's eight subjects become eight identical sentences with four buttons
  each. It is pre-existing with its own rationale, so it belongs to whoever owns
  that rationale, not to a reviewer passing through.
- **"91 unresolved findings" reconciling with nothing** (75 governed + 13
  legacy). Sixth instance of the disagreement class, and LP-UI-021's surface.
  The same condition applies as this ticket carried: it should not close without
  it.

### Verification

`tsc` and `biome` clean over 233 files, **669 tests** (from 665), build compiles
— into `.next-review`, with the dev server left running. No backend changes.

| mutation | result |
| --- | --- |
| derive needs-review by subtraction again | 2 tests fail |
