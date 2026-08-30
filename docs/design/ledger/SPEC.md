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
  vocabulary is shared. "Must fix" and "Blocked" are the same tone, different
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

## Definition of done, per ticket

- [ ] Matches the mockup screen named on the ticket
- [ ] Light **and** dark checked
- [ ] `pnpm biome check`, `pnpm tsc --noEmit`, `pnpm test` green
- [ ] No `gray-*` introduced; no `font-bold`; no new hex colours
- [ ] Keyboard reachable; visible focus
- [ ] `docs/tickets/LP-UI-XXX.md` written, per the repo convention in CLAUDE.md
