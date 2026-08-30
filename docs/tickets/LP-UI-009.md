# LP-UI-009 — File context rail

- **Ticket:** LP-UI-009 — the 288px right-hand rail on file routes
- **Epic:** Ledger redesign → Epic B (Primitives and shell)
- **Status:** Completed
- **Date:** 2026-08-29
- **Mockup:** Overview, Verification, Documents — right-hand column

## Summary

The fourth region of the shell. Loan amount, DTI, LTV and reserves are the
numbers a processor switches tabs to check; the rail pins them beside the work
surface on every file route, so the switching mostly stops.

Verified on the Communication tab — a Phase-4 placeholder with no data of its
own — where all four numbers are on screen anyway. That is the whole argument
for the rail in one screenshot.

## What Changed

- **`components/layout/file-context-rail.tsx`** (new). Always: status, loan
  (amount / program / purpose), ratios (back-end DTI against its limit,
  front-end DTI, LTV, reserves), recent activity. Plus one tab-specific section:
  coverage and freshness on Documents, run counts and last-run age on
  Verification.
- **`app/(protected)/loan-files/[id]/layout.tsx`** — the rail is a sibling of
  the work surface, not inside it, so the two scroll independently. `-m-4`
  cancels the shell's page padding so the rail meets the window edge and its
  border is the seam.

## Verification

**Geometry, measured on four file routes:** width **288px** on every one,
`overflow-y: auto` (its own scroll), and the tab-specific section present only
on its own tab — `Documents` on `/documents`, `Verification` on `/verification`,
absent on Overview and Communication.

**Below `xl` (1200px):** `display: none`, width 0. Unlike the LP-UI-008 collapse
bug, `display: none` removes it from the tab order and the accessibility tree as
well as from view. The rail also has **zero focusable elements** — it is
read-only by design — so it adds nothing to the keyboard path either way.

**Values render correctly:** `$357,050`, back-end DTI `50.45%` shown in
`destructive` against its `/ 50%` limit, front-end `33.05%`, LTV `96.50%`,
reserves `26.5 months`, and the five most recent activity entries.

**CI.** biome, tsc, 541 tests, build — green.

## Finding raised: "no extra fetches" is not achievable as written

The acceptance says the rail should read *"from the queries already cached by the
file layout — no extra fetches"*. Measured rather than assumed: distinct API
requests per route, captured over CDP with and without the rail mounted.

| route | without rail | with rail | delta | what the rail adds |
|---|---|---|---|---|
| overview | 6 | 9 | **+3** | `dti`, `ltv`, `calculators/reserves` |
| documents | 2 | 6 | **+4** | `dti`, `ltv`, `calculators/reserves`, `activity` |
| verification | 10 | 11 | **+1** | `activity` |

**The criterion cannot hold alongside the rail's purpose.** The file layout
caches exactly one query, `useLoanFile`. DTI, LTV and reserves are fetched by
the Verification tab because that is the tab that owns them — and the entire
point of the rail is that a processor should not have to go to that tab to see
them. Putting those numbers on Documents necessarily fetches them on Documents.

What *is* true, and is the property worth having:

- **The rail adds no duplicate requests.** Every query it shares with a page is
  served from one request — React Query dedupes on the key. On Verification the
  rail's `dti`, `ltv` and `reserves` cost **zero** additional requests, because
  the calculators already fetch them; its whole delta there is `activity`.
- The delta is largest exactly where the rail is most useful (Documents, +4)
  and zero-to-small where the page already had the data.

Left as-is and raised rather than worked around, because the alternatives are
both worse: rendering the numbers only when some other tab happened to warm the
cache would make the rail blank on a fresh load of Documents, and prefetching
them in the layout would move the same four requests earlier, not remove them.
If the intent was "no *duplicate* fetches", the rail meets it; if it was
literally "no new requests", the ticket and the feature disagree and the ticket
should be amended.

**Unrelated observation from the same measurement:** in dev, most queries fire
twice (overview: 19 requests, 10 distinct). The pattern covers queries the rail
does not touch — `borrowers`, `stated-financials`, `needs` — so it is React
StrictMode's double-invoke in development, not something this ticket introduced.
Worth confirming it does not survive into a production build before anyone reads
it as a performance problem.

## Assumptions and decisions

- **Decided** the tab-specific hooks (`useLoanFileDocuments`,
  `useVerification`) mount only on their own tab, so the rail never introduces
  those requests anywhere else.
- **Decided** the rail is read-only — no buttons, no links. It is a reference
  surface beside the work, and every affordance added to it is a tab stop
  between the work surface and the page.
- **Decided** `humanize()` on program and purpose. They arrive as raw enums
  (`conventional`, `purchase`) and the file header already humanises them;
  showing both spellings on one screen is the drift this epic keeps finding.
- **Decided** the DTI limit reads *after* the value (`50.45% / 50%`). The first
  pass rendered the hint first, which read as `/ 50% 50.45%`.
- **Assumed** `completed_at` is the right "last run" timestamp;
  `VerificationRun` has no `created_at`.

## Files

- new: `components/layout/file-context-rail.tsx`
- changed: `app/(protected)/loan-files/[id]/layout.tsx`
