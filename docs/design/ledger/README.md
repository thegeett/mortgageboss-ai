# Ledger — the mortgageboss-ai frontend redesign

Everything needed to implement it. Start here.

```
docs/design/ledger/
├── README.md                  you are here
├── PROMPT.md                  the exact prompt to hand Claude Code
├── SPEC.md                    the design rules — read before every ticket
├── TICKETS.md                 40 tickets, LP-UI-001 … LP-UI-040
├── ledger-direction.html      why: the audit and the reasoning
├── ledger-plan.html           how and who: phases and division of labour
├── ledger-screens.html        the 16 screens — open in a browser
├── screens/*.png              one still per screen, for pasting into tickets
└── assets/
    ├── globals.css            drop-in replacement for app/globals.css
    ├── tailwind.config.ts     drop-in replacement for tailwind.config.ts
    ├── fonts.ts               → lib/fonts.ts (IBM Plex via next/font)
    ├── lib/status.ts          → lib/status.ts (one status vocabulary)
    ├── components/
    │   └── status-token.tsx   → components/status-token.tsx
    └── codemod-gray-to-token.mjs   run once, in LP-UI-004
```

## The one-paragraph version

The product's job is putting a stated number next to a found number and saying
whether they agree. That comparison has never appeared on screen as a comparison —
stated financials live on the Overview, extracted values in a document drawer, the
verdict in a finding on the Verification tab, and the processor holds it in their
head across three routes. Ledger is organised around making it visible: a
**reconciliation ledger** on the file overview, and a **document reviewer** that
puts a document beside its extracted fields with each field linked to the box it
was read from.

## Where the leverage is

95 non-test components, but the look lives in eight primitives and one token file.
The blocker is that **784 hardcoded `gray-*` classes across 67 of them bypass the
token layer** — which is why `darkMode: ["class"]` has never been switchable.
Twenty-one class names cover 780 of those, so it is a codemod, not a rewrite.

Epic A (five tickets, ~3 days) is where roughly 80% of the visual change lands.
Screens nobody designed — login, the admin pages — come out looking like Ledger
without anyone opening them.

## Three things worth knowing before you start

1. **There is a live bug.** Twenty class names reference a `danger` colour that has
   never existed in the config. `FailedRunBanner` — the banner that reports a dead
   verification run — renders grey. LP-UI-002.
2. **`text-gray-400` is used 180 times at 2.54:1 on white.** It fails AA for text
   and fails the 3:1 bar for icons. The codemod fixes it. LP-UI-004.
3. **One ticket blocks a whole epic.** LP-UI-029: does the extraction pipeline
   store bounding-box coordinates? `SourceLocation` carries `page` and `snippet`
   today. Answer it before scheduling Epic E.

## Open decisions

Confirm these before LP-UI-001, since they are baked into the tokens:

| | Recommendation |
|---|---|
| Petrol `#12545E` or keep Tailwind blue `#2563EB`? | Petrol — far in hue from red/amber/green, so it never competes with a status |
| Dark mode now or later? | Now — it is nearly free at this point and expensive to retrofit |
| Base UI or stay on Radix? | Stay. Migrate separately, never during a visual redesign |
| Does Needs get its own route? | Yes — LP-UI-022 assumes it |

## Verified, not assumed

- Every text tone clears 4.5:1 against its own ground in **both** themes
- `--input` (control border) clears 3:1 — WCAG 1.4.11
- The codemod was dry-run against this repo on 2026-08-29: **803 replacements,
  70 files, 3 left for a human** (named in the script's footer). Re-measured against
  HEAD before LP-UI-004; see `AMENDMENTS.md` A5 for why the earlier figure was wrong.
