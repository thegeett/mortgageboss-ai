# Prompt for Claude Code

Open a session in the repo root and paste everything below the line.

---

We are implementing a frontend redesign called **Ledger**. Everything you need is in
`docs/design/ledger/`. Read before writing any code:

1. `docs/design/ledger/SPEC.md` — nine design rules and the definition of done.
   These are review criteria, not suggestions.
2. `docs/design/ledger/TICKETS.md` — 40 tickets, `LP-UI-001` … `LP-UI-040`.
3. Open `docs/design/ledger/ledger-screens.html` in a browser. It has a screen
   switcher across the top. Every ticket names the screen it must match — when a
   ticket says "Mockup: Verification", open that screen and match it. Do not
   improvise a layout.

**First, before LP-UI-001:** `docs/design/` is untracked. Commit it so it cannot be
lost — `git add docs/design/ledger && git commit -m "docs: Ledger design system and
LP-UI tickets"` — then create a branch for the work.

## How to work

One ticket at a time, in the "Suggested order" at the bottom of `TICKETS.md`.
For each ticket:

- Tell me which ticket you are starting and what you understand it to require.
- Implement it. Files listed under **Assets** in a ticket are drop-in — copy them
  from `docs/design/ledger/assets/`, do not retype them.
- Run `pnpm biome check --write .`, `pnpm tsc --noEmit`, `pnpm test`. CI staying
  green is non-negotiable per this repo's `CLAUDE.md`.
- Check the result in **both** light and dark.
- Write `docs/tickets/LP-UI-XXX.md` recording what you did, what you assumed and
  what you decided — the convention this repo already uses. Architectural decisions
  go in `decisions.md` as a new ADR.
- Commit, then stop and show me before starting the next ticket.

## Rules that hold across every ticket

- **No `gray-*` classes may re-enter the codebase** after LP-UI-004.
- **No `font-bold`.** The config caps weight at 600 deliberately.
- **No new hex colours.** If a screen seems to need one, the screen is wrong — say
  so on the ticket instead of adding it.
- Status is always colour **and** glyph shape **and** word, via `<StatusToken>`.
- Never merge or sum the governed rule findings with the legacy AI sweep. That
  separation is structural (LP-375) and the redesign preserves it.
- Preserve the existing wording on statuses and outcomes. LP-583 and LP-581 argued
  those labels out; only the colour vocabulary is being unified.

## Start here

**LP-UI-001.** Epic A (001 → 005) must land in order and must land first.

Two things to expect:

1. The app will look **worse** between LP-UI-001 and LP-UI-004, because 784
   hardcoded greys are still fighting the new tokens for those three tickets. That
   is expected. Do not tune the palette to compensate — LP-UI-004 resolves it.
2. LP-UI-002 fixes a live bug: twenty class names reference a `danger` colour that
   has never existed in `tailwind.config.ts`, so `FailedRunBanner` — the banner
   that reports a dead verification run — currently renders grey. Verify the fix by
   forcing a failed run and looking at it.

The token files already assume four decisions: petrol `#12545E` as the accent
rather than the current Tailwind blue, dark mode shipping now, staying on Radix
rather than migrating to Base UI, and Needs becoming its own route. Flag it if any
of those should change; do not change them on your own.

One ticket is blocked and you should raise it early: **LP-UI-029** asks whether the
extraction pipeline stores bounding-box coordinates. `SourceLocation` carries
`page` and `snippet` today. Epic E cannot be scheduled honestly until that is
answered — check the backend and tell me what you find.
