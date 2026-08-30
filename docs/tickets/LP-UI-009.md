# LP-UI-009 — File context rail

- **Ticket:** LP-UI-009 — the 288px right-hand rail on file routes
- **Epic:** Ledger redesign → Epic B (Primitives and shell)
- **Status:** Completed
- **Date:** 2026-08-29
- **Mockup:** Overview, Verification, Documents — right-hand column

## Summary

The fourth region of the shell. Loan amount, DTI, LTV and reserves are the
numbers a processor switches tabs to check; the rail pins them beside the work
surface on every file route, so the switching mostly stops.

Verified on the Communication tab — a Phase-4 placeholder with no data of its
own — where all four numbers are on screen anyway. That is the whole argument
for the rail in one screenshot.

## What Changed

- **`components/layout/file-context-rail.tsx`** (new). Always: status, loan
  (amount / program / purpose), ratios (back-end DTI against its limit,
  front-end DTI, LTV, reserves), recent activity. Plus one tab-specific section:
  coverage and freshness on Documents, run counts and last-run age on
  Verification.
- **`app/(protected)/loan-files/[id]/layout.tsx`** — the rail is a sibling of
  the work surface, not inside it, so the two scroll independently. `-m-4`
  cancels the shell's page padding so the rail meets the window edge and its
  border is the seam.

## Verification

**Geometry, measured on four file routes:** width **288px** on every one,
`overflow-y: auto` (its own scroll), and the tab-specific section present only
on its own tab — `Documents` on `/documents`, `Verification` on `/verification`,
absent on Overview and Communication.

**Below `xl` (1200px):** `display: none`, width 0. Unlike the LP-UI-008 collapse
bug, `display: none` removes it from the tab order and the accessibility tree as
well as from view. The rail also has **zero focusable elements** — it is
read-only by design — so it adds nothing to the keyboard path either way.

**Values render correctly:** `$357,050`, back-end DTI `50.45%` shown in
`destructive` against its `/ 50%` limit, front-end `33.05%`, LTV `96.50%`,
reserves `26.5 months`, and the five most recent activity entries.

**CI.** biome, tsc, 541 tests, build — green.

## Finding raised: "no extra fetches" is not achievable as written

The acceptance says the rail should read *"from the queries already cached by the
file layout — no extra fetches"*. Measured rather than assumed: distinct API
requests per route, captured over CDP with and without the rail mounted.

| route | without rail | with rail | delta | what the rail adds |
|---|---|---|---|---|
| overview | 6 | 9 | **+3** | `dti`, `ltv`, `calculators/reserves` |
| documents | 2 | 6 | **+4** | `dti`, `ltv`, `calculators/reserves`, `activity` |
| verification | 10 | 11 | **+1** | `activity` |

**The criterion cannot hold alongside the rail's purpose.** The file layout
caches exactly one query, `useLoanFile`. DTI, LTV and reserves are fetched by
the Verification tab because that is the tab that owns them — and the entire
point of the rail is that a processor should not have to go to that tab to see
them. Putting those numbers on Documents necessarily fetches them on Documents.

What *is* true, and is the property worth having:

- **The rail adds no duplicate requests.** Every query it shares with a page is
  served from one request — React Query dedupes on the key. On Verification the
  rail's `dti`, `ltv` and `reserves` cost **zero** additional requests, because
  the calculators already fetch them; its whole delta there is `activity`.
- The delta is largest exactly where the rail is most useful (Documents, +4)
  and zero-to-small where the page already had the data.

Left as-is and raised rather than worked around, because the alternatives are
both worse: rendering the numbers only when some other tab happened to warm the
cache would make the rail blank on a fresh load of Documents, and prefetching
them in the layout would move the same four requests earlier, not remove them.
If the intent was "no *duplicate* fetches", the rail meets it; if it was
literally "no new requests", the ticket and the feature disagree and the ticket
should be amended.

**Unrelated observation from the same measurement:** in dev, most queries fire
twice (overview: 19 requests, 10 distinct). The pattern covers queries the rail
does not touch — `borrowers`, `stated-financials`, `needs` — so it is React
StrictMode's double-invoke in development, not something this ticket introduced.
Worth confirming it does not survive into a production build before anyone reads
it as a performance problem.

## Assumptions and decisions

- **Decided** the tab-specific hooks (`useLoanFileDocuments`,
  `useVerification`) mount only on their own tab, so the rail never introduces
  those requests anywhere else.
- **Decided** the rail is read-only — no buttons, no links. It is a reference
  surface beside the work, and every affordance added to it is a tab stop
  between the work surface and the page.
- **Decided** `humanize()` on program and purpose. They arrive as raw enums
  (`conventional`, `purchase`) and the file header already humanises them;
  showing both spellings on one screen is the drift this epic keeps finding.
- **Decided** the DTI limit reads *after* the value (`50.45% / 50%`). The first
  pass rendered the hint first, which read as `/ 50% 50.45%`.
- **Assumed** `completed_at` is the right "last run" timestamp;
  `VerificationRun` has no `created_at`.

## Files

- new: `components/layout/file-context-rail.tsx`
- changed: `app/(protected)/loan-files/[id]/layout.tsx`

## Review pass — an em dash that meant two things, and a seam that stopped short

Reviewed on request from the session running the epic. Five defects fixed, three
of the hand-off's five suspicions cleared, and the two open questions answered.

### The full-bleed layout stopped 32px above the bottom of the window

`-m-4` cancels the shell's padding, and horizontally that works — a block with
`width: auto` absorbs its own negative margins, so the used width grows back by
exactly the two 16px it gave up and the rail meets both side edges.

`h-full` is not auto. `height: 100%` resolves against the parent's CONTENT box,
which is already 2×pad shorter than its border box, and a negative margin does
not grow it. So the element was `H − 32` tall with its top pulled up to the
window edge, leaving its bottom — and the rail's left border, the seam this
ticket is about — a full 32px above the bottom of the viewport. The horizontal
axis looked right, which is exactly why the vertical one would not have been
questioned.

Fixed by adding the padding back to the height, and by single-sourcing the
number the two files were both spelling as `4`:

- `--shell-pad: 1rem` in globals.css (asset re-synced),
- `p-[var(--shell-pad)]` on AppShell's `main`,
- `-m-[var(--shell-pad)] h-[calc(100%_+_var(--shell-pad)_*_2)]` on the layout.

That answers the hand-off's own worry about the coupling — "nothing asserting
it" — with three assertions in `tailwind.config.test.ts`: the variable exists,
`main` uses it rather than a literal, and the layout cancels it in BOTH axes. All
three Tailwind classes were checked against a compiled stylesheet, since two are
arbitrary values and one contains a `calc`.

### An em dash meant "absent" and was being used for "not loaded"

Every value in the rail fell back to `—`, including while its query was still in
flight. `—` means "this file has no such value", so a processor opening a file
saw four dashes that read as missing data on a file that has all four. The tabs
beside the rail show skeletons for the same period, so the rail was actively
contradicting them.

Each metric now takes `pending` and renders a skeleton, driven by the `isPending`
these hooks already return.

### The rail invented a fourth tone vocabulary

`Metric` took `tone?: "blocking" | "attention" | "neutral"` and mapped it to
classes inline — a private three-value subset of `Tone` with its own copy of the
mapping, which is precisely the shape LP-UI-005 consolidated six of. It is also
the third copy of the FIGURE variant specifically (`neutral` as
`text-foreground` rather than `text-muted-foreground`, right for a number and
wrong for a status).

`figureToneClass(tone)` is now exported from `status-token.tsx` and used by both
CalculatorCard and the rail, and `Metric` takes the real `Tone`.

### Tab detection matched the end of the URL, not the section

`pathname.endsWith("/documents")` is true for any route that finishes with that
word however deeply nested, and false for a trailing slash. `fileTabSegment()`
anchors to the file's own base and returns the first segment after it, so
`/loan-files/abc/documents/xyz` is still the documents section and
`/loan-files/abc/conditions/documents` is correctly the conditions one.

### A gated DTI read as a file with no DTI

LP-375 has the engine null a gated ratio rather than fabricate a 0, and the
calculator tile says "Gated". The rail rendered the null as `—`, which says
"this file has no DTI" instead of "a required input is unknown". It now says the
same word the tile does.

### Cleared, no change

- **`dtiTone` on decimal strings.** Correct as written. A null value or limit
  returns neutral, a non-numeric string fails `Number.isFinite` and returns
  neutral, and equality is `>` so a DTI exactly at its ceiling is not over —
  which is the right convention.
- **`reserves.headline`.** Cannot leak a machine token: `calculators.py:453`
  emits `"—"` or `f"{months} months"`, both display strings. This is unlike the
  `binding:*` case, where the leaking field was `status`, a machine enum, not a
  rendered headline.
- **The `attention` fallback on the status.** Deliberately kept, and the
  distinction from the calculators is principled. There the tone coloured a
  computed FIGURE, so an unrecognised status painted amber over a number with
  nothing wrong with it. Here it colours the STATUS ITSELF — a loan-file status
  this build does not recognise is a thing a processor should look at, which is
  what amber says. Noted in the code so the next reader does not "fix" it.

### The acceptance criterion: reword it

"Reads from the queries already cached by the file layout — no extra fetches" is
not achievable, and the hand-off is right that it contradicts the feature. The
layout caches one query; DTI, LTV and reserves belong to the Verification tab,
and not having to go there is the entire point of the rail. A criterion that
forbids the requests forbids the feature.

The criterion that was meant, and that this ticket meets, is **no DUPLICATE
requests**: every hook the rail calls is keyed identically to the tab that owns
it, so React Query serves both from one request and the rail costs nothing at
all on Verification. Reworded in the acceptance list, with the measured numbers
kept beside it.

One real cost to record rather than hide, which the +3/+4/+1 numbers do not show
on their own: the rail is `hidden xl:block`, which hides it from view, from the
tab order and from the a11y tree — but the component still MOUNTS below 1280px,
so its four always-on queries still fire for a user who cannot see it. Every fix
for that is worse than the cost: gating the hooks needs the viewport, the
viewport is only known after hydration, and a `useSyncExternalStore` with a
server snapshot still enables them on the first client render. Deferring them
properly would trade four requests on narrow screens for a guaranteed skeleton
flash on every wide one, which is the common case. Recommendation: accept it,
and revisit only if the rail's query set grows.

### The dev double-fetch is StrictMode, and is dev-only

`next.config.ts` does not set `reactStrictMode`, and Next 15's App Router
defaults it to true, so effects double-invoke in development, queries remount,
and each fetches twice — including queries this ticket never touches, which is
what the hand-off observed. It does not happen in a production build, where
StrictMode's double-invocation is compiled out. Nothing to fix; worth recording
so the numbers are not read as a regression.

### Verification

`tsc --noEmit` clean, `biome check` clean over 214 files, 555 tests pass (from
541), `pnpm build` compiles. Every fix mutation-checked:

| mutation | result |
| --- | --- |
| drop the height calc | 1 test fails |
| put a literal `p-4` back on `main` | 1 test fails |
| revert to `endsWith` tab detection | 1 test fails |
| drop the pending skeletons | 1 test fails |
| drop the gated check | 1 test fails |

The asset drift guard added in the LP-UI-007 review earned itself during this
pass: exporting `figureToneClass` from `status-token.tsx` failed
`ledger-assets.test.ts` immediately, before the change could be committed with a
stale asset. Its failure output printed both files in full, so it now reports the
first differing character with context instead.
