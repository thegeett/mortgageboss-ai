# LP-UI-042 — Zoom in the document preview

Asked for from the running app: the preview had no zoom at all. A page arrived
fit-to-column and stayed there, which is wrong for the two ends of the job — a
processor squinting at a figure in a scanned pay stub, and one who wants a whole
page in view at once.

## CSS, not a re-render

The page already arrives at **2× its point size** — a 612pt page is ~1224px of
image landing in a ~736px column, so there is real oversampling to spend. Scaling
that in CSS is instant, needs no round trip, and is sharp for the whole of
zoom-out and up to roughly **165%** before the browser starts inventing pixels.

The alternative is asking the server for a larger render at each step. It costs a
request per click and buys sharpness only *above* the range this covers. The
endpoint already takes a `zoom` parameter (capped at 4×), so that remains
available for the day someone needs to read a signature at 400% — it is a
different feature, not a better version of this one.

## What it does

Six steps — 50, 75, 100, 125, 150, 200% — with `−`, a percentage readout and `+`
beside the pager, separated by a rule because they move different things.

**The readout is the reset.** Its accessible name says so ("Zoom is 150%. Reset
to fit the column."), and it disables itself at fit. A separate "Fit" button would
be a third control for a job this one already does.

**Keyboard:** `+`/`=` in, `−`/`_` out, `0` back to fit — added to the LP-UI-033
binding table and to the `?` sheet, whose agreement test failed until both sides
matched, which is what it is for. `=` and `_` are bound because they are the
unshifted keys `+` and `−` share on a full keyboard.

**Zoom persists across pages and documents** for the session. A processor who
zoomed in to read small print is still reading small print on the next page.

## The highlight boxes come with it for free

`zoomWidth` scales the **wrapper**, and LP-UI-031's overlay is positioned in
percentages of that same element — so the boxes scale exactly with the page.
Measured live at four zoom levels: the box stays at 57.5% of the image width at
every one. Sizing the `<img>` instead would have left the overlay behind at the
old size, which is why the test asserts on the wrapper.

## The detail that is easy to get wrong

The width base is `min(100%, 46rem)`, not a flat `46rem`. On a narrow pane a
fixed base makes 50% *wider* than the pane it is supposed to fit inside — the
zoom-out control would zoom in. Both the unit test and a mutation cover it.

`zoomIn`/`zoomOut` return the **current** value at the ends rather than
`undefined`; a `?? current` that was missing would set the zoom to `NaN` and blank
the page.

## Tests

`zoom.test.ts` (8) — the ladder ordered and monotonic, stepping, stopping at both
ends, recovery from an off-ladder value, the sharpness claim, and the width base.
`page-canvas.test.tsx` grew to 15 — the readout, both directions, both ends, the
reset, and that the wrapper is what scales.

Mutation-checked, 6, all caught: stepping past the end returning undefined, a
fixed width base, the wrapper not scaled, zoom-in offered at the top of the
ladder, `0` no longer resetting, and `−` reading as zoom in.

Verified live in the browser: the readout, both keys, and the highlight box
holding its proportion at 75/100/125/150%. CI green by exit code: biome, tsc, 988
vitest. No backend changes.

## Not done

**Zoom is not persisted between sessions.** The pane split is (LP-UI-030 put it
on the user), and zoom could join it — but that is a preference write on every
click unless it is debounced, and I have no evidence yet that a processor wants
yesterday's zoom rather than a fresh fit. Left as session state deliberately.

**No fit-to-page.** The steps are all fit-to-WIDTH multiples; a "whole page on
screen" step needs the viewport height, which the canvas does not currently
measure. 50% is close to it on a typical pane and is not the same thing.
