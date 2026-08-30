# LP-UI-004 — Codemod: `gray-*` to design tokens

- **Ticket:** LP-UI-004 — remove the hardcoded neutral palette
- **Epic:** Ledger redesign → Epic A (Foundation)
- **Status:** Completed
- **Date:** 2026-08-29
- **Blocks:** every screen ticket

## Summary

The codemod ran clean — 803 replacements across 70 files, exactly the asset
footer's re-measured figure. It did not, on its own, make dark mode work.

Its pattern matches `{prop}-gray-{shade}` and nothing else, so three categories
of hardcoded neutral passed straight through it *and* through the ticket's
acceptance greps: 40 `bg-white`, 2 `text-white`, 1 `bg-black`, and 2
`shadow-gray-900/5`. A run reporting "nothing left unmapped" and a clean
`rg "gray-[0-9]"` were both true while 45 hardcoded neutrals remained, and the
`bg-white` surfaces are precisely the ones that pin the app to light.

Landed as two commits so the mechanical diff stays reviewable on its own:
the codemod and its named fixes, then the surfaces the pattern cannot see.

## What Changed

**Commit 1 — mechanical.** 803 replacements, 70 files. Largest movements:
`text-gray-400` (177) and `text-gray-500` (143) → `muted-foreground`.
`text-gray-400` was 2.54:1 on white and the most-used text colour in the app, so
this is as much an accessibility fix as a palette one. Plus, by hand:

- `tooltip.tsx`, `ltv-calculator.tsx:240` — the two inverted surfaces the asset
  footer names; a dark tooltip over a light page, sent to `foreground` /
  `background` so it inverts correctly in dark too.
- `app/page.tsx`, `login/page.tsx` — `shadow-gray-900/5` → `shadow-foreground/5`.
- the same two files — the A3 gradients, `hsl(217_91%_60%_/_0.08)` →
  `hsl(var(--primary)_/_0.08)`.
- `documents.test.ts` asserted `className` contains `"gray"`. Its intent is
  "this note is muted, not a status"; it now asserts `text-muted-foreground`.

**Commit 2 — the surfaces the pattern cannot see.** 28 files:

| from | to | n | why |
|---|---|---|---|
| `bg-white` | `bg-card` | 38 | every one is a panel raised off the page — cards, list rows, empty states, header, sidebar, form controls |
| `bg-white` | `bg-popover` | 2 | `sheet.tsx` and `version-selector.tsx` genuinely float; `popover`'s dark value is a step lighter than `card` so the layer still reads |
| `text-white` | `text-primary-foreground` | 2 | both sit on `bg-primary` |
| `bg-border/70` | `bg-skeleton/70` | 1 | see Findings |

`bg-black/80` in `dialog.tsx` is deliberately left. It is a modal scrim, not a
surface: it dims the page behind the dialog and is correctly black in both
themes. There is no scrim token and it does not need one.

## Verification

**The four acceptance greps.** `gray-[0-9]`, `217 91%|217_91%`, hex literals, and
every other Tailwind palette scale — all clean across `app/`, `components/`,
`lib/`. The only `gray` matches left are two comments in `globals.css`
documenting the mapping itself, which the AMENDMENTS wording already exempts
("outside comments").

**Contrast, measured across both themes rather than eyeballed.** A script walked
every leaf element carrying visible text on four screens, computed each one's
colour against its nearest opaque ancestor background, and applied the WCAG
threshold for its own size and weight (3:1 for large text, 4.5:1 otherwise).

| screen | text nodes | light | dark before commit 2 | dark after |
|---|---|---|---|---|
| overview | 238 | 0 | **87** | 0 |
| verification | 662 | 0 | **15** | 0 |
| documents | 61 | 0 | **37** | 0 |
| dashboard | 83 | 0 | **8** | 0 |

**2,088 text nodes, both themes, zero AA failures.** The 147 dark failures were
almost all the same shape — `rgb(233, 238, 237)` at 1.17:1, i.e. the dark
`--foreground` sitting on a `bg-white` panel that never flipped. That is the
codemod's blind spot rendered as a number.

**Looked at, not just measured.** Verification and overview screenshotted in both
themes. Dark reads correctly: petrol on the active tab and nav, amber on the
unresolved-findings banner, salmon `destructive` on the over-limit DTI with its
"Over limit" badge, cards stepped off the background by a hairline, tabular
figures aligned.

**CI.** biome (no fixes), tsc, 400 tests, build — green.

## Findings raised

1. **The codemod's report is not evidence the palette is gone, and neither are
   the acceptance greps.** `PATTERN` covers eight props and only numbered gray
   shades. `shadow` is not in the prop list, and `white` / `black` are not
   shades, so `shadow-gray-900/5`, `bg-white`, `text-white` and `bg-black` never
   even became candidates — they are absent from the "NOT MAPPED" report rather
   than listed in it. Silence there means "did not match", not "nothing left".

   Worth fixing in the asset, since Epic B onwards will keep hitting it:
   add `shadow` to the prop list, map `white` → `card` and `black` as a decision,
   and add `rg "-(white|black)\b" app components lib` to LP-UI-004's acceptance
   greps beside the three already there.

2. **`--skeleton` had zero consumers after the codemod.** LP-UI-001 introduced
   the token specifically for loading placeholders — its own comment says
   "`--muted` is too close to the card surface in dark" — and the codemod mapped
   `skeleton.tsx`'s `bg-gray-200/70` onto `bg-border/70`, routing the one
   component the token exists for away from it. Changed to `bg-skeleton/70`.
   The two colours are within 0.2% lightness of each other so nothing moves
   visually; the point is that the token now has the consumer it was created for.
   The `/70` is kept deliberately to preserve the current appearance — whether a
   purpose-built token should be used at full strength belongs to LP-UI-006,
   which owns `ui/`.

3. **Two `gray` mentions survive in `globals.css` comments.** They explain the
   `gray-600/700 → foreground-2` mapping and are useful documentation. Left.

## Assumptions and decisions

- **Decided** to split into two commits. The ticket asks for "one mechanical
  commit, reviewed as one diff", and the codemod output is exactly that. The 43
  white/black surfaces are judgement, not mechanism, and mixing them in would
  destroy the property the instruction is protecting.
- **Decided** `bg-card` rather than `bg-background` for the 38. Each is a panel
  sitting *on* the page rather than being the page; `--card` is pure white in
  light (unchanged appearance) and a distinct step above `--background` in dark,
  which is what makes the hairline-and-surface-step language of SPEC rule 1 work.
- **Decided** `bg-popover` for the sheet and the version dropdown. Both float, and
  SPEC rule 1 reserves shadow for exactly that class of thing.
- **Assumed** the two `text-white` sites want `primary-foreground`. Both are on
  `bg-primary`; `primary-foreground` is white in light and near-black in dark,
  which is correct for a filled petrol button in each theme.

## Files

- 70 files, codemod (commit 1) + 4 manual fixes + 1 test assertion
- 28 files, white/black surfaces (commit 2) + `skeleton.tsx`
