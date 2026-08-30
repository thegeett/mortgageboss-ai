# LP-UI-008 — App shell: full-bleed, icon rail, ⌘B

- **Ticket:** LP-UI-008 — the four-region shell
- **Epic:** Ledger redesign → Epic B (Primitives and shell)
- **Status:** Completed
- **Date:** 2026-08-29
- **Mockup:** every screen — the left two columns

## Summary

`max-w-6xl` capped the densest screen in the product at 1152px; on a 1600px
display that discarded a quarter of the width a processor was looking at. The
shell is now full-bleed with four regions, of which this ticket builds three
(the file context rail is LP-UI-009):

```
 52px      216px            flex-1
 icon rail context column   work surface
```

Measured in the browser: rail **52px**, column **216px**, header **44px**,
work surface **1332px** expanded / **1547px** collapsed at a 1600px viewport.

## What Changed

- **`components/layout/icon-rail.tsx`** (new) — 52px, top-level destinations
  only. Every item is an icon with no visible label, so each carries both an
  `aria-label` and a tooltip: the name for assistive tech, the tooltip for the
  sighted user who has not yet learned the glyphs.
- **`components/layout/context-column.tsx`** (new) — 216px, route-dependent:
  pipeline destinations on the dashboard, this file's sections inside a file,
  the admin sections in admin.
- **`lib/navigation.ts`** — `contextSection(pathname)`, `fileSections(fileId)`,
  `loanFileIdFromPath`.
- **`hooks/use-nav-collapse.ts`** (new) — ⌘B / Ctrl+B, the cookie, and the
  `data-nav` attribute.
- **`components/layout/app-shell.tsx`** — rewritten; `max-w-6xl` gone.
- **`components/layout/header.tsx`** — 64px → `--topbar-h` (44px).
- **`components/layout/sidebar.tsx`** — deleted; the rail and column replace it.

## How the collapse avoids a flash

The ticket asks for the state in a **cookie** so it is correct on the server
render, and that constraint drives the whole design. `ProtectedLayout` is a
client component, so the read happens one level up in `app/layout.tsx`, which is
a server component: it reads `ledger-nav` and stamps `data-nav="collapsed"` on
`<html>`.

The width is then one CSS rule — `[data-nav="collapsed"] { --nav-w: 0rem }` —
reusing the `--nav-w` token LP-UI-001 already shipped. The column just occupies
`w-nav` and never reads the state at all.

That matters: holding this in React state and applying it in an effect would
re-expand the column on every navigation and flash it open on every refresh,
which the ticket calls out as infuriating in an all-day tool. It is right.

## Verification

Driven in a real browser over CDP, with synthetic ⌘B keypresses:

| step | rail | column | main | `data-nav` | cookie |
|---|---|---|---|---|---|
| expanded | 52 | 216 | 1332 | — | — |
| after ⌘B | 52 | **0** | 1547 | `collapsed` | `ledger-nav=collapsed` |
| after navigating to a file | 52 | 0 | 1547 | `collapsed` | `collapsed` |
| after a hard reload | 52 | 0 | 1547 | `collapsed` | `collapsed` |
| ⌘B again | 52 | 216 | 1332 | — | `expanded` |

**No flash, checked rather than assumed.** On the hard reload the document was
sampled at 900ms — early, before hydration could have corrected anything — and
already read `data-nav="collapsed"` with `--nav-w: 0rem`. The server rendered it
collapsed.

**The column's contents follow the route.** `aria-label` on the column's `nav`
went `Pipeline` → `File` on navigating into a loan file, without a remount.

**Below `md`.** At a 700px viewport: rail hidden, context column hidden, the
existing mobile menu present and visible.

**Every nav href resolves to a real route** — checked against the filesystem,
all 15 (see Findings for the one that did not).

**CI.** biome, tsc, 520 tests, build — green.

## Findings raised

1. **Needs has no route, so it is not in the column.** "Needs becomes its own
   route" is one of the four standing decisions, and I added the item before
   checking — `/loan-files/[id]/needs` does not exist, so it would have shipped
   a link to a 404. Removed, with a comment saying why, and the filesystem check
   above now covers every href. It goes back in with the route.

2. **The file sections are now duplicated.** The context column lists Overview /
   Documents / Verification / Communication / Conditions / Lender package, and
   the file page still renders the same six as a tab strip directly beneath the
   file header. Both work; having both is the kind of thing that reads as an
   unfinished migration. The tab strip belongs to LP-UI-013, which is where the
   choice should be made — the mockup's file screens navigate from the rail.

3. **A collapsed column still painted a 1px hairline.** `--nav-w: 0` zeroes the
   width but not the `border-r`, so the measurement came back `1`, not `0`. It
   is the kind of thing that looks like a rendering artifact rather than a bug.
   Fixed with a matching rule; re-measured at exactly 0.

## Assumptions and decisions

- **Decided** the collapse lives on `<html>` rather than in a context provider.
  A provider cannot be read by the server, and the whole point of the cookie is
  that the first byte is already right.
- **Decided** ⌘B ignores Alt and Shift modifiers, so a chord the user meant for
  the browser or the OS is not swallowed.
- **Decided** `main` keeps a small `px-4 py-4`. Full-bleed means no *max-width*,
  not content flush to the chrome; a screen ticket that wants a table edge to
  edge can still opt out.
- **Assumed** the pipeline context section (Dashboard / All loan files) is a
  placeholder. The ticket says "saved views on the pipeline", and saved views do
  not exist yet — that is LP-UI-012's.

## Files

- new: `icon-rail.tsx`, `context-column.tsx`, `hooks/use-nav-collapse.ts`
- changed: `app-shell.tsx`, `header.tsx`, `app/layout.tsx`, `app/globals.css`
  (+ the matching `assets/globals.css`), `lib/navigation.ts`
- deleted: `components/layout/sidebar.tsx`
