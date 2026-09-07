# LP-UI-001 — Land the Ledger design tokens

- **Ticket:** LP-UI-001 — Land the Ledger design tokens
- **Epic:** Ledger redesign → Epic A (Foundation)
- **Status:** Completed
- **Date:** 2026-08-29
- **Spec:** [`docs/design/ledger/SPEC.md`](../design/ledger/SPEC.md) · **Mockup screen:** Foundations
- **Blocks:** everything in `LP-UI-*`

## Summary

`frontend/app/globals.css` and `frontend/tailwind.config.ts` were replaced with the
drop-in versions from `docs/design/ledger/assets/`. Both files were copied, not
retyped; the only edits afterwards were Biome's reformatting (line wrapping and
comment spacing — verified as whitespace-only against the assets with `diff`).

The token layer now carries the whole colour, weight, radius, density and layout
vocabulary. Nothing else changed: no component was touched, and the 808 hardcoded
`gray-*` classes are still in place and still fighting the tokens. That is the
planned intermediate state and LP-UI-004 resolves it.

## What Changed

- **`frontend/app/globals.css`** — 46 → 160 lines.
  - Petrol `--primary` (`#12545E` light / `#4FB3C0` dark) replaces the Tailwind
    blue `217 91% 60%`.
  - A full `.dark` block, the first one in this codebase.
  - New tokens: `--foreground-2` (the middle text tone), `--border-strong`,
    `--skeleton`, `--ai` (provenance, not status).
  - `--input` becomes the ≥3:1 control border; `--border` stays the hairline.
  - `--info` is aliased to the petrol accent — "in flight" *is* the accent state,
    so the system has five hues, not six.
  - Geometry: `--radius` 0.5rem → 0.3125rem, `--radius-container` 0.5rem.
  - Density variables `--row-h` / `--row-px` plus the `[data-density]` overrides
    that LP-UI-010 will switch.
  - Layout variables `--rail-w` / `--nav-w` / `--ctx-w` / `--topbar-h`.
  - Base rules: `.tabular, table { font-variant-numeric: tabular-nums }`,
    a `:focus-visible` ring (never `:focus`), `scroll-margin-block` on `[data-row]`,
    and a `prefers-reduced-motion` block.
- **`frontend/tailwind.config.ts`** — the `token()` / `pair()` helpers, the
  `fontSize` scale with 13px as `sm`, a `fontWeight` map, `danger` as an alias of
  `destructive` (LP-UI-002's fix arrives inside this asset), `foreground-2`,
  `border-strong`, `skeleton`, `ai`, the row/cell/rail spacing scales, and IBM Plex
  variables that LP-UI-003 will define.

## Verification

**Utilities resolve.** Compiled a probe file through the Tailwind CLI against the
new config and read the emitted CSS. `bg-warning/10` → `hsl(var(--warning) / 0.1)`
and `border-primary/30` → `hsl(var(--primary) / 0.3)`, so the space-separated HSL
form survived and the ~200 existing opacity modifiers keep working.
`text-danger` / `bg-danger/5` / `border-danger/40` now resolve to `--destructive`.
`h-row`, `px-cell`, `w-rail`, `w-nav`, `w-ctx`, `text-label`, `bg-skeleton`,
`text-foreground-2`, `text-ai` and `border-border-strong` all emit.

**Contrast, computed rather than assumed.** Every token pair was run through a
WCAG relative-luminance check in both themes. All text tones clear 4.5:1 on
`background` and `card`; every on-fill foreground clears 4.5:1 on its own fill;
`--input` clears 3:1 on both grounds (3.20:1 light, 3.47:1 dark). One pair does
not clear — see Findings.

**Light and dark, in a browser.** `next dev` on :3117, `/login` screenshotted at
1440×900 in light, then with `class="dark"` temporarily on `<html>` (reverted
immediately). Dark mode flips the card, the primary button, the input borders and
the body text correctly. The page background stays light and the card title goes
nearly invisible, because both are hardcoded `gray-*` — the predicted LP-UI-004
state, not a token defect.

**CI.** `pnpm biome check --write .` (2 files reformatted), `pnpm tsc --noEmit`,
`pnpm test` (47 files, 386 tests), `pnpm build` — all green.

## Findings raised

Three things surfaced during verification. None was changed unilaterally: the
assets are drop-in by instruction, and SPEC rule 8 says to raise a problem on the
ticket rather than edit the palette under it.

**All three were reviewed, confirmed and dispositioned the same day** — see
[`docs/design/ledger/AMENDMENTS.md`](../design/ledger/AMENDMENTS.md). Two were
defects in the assets and the assets were corrected; the third became acceptance
criteria on LP-UI-004. The corrections are folded into this ticket.

1. **`font-bold` still resolves to 700.** `fontWeight` sits under `theme.extend`,
   and Tailwind *merges* `extend` with the default theme rather than replacing it,
   so `bold: 700` survives. The compiled CSS confirms `.font-bold { font-weight:
   700 }`. The ticket's premise — "`fontWeight` is capped at 600 so `font-bold` no
   longer resolves" — is therefore not true of the asset as written, and the 12
   existing `font-bold` call sites still render at 700 in violation of SPEC rule 2.
   Moving the `fontWeight` block from `theme.extend` to `theme` (one level up)
   makes the cap real and turns those 12 sites into a build-visible break.

   **Resolved (A1).** `fontWeight` now sits at `theme` level in both the asset and
   `frontend/tailwind.config.ts`. Re-verified through the Tailwind CLI:
   `font-bold` emits nothing at all, while `font-normal` / `font-medium` /
   `font-semibold` emit 400 / 500 / 600. The consequence is that the 12 call sites
   now resolve to nothing and silently inherit their weight, which is worse than
   700 — so replacing them with `font-semibold` moved into LP-UI-002's scope
   rather than being left for a later screen ticket.
2. **`muted-foreground` on `muted` is 4.29:1 in light** — the one pair under the
   4.5:1 floor the SPEC declares verified. It does not bite yet (2 `bg-muted`
   usages, and no element pairs them today), but the LP-UI-004 codemod maps
   `bg-gray-50/100` → `muted` and `text-gray-300/400/500` → `muted-foreground`,
   and **24 elements currently carry both** — every one of them lands on 4.29:1.
   Dark is fine at 5.38:1. Dropping light `--muted-foreground` from `44.3%` to
   `43.0%` lightness clears it at 4.50:1. `41.5%` (`#656E6D`) also clears the
   `accent` hover surface, which is 4.05:1 today and 4.26:1 at 43.0%.

   **Resolved (A2).** Light `--muted-foreground` is now `168.0 4.4% 41.0%`
   (`#646D6B`) in both the asset and `frontend/app/globals.css` — 41.0% rather
   than the 41.5% proposed here, because 41.5% reaches only 4.53:1 on `accent`
   and hex rounding could push that under. Re-measured at 41.0%: 5.17:1 on
   `background`, 5.32:1 on `card`, 4.86:1 on `muted`, 4.60:1 on `accent`. Dark is
   unchanged.
3. **Two hardcoded colour literals the codemod cannot see.**
   `app/page.tsx:143` and `app/(auth)/login/page.tsx:18` both carry
   `bg-[radial-gradient(circle_at_top,_hsl(217_91%_60%_/_0.08),_transparent_55%)]`
   — the old Tailwind blue, written as an arbitrary value. The LP-UI-004 codemod
   only matches `{prop}-gray-{shade}`, so `rg "gray-[0-9]"` will come back clean
   while these two survive. They belong to LP-UI-012 (login) and the landing page.
   Otherwise the palette is clean: zero hex literals and zero non-`gray` Tailwind
   palette colours anywhere in `app/`, `components/` or `lib/`.

   **Resolved (A3).** Kept as a finding rather than patched here. LP-UI-004 gains
   two acceptance criteria — `rg "217 91%|217_91%"` and a hex-literal grep must
   both come back empty — and the two gradients become `hsl(var(--primary) / 0.08)`
   in that ticket. LP-UI-011 separately picks up the question of whether
   `app/page.tsx` should survive at all.

## Assumptions and decisions

- **Assumed** the Biome reformatting of the two assets is acceptable, since
  `pnpm biome check` is a CI gate and the alternative is a permanently failing
  lint. Confirmed whitespace-only.
- **Assumed** the ticket's "no hardcoded hex anywhere in either file's consumers"
  means literal hex; there is none. The two `hsl()` arbitrary values above are the
  same class of problem and are recorded as finding 3.
- **Decided** to verify `.dark` by temporarily setting the class by hand rather
  than building a theme switcher. Nothing in the app sets `.dark` yet and no
  component uses a `dark:` variant (0 occurrences) — dark mode here is purely a
  token swap, which is why LP-UI-004 is the ticket that makes it usable.
- **Decided** to leave the four standing decisions (petrol accent, dark mode
  shipping now, staying on Radix, Needs as its own route) as the assets encode
  them. Nothing found during this ticket argues against any of them.

## Files

- `frontend/app/globals.css` (replaced, then A2 applied)
- `frontend/tailwind.config.ts` (replaced, then A1 applied)
- `docs/design/ledger/AMENDMENTS.md` (new — the review's dispositions)
- `decisions.md` — ADR-389
