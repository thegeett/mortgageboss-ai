# LP-UI-006 — Density retune of the `ui/` primitives

- **Ticket:** LP-UI-006 — bring the vendored shadcn primitives to Ledger's geometry
- **Epic:** Ledger redesign → Epic B (Primitives and shell) — first of six
- **Status:** Completed
- **Date:** 2026-08-29

## Summary

The vendored shadcn defaults are built for a marketing-adjacent app: 40px
controls, 16px text, 24px card padding, a shadow on every panel. Ledger is a
28px-row tool. Eleven primitives were retuned, and — as in LP-UI-004 — the
primitives alone did not produce the result, because call sites had been
compensating for the old defaults for two epics.

## What Changed

### The primitives

| file | before | after |
|---|---|---|
| `button` | 40 / 36 / 44 / 40² | **28** / `sm` **24** / `lg` 32 / `icon` 28² / new `icon-sm` 24² |
| `input` | h-10, `text-base`, py-2 | h-7, `text-sm`, px-2.5 |
| `select` | h-10, px-3 py-2 | h-7, px-2.5 |
| `textarea` | min-h-80px, `text-base` | min-h-4.5rem, `text-sm` |
| `card` | `shadow-sm`, p-6, title `text-2xl` | no shadow, p-3, title `text-sm`, new `floating` prop |
| `badge` | px-2.5, `font-semibold` | px-2, `font-medium` |
| `dialog` | p-6, `bg-background` | p-4, `bg-popover` |
| `sheet` | header px-6 py-4 | px-4 py-3 |
| `tooltip` | px-3 py-2 | px-2 py-1 |

Button icons went `size-4` → `size-3.5`: a 16px glyph in a 28px control is
heavier than the 13px text beside it.

`Card` gains `floating?: boolean` rather than a `variant`, because there are
exactly two states and one of them is rare. Dropdown, popover, tooltip and
dialog have their own primitives and should not reach for it.

### One focus mechanism instead of two

Every primitive drew its own `focus-visible:ring-2 … ring-offset-2` **and**
inherited the global `:focus-visible` outline LP-UI-001 added — two indicators of
different shapes on the same element. The ring utilities are gone; the global
outline is the single mechanism, at exactly the SPEC's 2px / 2px offset.

That change had a trap in it, which is the part worth recording. Removing the
rings left `focus-visible:outline-none` behind on seven primitives, and Tailwind's
`outline-none` is not "no outline" — it compiles to a **transparent 2px outline**,
which beats the global rule. Buttons, inputs, selects, textareas, badges and both
close buttons would have shipped with *no visible focus indicator at all*, in a
ticket whose acceptance says "focus ring 2px at 2px offset". Removed from all
seven. The four `outline-none`s left are dropdown menu items, where Radix drives
the roving highlight through `focus:bg-accent` and an outline would be wrong.

### The call sites that were compensating

**46 height overrides, every one on `Button`.** All predate this ticket and all
were shrinking shadcn's oversized defaults; against a 28px default they now
*enlarge*. Classified before touching them:

| n | call site | pinned | new default | effect |
|---|---|---|---|---|
| 27 | `size="sm"` + `h-7` | 28px | 24px | larger |
| 9 | `size="icon"` + `h-8` | 32px | 28px | larger |
| 3 | `size="icon"` + `h-7` | 28px | 28px | redundant |
| 3 | `size="sm"` + `h-8` | 32px | 24px | larger |
| 2 | `size="default"` + `h-8` | 32px | 28px | larger |
| 1 | `size="icon"` + `h-9` | 36px | 28px | larger |
| 1 | `size="sm"` + `h-6` | 24px | 24px | redundant |

The 27 are the interesting group: those authors wanted **28px**, which is exactly
what `default` now is. Dropping only the `h-7` would have shrunk them to 24px —
changing the design while claiming to systematise it. So the override *and* the
now-wrong `size="sm"` both go, landing them on the default at the size they were
drawn at. Same for the three at `h-8`. `size="icon"` sites lose their `h-`/`w-`
pair and land square at 28px. Zero height overrides on `Button` remain.

**25 shadows across 21 files.** `Card` losing its default shadow achieves nothing
while 14 call sites pass `shadow-sm` back in — the same shape as `bg-white` in
LP-UI-004. Every one is a panel sitting in the page: dashboard cards, the
calculators, the activity feed, the needs list, the verification panel, both
loading skeletons, the login and landing cards. All removed, along with a
now-redundant `shadow-none`. The only shadow left outside `ui/` is the version
selector's dropdown, which genuinely floats.

## Verification

**Geometry, measured in the browser** across four routes — not read off the diff:

| route | control heights (px → count) |
|---|---|
| verification | **28 → 207**, 24 → 2, 23 → 13, 39 → 6, 40 → 2 |
| overview | **28 → 42**, 40 → 2 |
| dashboard | **28 → 11**, 24 → 2, 33 → 4, 40 → 2 |

The residual 33px and 40px are the dashboard filter pills and the user menu —
hand-rolled elements that never used `Button`. They are a finding, not an
oversight; see below.

**The 24×24 floor holds.** Every interactive element with an icon and no text was
measured on all four routes: **zero under 24×24**.

**Focus actually paints.** Programmatic `.focus()` does not match `:focus-visible`,
so the first probe reported `outline-style: none` and looked like a regression —
it was the probe that was wrong. Driving real `Tab` keypresses through CDP:

```
tag=tr      focusVisible=true  outline: solid 2px rgb(18,84,94) offset 2px  boxShadow: none
tag=button  focusVisible=true  outline: solid 2px rgb(18,84,94) offset 2px  boxShadow: none
```

`rgb(18,84,94)` is `--ring` (petrol `#12545E`), and `boxShadow: none` confirms
nothing double-draws.

**Contrast did not regress.** The LP-UI-004 sweep re-run over four routes in both
themes: **964 text nodes, 0 AA failures**, unchanged.

**Both themes screenshotted** on all four routes. Cards read as hairline plus a
surface step, which is what rule 1 is asking for.

**CI.** biome, tsc, 484 tests, build — green.

## Findings raised

1. **Hand-rolled controls that never used the primitives.** The dashboard filter
   pills (33px) and the user menu (40px) are `<button>` elements with their own
   classes, so retuning `Button` does not reach them and they now sit visibly
   outside the 28px system. `aggression-dial`'s segments are the same shape. They
   belong to their screen tickets (LP-UI-012 onward) but are worth naming now,
   because a geometry census that only counts `Button` will report success while
   they drift.

2. **`Card`'s `floating` prop has no consumers.** Third time in this epic —
   `--skeleton` and `--ai` in LP-UI-004, `StatusRail` in LP-UI-005. A shipped
   affordance with no call site is a thing nobody has yet tested. Whether the
   version selector's dropdown should use it rather than its own `shadow-lg` is
   the obvious first question, and it belongs to LP-UI-024.

3. **`CardTitle` dropped from `text-2xl` to `text-sm`.** That is a 26px → 13px
   change on every `CardTitle`, which is right for a panel heading in this system
   but is a large visual move made inside a "primitive retune". Called out
   explicitly so it is reviewed as a design decision rather than skimmed as
   plumbing.

## Assumptions and decisions

- **Decided** `lg` becomes 32px rather than staying 44px. A single scale that
  runs 24 / 28 / 32 keeps the relationship legible; a 44px button in a 28px-row
  tool is a different product's control.
- **Decided** to add `icon-sm` (24×24) rather than let call sites hand-write a
  smaller icon button and drift under the floor.
- **Decided** `dialog` moves from `bg-background` to `bg-popover`. It floats, and
  `--popover` is a step above `--card` in dark specifically so a floating layer
  reads against the page behind it.
- **Assumed** the `sm` sites pinned at `h-7`/`h-8` wanted the pixel size they
  drew, not the variant name. Preserving the size and dropping the variant is the
  reading that changes the fewest pixels.

## Files

- `components/ui/`: button, input, select, textarea, card, badge, dialog, sheet,
  tooltip, error-state
- 21 files, shadows removed; ~30 files, Button height overrides removed

## Review pass — four defects across three tickets

A `/code-review` over the LP-UI epic found four. Two land in LP-UI-005's status
vocabulary, one in this ticket's density retune, and one in LP-UI-001's config;
they are recorded together here because they were found together, with the file
each fix touches named.

### `CalculatorStatus` was exhaustive over the wrong set (LP-UI-005's file)

LP-UI-005's review pass declared `CalculatorStatus` in `lib/status.ts` "so the
map is still exhaustive over something". It was — over the display map it
replaced, rather than over the producers. There are **three**, not one, and they
all reach `CALCULATOR_STATUS` through `CalculatorsSection`'s `Tile`:

| producer | values |
| --- | --- |
| `DtiTile` | `DtiLimitStatus`, plus a literal `"unknown"` for a gated DTI |
| `LtvTile` | `LtvLimitStatus` |
| `CalcTile` | `CalculatorView.status` — `str \| None` on the wire |

`unknown` and `binding:*` were in neither. `services/calculators.py:573` emits
`"binding:" + result.binding_key` for `dti` / `ltv` / `loan_limit`, so those fell
through to `humanizeUnknown`, which only swaps underscores: `"binding:dti"` →
`"Binding:dti"`. A `variant="dot"` tile carries its label **only** in `title` and
an `sr-only` span, so on any file where max_loan resolves — which is most —
hovering the Maximum-loan tile showed the tooltip "Binding:dti" and a screen
reader read that string aloud. The `STATUS_DOT`/`dot()` map this replaced fell
back to a silent grey dot with no text at all, so the leak was new.

The two limit unions are now imported **by type** rather than retyped, so a new
member in `lib/types/dti.ts` breaks the map at compile time. The third has no
frontend union to import, so its values are listed against the backend lines that
emit them — the only place they can be checked against — and a test pins the full
producer output, asserting no label contains a colon or equals its own key.

`unknown` reads "Not determined" (`neutral`): it says the limit, or the ratio for
a gated DTI, could not be established, which is honest rather than alarming. The
three `binding:*` read "Limited by DTI / LTV / the program limit", also `neutral`
— every file with a computed max loan has a binding constraint, so it is
information, not a finding.

### `groupNeeds` still hard-crashed the Needs dashboard (LP-UI-005's file)

`buckets[NEEDS_GROUP[need.status]].push(need)`: an unrecognised status makes the
index `undefined`, `buckets[undefined]` `undefined`, and `.push` a `TypeError`.
`NeedsDashboard` calls `groupNeeds` before rendering any card, so **one**
unrecognised need blanked the entire page — including the needs the build did
understand. Now `?? "needs_action"`, matching `resolveStatus`'s `attention`
default: an unrecognised need is work someone has to look at, and the chase pile
is where they will see it.

`outstandingNeedsCount` had the milder version — it silently under-counted — and
got the same fallback. It is the headline number sitting beside the group it
counts, and the two disagreeing would be worse than either being wrong alone.

The sting is that LP-UI-005's review pass hardened `isTerminalStatus` against
precisely this and wrote a comment explaining why, while the call that runs first
and fails hardest kept the unguarded index.

### The density retune re-armed iOS auto-zoom (this ticket's file)

`input.tsx` and `textarea.tsx` lost their `text-base … md:text-sm` pair for a
flat `text-sm`. Mobile Safari zooms the viewport whenever a focused control
computes under 16px and does not zoom back out; `text-sm` is 0.8125rem (13px) at
every breakpoint, so tapping the dashboard search, any intake field or any
override input zoomed the page. `header.tsx` carries a `md:hidden` mobile nav, so
the viewport is reachable rather than theoretical.

The obvious fix is wrong here. **`text-base md:text-sm` does not work in this
scale** — `base` was retuned to 0.875rem (14px), still under the threshold. The
scale now carries a named `field` size at exactly 1rem, and both controls wear
`text-field md:text-sm`, so the reason travels with the token instead of resting
on `base` never being retuned again. A test pins `field` at 1rem.

### `fontSize` sat under `theme.extend` (LP-UI-001's file)

The same trap `tailwind.config.ts` documents seventeen lines above it for
`fontWeight`, and for the same reason: `extend` **merges**. `xs`…`2xl` were
retuned while Tailwind's stock ramp survived above them, so `text-3xl` and up
resolved to stock — no tracking — and the scale jumped from a tracked 26px `2xl`
straight to an untracked 30px `3xl`. Six live sites: the dashboard stat numbers,
the marketing hero, and the four DTI/LTV headline figures.

Moved to `theme` level, which REPLACES the ramp — so `3xl` had to join the scale
or all six would have compiled to nothing, which is the LP-UI-002 failure exactly.
It keeps stock size and line-height (the 1.2 ratio the rest of the scale uses was
already right) and adds the missing tracking. `text-4xl` and up now genuinely do
not exist, matching the weight cap's discipline, and a test pins the key set.

### Verification

`tsc --noEmit` clean, `biome check` clean over 206 files, 491 tests pass,
`pnpm build` compiles. Each fix was mutation-checked against the failure it
prevents:

| mutation | result |
| --- | --- |
| remove the `binding:*` entries | 1 test fails |
| revert `groupNeeds` to the unguarded index | 2 tests fail, on the real `TypeError` |
| move `fontSize` back under `extend` | 2 tests fail |
| drop `field` below 16px | 1 test fails |

The stylesheet was compiled and all ten distinct font-size classes in the tree
checked individually — every one emits CSS, including `file:text-sm` and the new
`text-field` and `text-3xl`.

### Noted, not changed

- **`text-label` has zero consumers.** A purpose-built token in the same position
  `--skeleton` and `--ai` were in twice before: introduced for the uppercase
  eyebrow and shipped with nothing using it. The uppercase eyebrows in the tree
  are still spelled as `text-[11px] uppercase tracking-wide` by hand.
- **`input.tsx` is `h-7` (28px).** With `text-field` at 16px/20px on mobile that
  leaves a 4px gutter — workable but tight. If the mobile fields read as cramped,
  the fix is a responsive height, not shrinking the text back under 16px.
