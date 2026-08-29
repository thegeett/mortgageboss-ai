# LP-UI-002 — Make the config's promises true

- **Ticket:** LP-UI-002 — define the missing `danger` colour; make the weight cap real
- **Epic:** Ledger redesign → Epic A (Foundation)
- **Status:** Completed
- **Date:** 2026-08-29
- **Scope note:** widened by [`AMENDMENTS.md`](../design/ledger/AMENDMENTS.md) (2026-08-29)
  from "define `danger`" to "make the config's promises true", after LP-UI-001
  finding A1. Where `TICKETS.md` and `AMENDMENTS.md` disagree, the amendment wins.

## Summary

Two claims the config was making but not keeping. `danger` was named at twenty
call sites and defined nowhere, so `border-danger/40 bg-danger/5 text-danger`
compiled to nothing and `FailedRunBanner` reported a dead verification run in
grey. And the weight cap, once A1 moved `fontWeight` to `theme` level, started
being real — which silently un-emphasised the 12 headings still asking for
`font-bold`.

The `danger` alias shipped inside the LP-UI-001 asset, so this ticket's job on
that half was to **verify it in a browser**, not to write it. The 12 headings were
rewritten, and both promises are now pinned by tests that fail if either regresses.

## What Changed

- **12 `font-bold` → `font-semibold`**, across 11 files. All are page or section
  headings; `extraction-bench/page.tsx` carries two. Mechanical, no other edit.
  `rg "font-bold" app components lib` now returns nothing.
- **`frontend/tailwind.config.test.ts`** (new, 13 tests) — the token layer's own
  regression suite: `danger` exists and equals `destructive`, the weight scale is
  exactly 400/500/600 with no `bold`, the tokens the redesign adds all resolve,
  and `border` and `input` remain two different colours.
- **`verification-panel.test.tsx`** — one test pinning the banner's markup, inside
  the existing "a run that didn't complete" block.

## Verification

### The banner, with a real failed run

A `failed` verification row was inserted against LF-96SV so it became the file's
latest run, the banner was driven in a real browser over CDP, and its **computed**
colours were read rather than eyeballed. The row was deleted afterwards and
LF-96SV's latest run is `completed` again.

| | light | dark |
|---|---|---|
| border | `rgba(178, 58, 42, 0.4)` | `rgba(236, 131, 117, 0.4)` |
| background | `rgba(178, 58, 42, 0.05)` | `rgba(236, 131, 117, 0.05)` |
| ✕ glyph | `rgb(178, 58, 42)` | `rgb(236, 131, 117)` |

`#B23A2A` and `#EC8375` are the light and dark `--destructive`. Before this, all
three resolved to nothing. The banner reads *"Verification didn't complete — AI
cross-source pass failed"* with a red rule, a red glyph and a tinted ground.

Computed colour is the right evidence here: a class-name assertion would have
passed throughout the entire life of the bug, because the class name was never
what was wrong.

### The other three `danger` call sites

- `calculator-card.tsx` `over` — the "Over limit" badge and the 50.45% back-end
  DTI both render `rgb(178, 58, 42)` light / `rgb(236, 131, 117)` dark.
- `admin/lenders/[id]` required-field asterisk — `rgb(178, 58, 42)`. Reached by
  logging in as `admin@summit-demo.com`; the route renders nothing for a
  processor, so a processor session shows no asterisk to check.
- Every element carrying a `text-danger` class on those pages resolves to the
  destructive colour and to nothing else.

### The headings did not silently lose weight

Each rewritten heading was measured in the browser, not read in the diff:

| screen | heading | computed |
|---|---|---|
| file header | Bharat Kapadiya | 600 / 26px |
| dashboard | Welcome back, Priya. | 600 / 26px |
| dashboard stat tiles | (4 tiles) | 600 / 30px |
| loan files | Loan files | 600 / 26px |
| admin | Administration | 600 / 26px |

### The tests fail when the bug is put back

A test that has never failed proves nothing, so both were checked against a
deliberately broken config: removing the `danger` alias and moving `fontWeight`
back under `theme.extend` turns **5 of the 13** assertions red. The config was
restored and re-verified against `HEAD`.

### CI

`pnpm biome check --write .` (no fixes), `pnpm tsc --noEmit`, `pnpm test`
(48 files, 400 tests — up from 47/386), `pnpm build` — all green.

## Finding raised: the entire dark theme is being purged from the build

**Dark mode currently ships as nothing at all, and LP-UI-001's dark checkbox
passed only because the way I verified it hid this.**

Tailwind v3 tree-shakes custom CSS written inside `@layer base` against the
`content` globs, and that includes the `.dark` block. Nothing in `app/`,
`components/` or `lib/` contains the literal string `dark` today — there are zero
`dark:` variants and no theme toggle yet — so the block is dropped. Read out of
the running dev server's CSSOM, the stylesheet contains `:root` and no `.dark`
rule at all, and setting `document.documentElement.classList.add("dark")` at
runtime changes nothing: `--destructive` stays at the light `7.1 61.8% 43.1%`.

The controlled A/B, same app, one difference:

| `app/layout.tsx` | `.dark` rule in the stylesheet | live `--destructive` | body background |
|---|---|---|---|
| `<html lang="en">` | **absent** | `7.1 61.8% 43.1%` (light) | `rgb(251, 252, 252)` |
| `<html lang="en" className="dark">` | **present** | `7.1 75.8% 69.2%` (dark) | `rgb(12, 16, 17)` |

Adding the class in `layout.tsx` — which is how LP-UI-001 checked dark, and how
the dark measurements above were taken — also puts the string `dark` into a
scanned file, which is what keeps the block alive. The verification method was
supplying the very condition it was meant to be testing.

It will look fixed the moment a theme toggle exists, since the toggle's own source
contains the word. But it will break again, silently, if that toggle ever sets the
class from a variable (`classList.add(theme)`) rather than a literal — which is the
natural way to write a three-way light/dark/system control.

**Proposed fix, not applied:** `safelist: ["dark"]` in `tailwind.config.ts`, which
makes the block's survival independent of what any component happens to spell. It
is one line in the asset, so it is raised here rather than changed unilaterally.
LP-UI-011 (the theme toggle) is where it would otherwise bite.

## Assumptions and decisions

- **Decided** to test the token layer at the config level as well as the DOM.
  Both LP-UI bugs lived in what the config did with a correct class string, which
  is invisible to JSDOM — a component test would have stayed green through both.
- **Decided** to leave the twenty call sites spelled `danger` rather than
  normalising them to `destructive`. `TICKETS.md` marks that optional, the alias
  makes them correct, and a rename would put mechanical churn in the same commit
  as a behaviour fix.
- **Assumed** `font-semibold` is the right landing weight for all 12 headings —
  it is the system's maximum, and the amendment specifies it. Their *sizes* are
  left alone for the screen tickets.
- **Noted** the local dev database was many migrations behind this branch
  (`c9d3f1a6b2e4` → `c4a71fe28b93`, ~20 revisions) and the API could not serve a
  loan file until `alembic upgrade head` ran. Dev-only, and re-seedable.

## Files

- 11 files, `font-bold` → `font-semibold` (12 occurrences)
- `frontend/tailwind.config.test.ts` (new)
- `frontend/components/file/verification/verification-panel.test.tsx`
