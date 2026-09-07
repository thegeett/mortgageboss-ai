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

## Review pass — the collapse hides the column from eyes, not from keyboards

Reviewed on request from the session running the epic. Five defects, plus a
confirmation of the three findings this ticket raised and deliberately left.

### The collapsed column stayed focusable and announced

`--nav-w: 0` plus `overflow-hidden` clips the column out of SIGHT. It does not
remove it: the six links stayed in the tab order and in the accessibility tree.
⌘B therefore "hid" a nav that a keyboard user still tabbed through — six
invisible stops between the rail and the page, with focus apparently vanishing —
and that a screen reader still read out in full.

This is the sharp edge of the CSS-only design, and the fix keeps that design
rather than retreating from it: `visibility: hidden` alongside the existing
`border-right-width: 0`. Visibility is what actually removes an element from the
tab order and the a11y tree, and unlike `display: none` it leaves the width
transition intact. Still no client effect in the path, so the no-flash property
this ticket was built around is untouched.

`assets/globals.css` re-synced; `ledger-assets.test.ts` fails if it is not.

### Two links claimed to be the current page

`ContextColumn` computed `active` per item with `isActivePath`, which is a prefix
match. "Overview" is `/loan-files/<id>` and "Documents" is
`/loan-files/<id>/documents`, so on the documents page **both** matched and both
carried `aria-current="page"`. A screen reader announces two current pages, and
two rows read as selected. Administration has the same index-plus-children shape
(`/admin` beside `/admin/lenders`) and the same bug.

The expression was also self-cancelling —
`item.href === pathname || (item.href !== pathname && isActivePath(...))` reduces
to `isActivePath(...)`, so the first two clauses did nothing.

`activeItemHref(pathname, hrefs)` now picks the LONGEST match, because "current"
is a property of the whole set rather than of any item alone. It is tested
against both declaration orders: any first-match or last-match implementation
gives a different answer for one of them, and only longest-match agrees with
both.

### The hook had three producers of one fact

Correctly identified in the hand-off, and worth being precise about what was
wrong. `data-nav` on `<html>` is what the CSS reads, so it is what the user sees.
`toggle` computed the next state from the React value instead and wrote the DOM
from that — so the thing deciding was not the thing driving the pixels, and any
divergence would cost a press that visibly does nothing.

`toggle` now reads the attribute, and `setCollapsed` only mirrors the result
afterwards. That also takes the DOM write and the cookie write out of a
`setState` updater, where they never belonged: React may invoke an updater twice
or discard the render it ran in, and both writes would already have happened.

The React value was unread by anything, which is exactly why it was free to
drift. It now has a consumer: `aria-expanded` on the rail's toggle. A disclosure
button that does not say which way it is pointing is identical in both states to
anyone who cannot see the column. `aria-controls` goes with it, but only where
the column actually renders — `contextSection` returns null on `/dev/*`, and an
`aria-controls` naming an element that is not in the document is worse than none.

### ⌘B stole bold from rich text

The listener suppressed the default for every ⌘B on the window. In a
`contenteditable` that is the browser's bold command, and taking it is wrong in
the one place the user definitely meant something else. Guarded.

Plain inputs and textareas are deliberately NOT guarded: ⌘B has no native meaning
in them, so a processor who presses it while a field has focus meant the sidebar.
Suppressing there would make the shortcut feel broken for the sake of a
layout shift that does not cost the caret.

### The cookie had two spellings for one state

Expanding wrote `ledger-nav=expanded`. The server tests for `"collapsed"`
exactly, so `expanded` and no-cookie are the same state, and a cookie whose only
value means "the default" is a second way to spell its own absence — the two
eventually disagree about which is canonical. Expanding now deletes it
(`max-age=0`). Answering the hand-off's question directly: the `expanded` write
was not needed.

### Checked and found correct

- **Unexpected cookie values.** `=== "collapsed"` is already fail-safe: garbage,
  a stale `expanded`, or an absent cookie all render expanded, which is the
  default. No change needed.
- **`loanFileIdFromPath` and other non-id segments.** `new` is the only one
  today — every other child of `/loan-files` lives under `[id]`. Verified against
  the route tree rather than the ticket, and pinned in a test.
- **Rail/column at the `md` breakpoint.** Below `md` both are `hidden`, and
  `Header` carries its own mobile nav, so the collapse and the breakpoint do not
  interact: collapsing is a no-op on a viewport where the column is not rendered,
  and the cookie simply carries the preference to the next wide viewport.

### The three raised and not fixed — all the right call

- **Needs omitted from the file sections.** Correct. `/loan-files/[id]/needs`
  does not exist, and a link to a 404 is worse than an absent link. It goes in
  with the route.
- **File sections duplicated between the column and the tab strip.** Correct to
  leave. It is a real duplication — two mechanisms now answer "which section am
  I in" for the same set — but resolving it is a design decision about which one
  survives, which is LP-UI-013's to make, not a defect to patch mid-epic.
- **`main` keeps `px-4 py-4` under full-bleed.** Correct. Full-bleed removed a
  *max-width cap*, which is what was throwing away a quarter of a 1600px display;
  padding is the work surface's own breathing room and a table can still opt out
  of it, as the comment says.

### Verification

`tsc --noEmit` clean, `biome check` clean over 212 files, 541 tests pass (from
520), `pnpm build` compiles. Every fix mutation-checked:

| mutation | result |
| --- | --- |
| revert ContextColumn to per-item `isActivePath` | 3 tests fail |
| make `activeItemHref` pick the last match, not the longest | 1 test fails |
| compute `toggle` from React state instead of the DOM | 1 test fails |
| write `expanded` instead of deleting the cookie | 1 test fails |
| drop the contenteditable guard | 1 test fails |
| drop `visibility: hidden` from the collapsed column | 1 test fails (asset drift) |

Two of those mutations passed on the first attempt and the tests were rewritten
until they did not. The `activeItemHref` test only checked one declaration order,
where last-match and longest-match agree; and the hook test set `data-nav` before
mounting, so the adopt effect made React state and the DOM agree and there was no
divergence left to detect. Both now encode the divergence itself.

The stylesheet was compiled and the emitted rules checked:
`[data-nav="collapsed"]` sets `--nav-w: 0rem`, and the column rule carries both
`border-right-width: 0` and `visibility: hidden`.
