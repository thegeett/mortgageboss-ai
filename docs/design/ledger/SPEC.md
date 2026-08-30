# Ledger — frontend design spec

The contract between the design and the implementation. Read this at the start of
every `LP-UI-*` ticket; it is short on purpose.

- **Screens:** `ledger-screens.html` — open it in a browser and use the screen
  switcher. Sixteen screens, both themes, real routes and real seed data.
- **Stills:** `screens/*.png` — one per screen, for pasting into a ticket.
- **Why:** `ledger-direction.html` — the audit and the reasoning.
- **Plan:** `ledger-plan.html` and `TICKETS.md`.
- **Code to drop in:** `assets/`.

---

## The nine rules

These are review criteria, not suggestions. A PR that breaks one should be sent back.

1. **Hairlines, not cards.** One pixel of `border-border` plus a surface step does
   every job a rounded-shadowed card was doing. `shadow-*` is reserved for things
   that genuinely float: dropdown, popover, tooltip, dialog. If a panel does not
   float, it does not get a shadow.
2. **Font weight never exceeds 600.** There is no `font-bold` in this system —
   `fontWeight` in the Tailwind config only defines 400/500/600. Hierarchy comes
   from size, colour and space.
3. **One accent.** `primary` (petrol) appears on primary buttons and active
   navigation, and nowhere else. Not links, not headings, not decorative icons.
4. **Status is three channels: colour, glyph shape, word.** Always all three, via
   `<StatusToken>`. Delete the colour mentally and the row must still read.
5. **State goes on the left rail and the glyph, never on a background fill.**
   `<StatusRail>` or `railClass()`. Fills stack badly under hover/focus and cost
   text contrast.
6. **Violet (`ai`) is provenance, not status.** It marks "a model produced this".
   It never means bad, and it is never one of the four status tones.
7. **Tabular numerals everywhere digits line up.** Money, ratios, rates, dates,
   loan ids. `<table>` gets it automatically; anything else needs `.tabular`.
8. **No new colour outside the token set.** If a screen seems to need one, the
   screen is wrong. Say so on the ticket instead of adding a hex value.
9. **Every error names what failed and offers the next move.** No apologies, no
   "something went wrong". See the States screen in the mockup.

## Density

Default is **compact**: 28px rows, 13px text, 12px horizontal cell padding.
Driven by `--row-h` / `--row-px`, switched by `[data-density]` on `<html>`.
It is a per-person preference, persisted per user — **not** per view, not per
screen. A processor decides once.

## Layout

Full-bleed. `max-w-6xl` is gone. Four regions:

```
 52px      216px            flex-1                288px
┌──────┬──────────────┬────────────────────────┬──────────────┐
│ icon │ context      │ work surface           │ file context │
│ rail │ column       │                        │ rail         │
└──────┴──────────────┴────────────────────────┴──────────────┘
   ⌘B collapses ────┘                            file routes only
```

The file context rail carries loan amount, DTI, LTV, reserves and the blocking
count. Those four numbers are the reason a processor switches tabs today.

## Naming

- Tailwind token classes only: `text-foreground`, `text-foreground-2`,
  `text-muted-foreground`, `border-border`, `border-input`, `bg-muted`.
  **No `gray-*` may re-enter the codebase.** Add a lint rule if it does.
- `border` = decorative hairline. `input` = control border, clears 3:1.
- **`bg-border` is not a text surface.** It is for rules, dividers, dots and
  progress troughs. `text-muted-foreground` on it is 4.27:1 in light — below the
  floor. No element pairs them today and none should; if a filled surface is
  wanted, use `bg-muted` (4.87:1 with the same text).
- Status labels stay domain-specific (`lib/status.ts`); only the colour
  vocabulary is shared. **The words are not ours to re-open.** They were argued
  out in LP-583/LP-581 and they carry domain meaning: `completed` is where the
  processing pipeline ends, `verified` is where a human confirmed something, and
  in a product that tracks stated-versus-verified data those are different facts.
  If an asset proposes different wording, the asset is wrong — say so on the
  ticket (see AMENDMENTS A10). "Must fix" and "Blocked" are the same tone, different
  words, and the words are what processors quote.

## Accessibility floor

- Every text tone clears **4.5:1** against its own ground in both themes.
  Verified, not assumed — do not add a lighter one.
- `input` (control border) clears **3:1** — WCAG 1.4.11.
- `:focus-visible`, never `:focus`. 2px outline at 2px offset.
- Interactive tables use the ARIA **grid** pattern with a roving tabindex.
  A 40-row × 9-column table must not be 360 tab stops.
- Icon-only buttons are at least 24×24 CSS px.
- Status is never colour-only. See rule 4.

## Two rules the LP-UI-005 review earned

- **Every status map stays exhaustive over its own union.** Never
  `Record<string, StatusMeta>`. A fallback resolver plus a widened key type
  removes the compile-time guarantee and the runtime one together, and a stale
  test array then hides it (AMENDMENTS A11).
- **Exhaustive over its PRODUCERS, not over what it replaced.** A map typed
  against the display map it succeeded can still miss values the backend emits
  (AMENDMENTS A13). Trace every caller.
- **Never index a map raw and then use the result.** `map[x].push(...)` throws on
  an unknown key and takes the whole page with it. Fall back explicitly
  (AMENDMENTS A14).
- **Form controls stay at 16px on mobile.** `text-field md:text-sm`, never
  `text-sm` alone — Safari zooms under 16px and does not zoom back (AMENDMENTS A15).
- **A sticky header is a property of the whole ancestor chain, not of the table.**
  `position: sticky` resolves against the nearest scrollport, and *any* `overflow`
  other than `visible` creates one — including `overflow: hidden`. Two independent
  ancestors defeated it here: shadcn's `div.overflow-auto` wrapper, and a
  `<Card className="overflow-hidden">` used to clip to the card radius. Note also
  that `overflow-x: auto` forces `overflow-y` to compute to `auto`, so a
  horizontally-scrolling wrapper is always a vertical scrollport too. Epic C adds
  more tables — check the chain, not the table (LP-UI-007).
- **A test that cannot fail is not a test.** Do not assert through a function
  that synthesises a result for unknown input. Index the map, and assert its keys
  equal the union.

## Definition of done, per ticket

- [ ] Matches the mockup screen named on the ticket
- [ ] Light **and** dark checked
- [ ] `pnpm biome check`, `pnpm tsc --noEmit`, `pnpm test` green
- [ ] No `gray-*` introduced; no `font-bold`; no new hex colours
- [ ] Keyboard reachable; visible focus
- [ ] `docs/tickets/LP-UI-XXX.md` written, per the repo convention in CLAUDE.md
