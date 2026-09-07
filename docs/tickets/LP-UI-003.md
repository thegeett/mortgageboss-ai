# LP-UI-003 — IBM Plex via next/font

- **Ticket:** LP-UI-003 — replace the bare system stack with IBM Plex
- **Epic:** Ledger redesign → Epic A (Foundation)
- **Status:** Completed
- **Date:** 2026-08-29

## Summary

`assets/fonts.ts` dropped in as `frontend/lib/fonts.ts` unchanged, and the three
variables wired onto `<html>` in `app/layout.tsx`. Plex Sans carries the UI, Plex
Mono carries money, ratios, loan ids and citations, and Plex Serif italic is
loaded for its single future use — text quoted verbatim from a document.

This also ends a regression LP-UI-001 introduced and this ticket was always going
to close. `tailwind.config.ts` has pointed `font-sans` at `var(--font-plex-sans)`
since LP-UI-001, and an undefined custom property makes the whole `font-family`
declaration invalid at computed-value time — so the property fell back to the
browser default and **every screen has been rendering in Times since LP-UI-001**.
It is visible in that ticket's screenshots. Both are now defined, and the app
renders in Plex.

## What Changed

- **`frontend/lib/fonts.ts`** (new) — copied from `assets/fonts.ts`, unmodified.
- **`frontend/app/layout.tsx`** — imports the three faces and puts
  `plexSans.variable plexMono.variable plexSerif.variable` on `<html>`.

## Verification

**Three variables on `<html>`, and they resolve.** Read out of the running app:

```
htmlClass  __variable_1bc20f __variable_46fe82 __variable_3c0edb
--font-plex-sans   'IBM Plex Sans', 'IBM Plex Sans Fallback'
--font-plex-mono   'IBM Plex Mono', 'IBM Plex Mono Fallback'
--font-plex-serif  'IBM Plex Serif', 'IBM Plex Serif Fallback'
```

`font-sans` computes to `"IBM Plex Sans", "IBM Plex Sans Fallback", ui-sans-serif,
system-ui, sans-serif` and `font-mono` to the Plex Mono equivalent.

**`font-serif` needs a note.** Probing it returned the *sans* stack, which looks
like a failure and is not: nothing in `app/`, `components/` or `lib/` uses
`font-serif` yet — per the SPEC it has exactly one future use — so Tailwind does
not generate the `.font-serif` utility and the probe element simply inherited the
body font. Rendering the config's serif stack directly confirms the wiring is
sound: it computes to `"IBM Plex Serif", "IBM Plex Serif Fallback", Georgia,
serif`, `document.fonts.check("italic 400 20px 'IBM Plex Serif'")` is true, and
the same string measures 131.56px against the sans stack's 138.46px — a different
face is genuinely rendering, not a silent fallback.

This is ordinary on-demand utility generation and needs no safelist. It is
**not** the LP-UI-002 A4 situation: `.dark` was custom CSS inside `@layer base`
that no markup would ever name as a class, whereas `.font-serif` appears the
moment a component asks for it.

**Weights are capped, checked in the built artifact** rather than in the source.
`@font-face` rules emitted by `pnpm build`:

| family | weights | style |
|---|---|---|
| IBM Plex Sans | 400, 500, 600 | normal |
| IBM Plex Mono | 400, 500 | normal |
| IBM Plex Serif | 400 | italic |

No 700 face is downloaded or declared, which is the same cap LP-UI-002 made real
in the Tailwind config, now true of the font payload too.

**Self-hosted.** 21 `.woff2` files under `.next/static/media/`, served from
`/_next/static/media/…`. No runtime request to Google.

**Layout shift.** Measured with a `layout-shift` PerformanceObserver installed
before navigation, on a cold load of `/login`: **CLS 0.0069** — an order of
magnitude under the 0.1 "good" threshold, and not attributable to the fonts:
`next/font` emits metric-matched fallbacks that stop the swap from moving
anything.

```
IBM Plex Sans Fallback   src: local("Arial")            size-adjust: 101.17%
IBM Plex Mono Fallback   src: local("Arial")            size-adjust: 134.59%
IBM Plex Serif Fallback  src: local("Times New Roman")  size-adjust: 116.43%
```

**CI.** `pnpm biome check --write .` (no fixes), `pnpm tsc --noEmit`, `pnpm test`
(48 files, 400 tests), `pnpm build` — all green.

## Finding raised, not fixed: the build now needs network egress to Google Fonts

"No runtime network request" is true, and worth separating from what actually
changed. `next/font/google` fetches the font files **at build time** and vendors
them into the bundle. `Dockerfile:67` runs `pnpm build` inside the image build, so
the frontend image now needs egress to `fonts.googleapis.com` and
`fonts.gstatic.com` where it previously needed none — and a font fetch failure
fails the build rather than degrading to a fallback.

That is fine if the build environment has general internet access, which this one
does. It is worth deciding deliberately rather than discovering in a locked-down
or air-gapped pipeline. If it ever needs removing, the fix is `next/font/local`
with the eleven `.woff2` files committed under `public/` or `lib/fonts/` — same
API, same metric-matched fallbacks, no build-time fetch, at the cost of carrying
the binaries in the repo.

Not changed here: it is a deployment decision, and the current pipeline works.

## Assumptions and decisions

- **Assumed** the asset's subset choice is deliberate. `subsets: ["latin"]`
  controls *preloading*, not what is downloaded — Next still vendors the Cyrillic,
  Greek and Vietnamese `unicode-range` slices, which is why 21 files land for
  three families. They are only fetched by a browser that needs those glyphs.
- **Decided** not to safelist `font-serif`. See above — a utility that no
  component uses should not be generated, and it will appear when LP-UI-0xx gives
  the serif its one job.
- **Noted** `document.fonts.check("700 …")` returns true. That is CSS font
  matching resolving 700 to the nearest available face, not a 700 file existing.
  The `@font-face` table above is the real evidence.

## Files

- `frontend/lib/fonts.ts` (new, copied from the asset)
- `frontend/app/layout.tsx`
