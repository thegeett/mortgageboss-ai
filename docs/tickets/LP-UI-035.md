# LP-UI-035 — Dialogs and toasts

Epic F. A destructive confirmation worth showing, toasts that say what changed,
undo where undo exists, and Sonner on the design tokens.

## The delete dialog

Two things make a destructive confirmation worth showing, and a dialog with
neither is a speed bump that teaches people to click through:

**It names what goes with it.** "8 documents" is what makes a processor stop;
"this file and its data" is what they already agreed to by clicking Delete. The
count is fetched while the dialog is open — one request, on a deliberate and rare
action — and **omitted rather than guessed** while it loads. A wrong number on a
destructive confirmation is worse than no number.

**It asks them to type the id.** A muscle-memory click cannot produce "LF-96SV".
Compared trimmed and case-insensitively: the gate exists to defeat a reflex, not
to test typing, and a processor who typed the id in lower case has demonstrated
everything it asks for. The typed value resets when the dialog closes, so a
half-typed id from a cancelled delete cannot pre-arm the next file's dialog.

The id is in the title too, as the mockup has it — a processor with two tabs open
needs to see *which* file without reading the body.

## The toasts

**All 49 call sites moved to a wrapper that requires a second line.** Seventeen of
the 26 success toasts said only what had happened — "Asset added", "Loan updated",
"Document removed" — which the processor already knows, because they just did it.
The title is the action; the second line is what *changed*:

> Bonus income set to the 24-month average
> Back-end DTI moved from 44.7% to 43.8%.  **[Undo]**

A required prop is what stops the bare label coming back, the same shape that
stopped the apology coming back in LP-UI-034. `lib/toast-usage.test.ts` fails if
anything imports `sonner` directly again — with its roots derived from the tree
rather than listed, because the LP-UI-034 review found a hand-written directory
list silently missing `hooks/`.

**Two tones that are neither success nor failure**, because reporting them as
success is a small lie:

- `notifyStarted` — an upload or a re-extraction has begun. Nothing has changed
  yet, so a success tick would be a claim.
- `notifyPartial` — the file was created *and* the property the processor typed
  was dropped. Both are true and the dropped one still needs them.

**Every finding resolution now carries an undo**, because one already existed:
`kind: "undo"` reverses any of them (LP-98) and the row has offered that button
since. A toast is where a processor is looking the instant they realise they
clicked the wrong row; making them find the row again is the gap this closes. The
undo itself gets none, and neither does a bulk action — there is no single finding
to reverse. Undoable toasts stay up for ten seconds, because the default four is
less time than it takes to read the consequence and decide it was wrong.

## The bug only the browser found

`richColors` is gone — it is Sonner's own palette, a second colour vocabulary
beside the one LP-UI-005 unified — and the rail carries the tone instead.

Then the live check: **an error toast rendered a petrol rail.** Sonner applies its
`default` slot *in addition* to the typed one, so the element carried both
`!border-l-primary` and `!border-l-destructive`, and which one won was decided by
**Tailwind's output order**, not by the order I wrote them. It emitted primary
last. The class list looked correct; only `getComputedStyle` showed
`rgb(18, 84, 94)` where the destructive token should have been.

Fixed by scoping the neutral rail to `data-[type=default]`, which cannot collide
with a typed one. The styling moved out of `providers.tsx` into
`TOASTER_CLASSNAMES` so it can be asserted on, and the test states the rule
directly: no unscoped rail colour on the base, exactly one per status, tokens
only.

## Tests

`lib/toast.test.ts` (12), `lib/toast-usage.test.ts` (3), and
`delete-file-dialog.test.tsx` grew from 5 to 12 — the gate disabled until the id
is typed, a near miss rejected, lower case accepted, the count shown when it
arrives and omitted while it loads.

Mutation-checked, 12 mutations, all caught: the consequence never reaching the
toast, an undo wired to nothing, an undo dismissed before it can be reached, a
partial success reported as a success, started work reported as a success, the
usage guard skipping a directory, the delete button no longer needing the typed
id, a near miss accepted, the unscoped rail returning, an untyped toast losing its
rail, two rails on one status, and a raw colour instead of a token.

Checked in light and dark, and driven live in the browser for both the dialog and
a real toast. CI green by exit code: biome, tsc, 918 vitest. No backend changes.

## Not done

**"Success toasts state the consequence" is now structurally enforced, but the
consequences themselves are as good as I could write them from the code.** The
mockup's example quotes a real number — "Back-end DTI moved from 44.7% to 43.8%" —
and none of mine do, because none of these call sites has the before-and-after
figures to hand. Saying *what kind* of thing changed ("its payment counts towards
the back-end DTI") is honest and useful; quoting the movement would need each
mutation to return the recalculated ratio. That is a backend shape change, not a
copy change, and it is the difference between this ticket's letter and its intent.

---

## Review (LP-UI-035 review commit)

Reviewed on request from the session running the epic. Five findings. Three of
them are the ticket's own worry about the rewritten messages, and they are the
ones that matter: each was a confident false statement to a processor.

### 1. Three consequence lines were wrong about how the system behaves

Checked against the backend rather than read.

- **"Fill it in and its payment counts towards the back-end DTI."** A liability
  marked paid off at closing is EXCLUDED from the back-end ratio (LP-568,
  `_auto_debt_lines`). On a refinance the mortgage being replaced is exactly that,
  and it is the most common liability a processor adds here — counting it charges
  the same house twice. This is the field where getting it wrong moved a real
  file's DTI from 34% to 59%. Now: "…unless it is paid off at closing."
- **"Fill it in and its value counts towards reserves."** `build_reserves_view`
  excludes gifts and borrowed funds outright and takes retirement at a factor —
  0.60 on FHA. Now names both.
- **"LTV and the property rules can now run on this file."** The button creates an
  EMPTY property row (`mutate({})`), and LTV reads a purchase price or an
  appraised value; with neither it returns "unknown". Its three siblings all say
  "Fill it in and…"; this one claimed the end state at the moment the row was
  blank. Now matches them.

The income line — "it counts towards the stated income" — is correct: no
exclusion applies to a stated income item.

### 2. The rail fix is complete; its guard is not

The scoping to `data-[type=default]` is right, and `TOASTER_CLASSNAMES`' test
catches an unscoped rail colour coming back — verified by reintroducing it.

But the hazard is not about rails. Sonner applies the base slot AND the typed slot
to the same element, both with `!`, so ANY shared property is decided by Tailwind's
output order. Giving `error` a `!text-destructive` against the base's
`!text-foreground` is the same bug on a different property, and every existing test
passes. Added a guard that compares the CSS property each utility sets, so no typed
slot can set something the base slot already sets unscoped.

### 3. The Sonner ban only banned one syntax

`from "sonner"` was the only shape matched. Verified by planting each in a real
component: `await import("sonner")` and `require("sonner")` both reached Sonner
with the guard green. Now matches static, dynamic and require forms, either quote
style, pinned by a table of samples in both directions.

The ticket's own worry about the `*.test.ts` exemption does not hold: the scan is
static over source, so what a test mocks at runtime cannot hide a component's
import. The exemption is sound.

### 4. The undo's failure was not silent — it was mislabelled

`act` serves both the resolutions and the undo, and `onError` always said
"Couldn't resolve the finding". A processor who clicked Undo and hit a failure was
told a resolution failed: the one message they get about what just happened,
describing the wrong action. The title now names the action attempted, tested in
both directions so the fix cannot be "always say undo".

### Confirmed, not changed

- **The undo cannot fire twice in practice.** Sonner dismisses a toast when its
  action is clicked, and the recursion is correctly bounded — `kind: "undo"` and
  any action without a `findingId` both fall through to no undo. A double-fire
  would need two clicks in one frame, and the second would surface an error rather
  than pass silently.
- **The remaining consequence lines** — the checklist, the stated totals, and "the
  rules that read it run again on the next verification" — are accurate. The last
  one is correctly hedged: a verification run is triggered, not automatic.

### Verification

biome 0, tsc 0, **929 vitest**, build clean. No backend change, so no pytest run.
Seven mutations, all caught.
