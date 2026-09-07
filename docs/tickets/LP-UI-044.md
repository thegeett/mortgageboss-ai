# LP-UI-044 — The calculator strip LP-UI-021 was named for

Reported from the running app: the Verification screen does not look like
`07-verification.png`. It did not, and the reason is worth recording because the
ticket that should have caught it passed.

## What was actually different

Comparing the mockup with the live screen, most of the Verification work had in
fact shipped — the outcome tabs (`Needs attention`, `Couldn't check`,
`Cross-checks`), the run history, the Run verification control, findings as
rail-coded rows. It was all **below the fold**, because of one thing above it.

**The calculators were a 2/3-column grid, not a strip.** Six tiles in two rows,
with an expanded panel under them, filled the first screen entirely. The mockup
has six tiles in **one row** so that the outcome tabs — the point of the screen —
are visible without scrolling.

## Why LP-UI-021 passed anyway

The ticket is titled "Verification: calculator strip" and its prose says *"Six
tiles in one strip"*. Its three acceptance criteria are about something else:
expanding without refetching, override attribution, and a gated DTI never
rendering a fabricated 0.

I checked those three, and they were genuinely met. The layout the ticket was
named for was in the prose, not the checkboxes, and I did not build it — the
ticket doc I wrote is entirely about finding counts and override attribution and
never mentions the strip at all.

**The lesson is not "read the prose".** It is that a ticket's acceptance criteria
can be a strict subset of what it asks for, and a checklist that passes is not
evidence the ticket is done. Where the mockup is the specification, the screen
has to be compared with it.

## What changed

`grid-cols-2 sm:grid-cols-3` → `... xl:grid-cols-6`. Six abreast where there is
room, degrading by the LP-UI-037 ladder: three where a tile would otherwise be too
narrow to read its own figure, two at the bottom. A tile is a label over a number,
and below about 9rem the number truncates — which is worse than a second row.

`min-w-0` on the tile button as well as its label: a grid item's default
`min-width: auto` refuses to shrink below its content, so six tiles would have
overflowed the strip instead of sharing it.

**The tile owns its label now.** It read `data?.title ?? humanizeCalc(...)`, so
the API's "Mortgage insurance" won and rendered as "Mortgage insura…" on a 9rem
tile. The tile uses the mockup's short forms — "Mortgage ins.", "Self-employed",
"Max loan" — and the unabbreviated name stays as the button's accessible name, so
a screen reader still gets it and the expanded panel still shows it in full.

That last one took two attempts: I changed `humanizeCalc` first, screenshotted,
and saw no change, because it was only the fallback.

## Tests

`calculators-strip.test.tsx` (5) — six abreast, the degradation ladder, the short
labels, the full name kept as the accessible name, and the API's long title not
getting back into the visible label.

Mutation-checked, 5, all caught: back to a grid, six abreast at every width, the
API title back in the label, the accessible name losing the full title, and a long
label returning.

Checked in light and dark. CI green by exit code: biome, tsc, 1008 vitest. No
backend changes.

## Still not the mockup, and these are bigger than a layout fix

**The expanded calculator is a tall vertical stack.** The mockup shows a compact
two-column arrangement — the math table on the left, a RESULT panel on the right
with the figure, the arithmetic expression and a bar against the cap. Ours runs
the same information down the page, which is why the tabs are still a scroll away
even with the strip fixed. That is a redesign of three components
(`dti-calculator`, `ltv-calculator`, `calculator-card`), not a layout tweak.

**The right rail is the shared file context rail**, not the mockup's
verification-specific one (THIS RUN / THOROUGHNESS / MISSING DOCUMENTS with a
batched "Request all four"). That is deliberate and recorded: LP-UI-009 replaced
per-tab rails with one shared rail. The missing-documents batching was LP-UI-020's
second departure and it is not in the rail today.

**The thoroughness dial is not on the screen.** The mockup puts it in the header
beside Run verification, with the three levels and their confidence thresholds.

I have not built these because each is a real piece of work with its own
decisions, and the report was about how the screen looks rather than a request for
three more features. They are listed so the gap is known rather than discovered
again.
