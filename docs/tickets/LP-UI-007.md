# LP-UI-007 — Table: 28px rows, sticky header, grid semantics

- **Ticket:** LP-UI-007 — the dense table
- **Epic:** Ledger redesign → Epic B (Primitives and shell)
- **Status:** Completed
- **Date:** 2026-08-29
- **Mockup:** Pipeline

## Summary

`TableHead` was `h-12` and `TableCell` `p-4` — 53px rows. Both now come from
`--row-h` / `--row-px`, so LP-UI-010's density switch will move every table at
once. Measured in the browser: **rows are exactly 28px**, header 28px, cell
padding 12px.

The accessibility half mattered more. Every row carried `tabIndex={0}` and every
row's action button another, so a nine-file table was ~18 tab stops between the
search box and the page's real controls — and a forty-file table would be ~80.
It is now **one** tab stop with arrow-key navigation, per the ARIA grid pattern.

## What Changed

### `components/ui/table.tsx`

- `TableHead` / `TableCell` share `h-row px-cell py-0`; the `py-0` kills the UA's
  1px vertical padding on `td`, without which `--row-h` is not the whole story.
- `TableHeader` is `sticky top-0 z-30` with its own background.
- `border-separate border-spacing-0`, and the hairline moved from the row to the
  cells. A sticky cell needs its own background, which a collapsed border box
  will not give it — and `border-collapse` drops row borders under separation.
- `stickyFirstColumn` pins column one, with the shadow gated on `scrollLeft > 0`
  through a context the cells read.
- `containerClassName` so a caller can bound the scroll area's height.

### `components/dashboard/file-table.tsx`

- `role="grid"` with `aria-rowcount` / `aria-colcount`, `aria-rowindex` on every
  row (header is row 1), `aria-colindex` on every cell.
- `useRovingRows` — one row holds `tabIndex={0}`, the rest `-1`. ArrowUp/Down
  move it, Home/End jump, Enter/Space opens, ArrowRight enters the row's action
  menu and ArrowLeft/Escape returns. The menu button is `tabIndex={-1}`.
- Focus is only stolen when the move came from a keypress — a refetch that
  re-focused a row would yank the caret out of the search box mid-type.
- The roving index is clamped when filtering shrinks the list beneath it;
  otherwise the grid becomes unreachable by keyboard entirely.
- Skeleton bars dropped `h-4` → `h-3` so a loading row and a real row are the
  same height and nothing jumps when data arrives.
- The row menu became `size="icon-sm"`. A 28px `size="icon"` button cannot fit
  inside a 28px row once the cell padding and the hairline are counted — it was
  measured at 31px. This is what LP-UI-006 added `icon-sm` for.

## Verification

**Geometry, measured:** row heights `[28]` — a single value across all rows —
header 28px, cell padding 12px, against `--row-h: 1.75rem`.

**One tab stop, counted by pressing Tab.** Forty synthetic Tab presses through
CDP, recording `document.activeElement` each time. The grid appears **exactly
once per cycle** through the page. Two ArrowDowns then moved focus from
`aria-rowindex` 2 to 4.

**Sticky header — and it took two fixes to actually work.** See Findings; the
final measurement, with `main` scrolled 500px:

```
mainScrollTop 500   headerTop 64   mainTop 64   gridTop -141   STUCK true
```

The grid has scrolled 141px above the viewport while the header sits pinned at
the top of `main`.

**Sticky first column, tested under real scroll.** No table uses it yet, so
rather than ship it unverified I built a probe carrying the exact class strings
the component emits, in a bounded container, and scrolled it 400px across and
60px down:

```
firstColumnPinned true   secondColumnScrolledAway true   headerPinned true
shadowWhenScrolled  rgba(16,22,23,0.12) 8px 0px 8px -8px
```

The first attempt at this probe reported `canScrollX: false` — it could not
scroll, so its "pinned" result was vacuous. Recorded because the fix was to
notice the measurement was empty, not to trust it.

**Nine keyboard tests, mutation-checked.** A test that has never failed proves
nothing, so the suite was run against two deliberate regressions:

| mutation | tests that failed |
|---|---|
| `tabIndex={0}` on every row (the pre-ticket behaviour) | 3 |
| `Home` key handler deleted | 1 |

**CI.** biome, tsc, **500 tests** (up from 491), build — green.

## Findings raised

1. **Two independent ancestors each silently defeat a sticky header, and neither
   is visible from the table.** `position: sticky` resolves against the nearest
   scrollport, and *any* `overflow` other than `visible` creates one — including
   `overflow: hidden`.

   - shadcn wraps every table in `div.overflow-auto`. That box grows with its
     content, so it never scrolls, so a header sticking to it can never move.
     CSS offers no escape: setting `overflow-x: auto` forces `overflow-y` to
     compute to `auto` as well, so a horizontally-scrolling wrapper is always
     also a vertical scrollport. The wrapper now only becomes a scrollport when
     the caller asks for one.
   - `dashboard/page.tsx` wrapped the table in `<Card className="overflow-hidden">`
     to clip it to the card's radius. That was the second trap, and it survived
     the first fix. Removed from the page and its loading skeleton.

   Both are worth knowing before Epic C adds more tables: a sticky header is a
   property of the whole ancestor chain, not of the table.

2. **`stickyFirstColumn` has no consumer.** Having both a sticky header and a
   sticky first column requires the container to own the vertical scroll, which
   requires a bounded height — and today's shell has none. That arrives with
   LP-UI-008's full-bleed work surface, and the Pipeline screen (LP-UI-012) is
   where it should first be used. Unlike the previous unused affordances in this
   epic, its mechanics are verified rather than assumed.

3. **`pnpm build` while `next dev` is running clobbers `.next`.** The dev server
   then serves 404 for every chunk and the app renders as unstyled text. It cost
   a screenshot cycle here and looked exactly like an auth failure. Worth a line
   in the development workflow docs.

## Assumptions and decisions

- **Decided** row-level roving rather than cell-level. The ticket asks for arrows
  between rows, and a processor scanning a file list is choosing a row, not a
  cell. `aria-colindex` is still on every cell so position is announced.
- **Decided** ArrowRight reaches the row menu rather than giving it a tab stop.
  The grid pattern reaches a widget inside a cell with the arrow keys; a tab stop
  per row is the thing this ticket exists to remove.
- **Decided** to suppress `lint/a11y/useSemanticElements` for `role="grid"` with
  a written reason. An ARIA grid is an interactive widget, not a static table,
  and the WAI-ARIA APG data-grid pattern puts `role="grid"` on a `<table>`.
  Dropping it would leave the roving tabindex with no semantics.
- **Assumed** arrows should not wrap at the ends. A list of files has a first and
  a last; wrapping loses that.

## Files

- `components/ui/table.tsx` (rewritten)
- `components/dashboard/file-table.tsx`, `file-table.test.tsx` (+9 tests)
- `app/(protected)/dashboard/page.tsx`, `loading.tsx` — the `overflow-hidden` trap

## Review pass — two keyboard traps, and a rule that keeps coming undone

A `/code-review` found four defects. Two are in this ticket's roving-tabindex
grid, one is the third instance of a rule LP-UI-006 wrote down, and one is the
ledger assets drifting for the third review running.

### Enter on the row menu navigated instead of opening it

`useRovingRows`'s `onKeyDown` is bound on the `<tr>`, and every keydown from
inside a cell bubbles to it. Nothing checked the target, so the row answered keys
meant for the row-actions button. Combined with this ticket's own decision to
give that button `tabIndex={-1}`, **ArrowRight is the only way to reach it** — so
a keyboard user arrows right onto "Actions for LF-1234", presses Enter, and the
row's `Enter` case runs `preventDefault()` + `onActivate(index)` and navigates to
the loan file. Delete-file was unreachable by keyboard entirely. Arrow/Home/End
on the focused button likewise moved the roving stop out from under it.

`onKeyDown` now early-returns unless `event.target === event.currentTarget`.

### The focus flag stayed armed after a move that never happened

`move()` set `shouldFocus.current = true` before `setActive(to)`. When
`to === active` — ArrowUp on row 0, ArrowDown or End on the last row, all
reachable by holding a key — React bails out of the same-value update, the
`[active]` effect never runs, and the flag stays armed. The next time `active`
changes for a non-keyboard reason (the `[count]` clamp, on a refetch or a filter)
the focus effect fires and pulls focus onto a table row.

That is exactly what the comment above the flag says it exists to prevent: "would
yank the caret out of the search box mid-type". A processor typing in the search
box lost the caret on the next poll.

`move()` now returns early when the index is unchanged. That guard would have
broken the ArrowLeft/Escape return path — the row being returned to is almost
always already the active one, so a state-change-driven focus is a no-op exactly
when it is needed — so `onCellKeyDown` focuses the row directly instead.

### The iOS zoom rule, broken a third and fourth way

LP-UI-006 added `text-field md:text-sm` to `Input` and `Textarea` and SPEC's
amendment wrote the rule down. `Select` — the third form control — was missed.

Chasing that turned up two more shapes of the same defect:

- **Raw controls in feature code.** `admin/validation`'s filter `<select>`,
  `extraction-bench`'s path `<input>`, `document-drawer`'s document-type
  `<select>` and `rule-finding-actions`' note `<textarea>` are real form controls
  that never went through the primitives. The last two were also wearing
  `border-border` (the 1.2:1 decorative hairline) rather than `border-input` (the
  3:1 control border), which is the one place the new two-border rule was not
  held.
- **Callers overriding the primitive from outside.** `cn` puts the caller's
  className last and tailwind-merge treats every font size as one group, so
  `<Input className="h-8 text-sm">` silently beat the primitive's own
  `text-field md:text-sm`. Thirteen of these across seven files — the overview
  editable rows, the lender admin form, the DTI/LTV/calculator override inputs,
  the stated-financials editor and the finding-card note box. A caller's
  className is for geometry; the size belongs to the control.

`components/ui/form-control-zoom.test.ts` now holds all three shapes: every
control file sets `text-field`, the three primitives carry no unprefixed font
size, and no `<Input>`/`<Select>`/`<Textarea>` call site anywhere in `app/` or
`components/` passes one down.

A note on building that test, because the lesson is the point of it. The first
version terminated an element's attributes at the first `>`, which meant
`onChange={(e) => …}` ended the match early and it captured no className at all
— so it **passed the mutation**. It only surfaced because the fix was
mutation-checked rather than assumed; the corrected matcher then found ten sites
the review had not reached. A test that cannot fail is the same defect this epic
has now fixed twice (LP-UI-005's coverage tests, LP-UI-002's `border`/`input`
assertion), and it nearly shipped a third time.

### The ledger assets, third review running

`assets/lib/status.ts` was behind on the `CalculatorStatus` union — no `unknown`,
no `binding:*`, i.e. the exact "Binding:dti" a screen reader read aloud — and
`assets/fonts.ts` still had `plexSerif` italic-only. Both are the fixes the
*previous* review pass landed. `TICKETS.md` points implementers at these as
drop-in sources, so copying one forward reintroduces whatever it is behind on.

Copied from the shipped files, and `ledger-assets.test.ts` now compares each
asset to the file it seeds with whitespace normalised — the assets are
hand-aligned for reading (globals.css lines its trailing comments up) and the
shipped files are Biome-formatted, which is a difference worth keeping and the
only one worth tolerating.

Committing that test required committing the working-tree fixes to
`assets/tailwind.config.ts` and `assets/components/status-token.tsx` as well:
their committed versions were still drifted, so the test would have gone red on a
clean checkout without them.

### Also fixed

`TableBody` lost `[&_tr:last-child]:border-0` in this ticket, leaving a trailing
hairline under the last row. Restoring the old selector would not have worked —
`TableRow` moved its hairline from the row to the CELLS when it went
`border-separate` for the sticky header — so it is now
`[&>tr:last-child>*]:border-b-0`.

### Verification

`tsc --noEmit` clean, `biome check` clean over 208 files, 520 tests pass,
`pnpm build` compiles. Every fix mutation-checked:

| mutation | result |
| --- | --- |
| drop the event-target check | 2 tests fail |
| arm `shouldFocus` unconditionally | 1 test fails |
| revert `Select` to `text-sm` | 2 tests fail |
| put `text-sm` back on EditableRow | 1 test fails |
| put an asset back behind its shipped file | 1 test fails |

The stylesheet was compiled and every font-size and border class in the tree
checked against it, including the new `[&>tr:last-child>*]:border-b-0`.
