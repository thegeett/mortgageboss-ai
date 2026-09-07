# LP-UI-045 — The expanded calculator: result beside the math

The second of the three gaps LP-UI-044 listed. The mockup shows the expanded
calculator as two columns — the itemised math on the left, a result panel on the
right with the figure, the arithmetic that produces it, and a bar against the cap.
Ours ran the same information down the page.

## Why the old order was wrong, not just different

The panel went: the ratios, then three breakdown sections, then the formula. So
the **answer was above the working, and the arithmetic that reaches it was a
screen below**. A processor checking a 39.70% against the twenty-odd lines that
produce it had to scroll between the number and the numbers it came from, and the
formula — the one line that connects them — was below both.

Putting the result beside the math means the figure, the division and the cap are
on screen together, which is the thing a processor is actually doing when they
open a calculator.

## What changed

`lg:grid-cols-[minmax(0,1fr)_19rem]` on all three panels — DTI, LTV and the four
generic calculators — with the result column **sticky**. That is the point of the
split rather than decoration: the answer stays on screen while the reader works
down the lines that feed it.

**Single column below `lg`.** A line is a label, a figure and its source; at half a
laptop's width that wraps three times, which is worse than the scrolling this
replaces.

**The result panel is one panel, not three pieces.** The figure, the formula and
the limit bar were a ratio tile, a receipt and a bar in three places. The figure
means nothing without the division that produced it, and the division means
nothing without the limit it is judged against.

Per panel:

- **DTI** — back-end figure with its cap bar, the formula, then front-end as a
  secondary line. Front-end is the same ratio with less in the numerator; it reads
  as a variant of the headline rather than a peer beside it.
- **LTV** — LTV with its cap bar, the three formulas, then CLTV and HCLTV. Same
  argument: they are the same ratio with more of the debt stack.
- **The four generic calculators** — headline, formulas, methodology note. Inputs
  and derivation steps stay on the left.

Nothing about the data, the overrides, the editing or the gating changed. LP-375
still holds: a gated DTI shows "Gated" and the result panel shows "—" rather than
a fabricated 0 — verified on a real gated file as well as a computed one.

## Tests

Two added to `dti-calculator.test.tsx`: the result beside the math with the
sticky column, and a single column below `lg`.

Mutation-checked, 4, all caught: back to one column, two columns at every width,
the result no longer sticky, and the formula dropped from the result panel.

Verified live on a gated file and a computed one, light and dark, and every panel
measured two-column at 666px + 304px. CI green by exit code: biome, tsc, 1010
vitest. No backend changes.

## Still not the mockup

Two of LP-UI-044's three remain, both bigger than layout:

**The right rail is the shared file context rail**, not the mockup's THIS RUN /
THOROUGHNESS / MISSING DOCUMENTS. Deliberate and recorded — LP-UI-009 replaced
per-tab rails with one shared rail — but LP-UI-020's batched "request all missing
documents" has nowhere to live as a result.

**The thoroughness dial is not on the screen.** The mockup puts it in the header
beside Run verification, with three levels and their confidence thresholds. The
aggression level exists in the backend (`AggressionLevel`, LP-75/79); no control
sets it here.
