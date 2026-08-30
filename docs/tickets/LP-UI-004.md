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

## Review pass — the many-to-one mappings the codemod could not see

A `/code-review` over `HEAD~10...HEAD` found thirteen defects, twelve of them one
failure mode: **the `gray-*` → token mapping is many-to-one**. Wherever two
distinct grays carried meaning — a base tone and its hover, state A and state B,
text-on-inverted and text-on-surface — the codemod collapsed them onto a single
token and the distinction silently disappeared. Nothing failed; the classes still
resolved, they just resolved to the same thing.

### Contrast: text on an inverted surface

`TooltipContent` is `bg-foreground` (near-black in light), so its body copy needs
the tooltip's own text colour, not the page's. Two `text-gray-300` sites took the
generic `text-muted-foreground` mapping and landed at **3.44:1 light / 2.63:1
dark** — below AA, from ~12:1 before. Both are now `text-background/75`
(**10.27:1 / 7.97:1**).

- `file/ltv/ltv-calculator.tsx:247` — the appraised-value help tooltip
- `file/dti/dti-calculator.tsx:502` — the tax-suggestion override caveat

Worth recording *why* the contrast sweep above missed them: it walked every leaf
element with visible text on four screens, and tooltip content is portalled in
only on hover, so it was never in the DOM to be measured. A sweep of static
screens cannot see a hover-mounted portal.

### A scrim is not a surface — second instance

`SheetOverlay` was `bg-gray-900/40` → `bg-foreground/40`. `--foreground` is 92.4%
lightness in dark, so the modal scrim became a 40% *white* wash that brightened
the page it was meant to dim. `dialog.tsx` was already corrected to `bg-black/80`
for exactly this reason; the sheet is the same kind of element and did not get the
same treatment. Now `bg-black/40`.

### Hover states that collapsed onto their own base

Four sites where `X` and `hover:X-darker` both mapped to one token, leaving
`text-muted-foreground group-hover:text-muted-foreground` — a hover that does
nothing. In three of them the pencil is the *only* affordance signalling that a
line amount is click-to-edit.

- `file/ltv/ltv-calculator.tsx:410`, `file/dti/dti-calculator.tsx:411`,
  `file/calculators/calculator-card.tsx:293` — `group-hover:text-foreground`
- `file/documents/document-dropzone.tsx:88` — `hover:border-foreground-2`

`border-strong` would have been the wrong fix for the dropzone: it is *lighter*
than `input` (81.6% vs 54.5%), so hover would have weakened the border rather than
strengthened it. `foreground-2` is darker than `input` in light and lighter in
dark, so it reads as a strengthening in both.

### `bg-border` used as a status indicator

`--border` is the hairline at 89.8% lightness: **1.25:1** on a card, effectively
invisible. Findings section A6 scopes it to rules, dividers and troughs; a status
dot is none of those. Five `bg-gray-300` dots took it.

- `file/verification/rule-finding-row.tsx:53` — the `muted` severity dot
- `file/verification/rule-findings-tabs.tsx:329` — the collapsed-group tone dot
- `file/calculators/calculators-section.tsx:36` — the *default* calculator dot,
  i.e. every unrecognised status
- `lib/loan-files/needs.ts:73` — the "Waived" dot

All four → `bg-muted-foreground` (**5.32:1 light / 5.83:1 dark**).

The fifth, `rule-findings-tabs.tsx:431`, is a 4px decorative list bullet rather
than an indicator, so it took `bg-border-strong` — 1.52:1, the weight
`gray-300` actually had.

### Two states that became byte-identical

`closed` and `withdrawn` in `lib/loan-files/status.ts` were `gray-100/gray-500`
and `gray-50/gray-400`; both collapsed to `bg-muted text-muted-foreground
border-border`, so two different terminal states rendered as the same badge and
the only differentiator left was reading the label. `withdrawn` is now
`bg-transparent … border-border-strong` — **outline vs filled**, chosen over a
lightness step because a lightness step does not survive the theme flip.

### A ternary with one branch

`file/verification/finding-card.tsx:264` read
`deterministic ? "bg-primary/10 text-primary" : "bg-info/10 text-info"`. `--info`
is aliased to `--primary` in both themes, so both branches rendered the same
colour — and matched the neighbouring "docs requested" chip, which means something
unrelated. The AI branch now uses `bg-ai/10 text-ai` (**5.80:1 / 6.31:1**), the
token LP-UI-001 introduced for provenance and which until now had zero consumers.

### Not a codemod defect: the serif face

`lib/fonts.ts` loaded `IBM_Plex_Serif` with `style: ["italic"]` only, so the
generated `@font-face` matched italic text alone and upright `font-serif` had no
face to bind to — it fell back to Georgia, silently, and invisibly on any machine
with a passable serif. Nothing uses `font-serif` yet, but LP-UI-029's
verbatim-snippet state is about to. Now `style: ["normal", "italic"]`; the build
emits both faces.

### The test assertion that could not fail

`tailwind.config.test.ts:83` asserted `colour("border") !== colour("input")`.
Those return the literal strings `"hsl(var(--border))"` and `"hsl(var(--input))"`,
which differ *by construction* whatever the variables hold — setting `--input`
equal to `--border`, the exact regression the comment describes, left the test
green. The `it.each` "`%s` resolves" block had the same shape: it proved a key
exists in the resolved theme, not that the variable behind it is defined, so
deleting `--ai` from `globals.css` would have reproduced LP-UI-002's
"compiles to nothing" failure with the suite passing.

The suite now parses `app/globals.css` and asserts against the declarations
themselves: every `var(--x)` the resolved theme's colours reference is defined in
**both** `:root` and `.dark`, and `--border` ≠ `--input` **by value**, per theme.
Both were mutation-checked — collapsing `--input` onto `--border` and deleting
`--ai` each fail exactly one test, where previously neither failed any.

### Verification

- `tsc --noEmit` clean; `biome check` clean over 203 files; **460 tests pass**
  (48 files); `pnpm build` succeeds.
- Contrast ratios above computed per token pair in both themes, including the
  alpha compositing for `text-background/75` and `bg-ai/10`.
- Built the CSS with the Tailwind CLI and confirmed every new class emits a real
  rule — `text-background/75` → `color: hsl(var(--background) / 0.75)`.
- Build output inspected for `@font-face`: both `IBM Plex Serif` styles present.

### For the next codemod

The mechanical check that would have caught eight of these is a grep for a
variant and its base resolving to the same utility:

```
rg '(\w[\w-]*):([\w-]+)\b(?=[^"]*\b\2\b)' --pcre2 app components lib
```

The remaining four need a human: a colour-on-inverted-surface pass, and a check
that every `Record<K, string>` of class strings still has distinct values for
distinct keys.
