# LP-UI-046 — The thoroughness dial, where it can be found

The last of LP-UI-044's three gaps. The mockup puts a thoroughness control in the
header beside Run verification; the screen had none.

## It existed. Nobody could reach it.

`AggressionDial` has been built since LP-79 and is mounted — inside `LegacyBody`,
the **Old findings** tab. That is the quarantine for the legacy AI sweep (LP-376),
and the one tab a processor has no reason to open. A control nobody finds is a
control that does not exist.

Worse, the run controls themselves sat **~1,400px down the page**: the route
rendered `CalculatorsSection` above `VerificationPanel`, so the calculator strip
and an expanded panel came before the heading, the version selector and Run
verification.

## What it filters, and the thing I nearly got wrong

The obvious build is "apply the confidence cutoff to the governed tabs too". I
measured before doing that, and it would have been a bad mistake.

On a real file: 38 governed rule findings — 23 at confidence 1.0, 11 at 0.95, one
at 0.9, one at 0.85, and **two at 0.4**. Both of the two are
`evaluation_outcome: needs_review` — the outcome whose entire purpose is that a
human must look at it.

So a confidence dial over the governed tabs would hide precisely the findings that
most need a person, **at the default setting**. The governed engine's confidence
is not a hunch-strength either: a deterministic rule emits 1.0 because the
comparison is exact (`DETERMINISTIC_CONFIDENCE`), so the number means something
different there than it does over the sweep.

The dial therefore governs the AI cross-source sweep, as it always has — and the
menu **says so**, because a control in the page header implies it governs the
page:

> Re-filters the AI cross-source findings already on this file. It never re-runs
> anything, and it never hides a rule finding — those are shown in full on the
> tabs above.

## What changed

**`ThoroughnessControl`** — a compact header control reading "Thoroughness:
Balanced", opening to the three levels with each one's threshold **and its cost**:
`≥ 80% confidence · 3 shown`, `≥ 50% · 6 shown`, `every finding · 9 shown`. A
cutoff with no count is a setting whose effect you discover by choosing it, which
is the mockup's reason for pairing them.

Thorough reads "every finding" rather than "≥ 0% confidence", because that is what
it means.

**The calculators moved inside the panel**, between the run controls and the
outcomes, as the mockup has them. The run controls went from 1,429px to **130px** —
above the fold on a laptop. This is what makes the dial reachable at all; putting
it in a header that nobody scrolls to would have been the same bug one level up.

The existing `AggressionDial` block stays on the Old findings tab. Two controls
for one setting is not ideal, and removing it is the sort of thing a reviewer
should weigh — it carries the reset-to-default and set-as-my-default actions the
header control does not.

## Tests

`thoroughness-control.test.tsx` (6) — the active level on the trigger, each
threshold with its count, "every finding" rather than 0%, picking a level, the
scope note in both its halves, and disabled while a change is in flight.

Mutation-checked, 6, all caught: the count dropped, Thorough reading as "≥ 0%",
the scope note removed, picking doing nothing, the control staying live while
busy, and the dial leaving the header.

Verified live: the menu opens, reads 3/6/9 on a real file, and picking Thorough
switches the level and persists it. Checked light and dark. CI green by exit code:
biome, tsc, 1016 vitest. No backend changes — the endpoint, the levels and the
per-file override have existed since LP-79.

## Noted

**The mockup's THOROUGHNESS panel lives in the right rail**, with the same three
levels and the line "Moving the dial re-filters what's already been found. It
never re-runs the AI." Ours is in the header instead, because the right rail is
the shared file context rail (LP-UI-009) rather than a verification-specific one.
That is the remaining gap from LP-UI-044 and it is a decision about the rail, not
about this control.

**Two controls now set one value.** The header control and the block on the Old
findings tab. The block has actions the header does not (reset to default, set as
my default), so it is not simply redundant — but a processor who finds both will
reasonably wonder which one is real.
