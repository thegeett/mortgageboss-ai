# LP-UI-016 — File overview: identity strip

- **Ticket:** LP-UI-016 — one identity strip, tabs into the context column
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Mockup:** Overview — top strip

## Summary

The file header is one strip: who, which file, what kind of loan, whose lender
and where it stands on the left; the loan amount and the property it is secured
on set right. Two things left it — the back link became a topbar breadcrumb, and
the tab strip moved into the shell's context column.

**This closes the duplication raised on LP-UI-008.** That ticket put the six file
sections in the context column and noted the file page still rendered the same
six as a tab strip directly beneath the header — "the kind of thing that reads as
an unfinished migration". It was LP-UI-013's to decide and this is where it lands.

## What Changed

- `components/file/file-header.tsx` — rewritten as the identity strip.
- `components/layout/breadcrumb.tsx` (new) — `Pipeline / <borrower> <LF-ID>` in
  the topbar, reading the file from the query the layout already cached.
- `components/layout/header.tsx` — renders the breadcrumb instead of a title.
- `app/(protected)/loan-files/[id]/layout.tsx` — the tab strip is gone.
- **Deleted:** `components/file/file-tabs.tsx`, `lib/loan-files/tabs.ts` and its
  test — orphaned once the strip went (see Decisions).

## Verification

Measured in the browser on a real file:

| | |
|---|---|
| breadcrumb | `Pipeline / Bharat Kapadiya  LF-96SV` |
| strip | name + `Draft` status token, then `LF-96SV` · `Conventional` · `Purchase` |
| right | `$357,050` over `860 Balfour Drive` |
| tab strip | **gone** (`nav[aria-label="File sections"]` absent) |
| context column | Overview, Documents, Verification, Communication, Conditions, Lender package |

**Skeleton height, which took four attempts to measure honestly.** The criterion
is that the skeleton and the loaded strip are the same height, and my first
measurement said 52 vs 54 — a real 2px jump, fixed by setting the shared
`min-h` to the loaded strip's actual height rather than a guessed one.

Confirming the fix was harder than making it, and the failures are worth
recording because each looked like a result:

1. Sampling at 1.1s caught a **different** `[aria-busy]` element — the tab's
   loading block, not the header's — and reported 168px.
2. Targeting the header's own live region returned `null`: on localhost the
   query resolves faster than the probe can sample.
3. `Network.setBlockedURLs` held the request but produced the **error** state,
   which is a different screen (869px).
4. 4s of emulated latency held the request but the shell's auth loader was still
   up, so the header had not rendered at all.

What worked was forcing `<FileHeader file={undefined} />` in the layout,
measuring, and reverting: **skeleton 54px, loaded 54.4px** — 0.4px apart, below
one device pixel.

**CI.** biome, tsc, 605 tests, build — green.

## Decisions

- **Deleted `lib/loan-files/tabs.ts` rather than leaving it.** It held the same
  six sections `fileSections()` in `lib/navigation.ts` now owns, and two
  producers of one list is the shape three reviews in this epic have flagged.
  The one that renders should be the one that decides. Its `phase` metadata had
  no consumer — the placeholder pages hard-code their own copy.
- **The breadcrumb reads the cached file query**, so it costs no request. Before
  the file resolves it shows the id from the URL, which is real and already on
  screen — a skeleton there would flicker a word into a bar and back for a query
  that usually resolves instantly.
- **Status renders through `StatusToken`**, not the old `StatusBadge` pill, so
  the strip carries colour + glyph + word like every other status in the app.
- **Assumed** the context column is the only file navigation now. On a narrow
  screen the column is hidden below `md`, which means the file's sections are
  currently unreachable there — raised below.

## Finding raised

**Below `md`, a file's sections have no navigation.** The tab strip used to be
the mobile affordance: it scrolled horizontally and was always present. The
context column that replaced it is `hidden … md:block`, and the header's mobile
menu only carries top-level destinations (Dashboard, Administration). So on a
phone you can open a file and cannot reach its Documents or Verification tabs.

Not fixed here because the fix is a design decision rather than a patch — a
drawer, a select, or a horizontal strip that returns only below `md` — and
LP-UI-037 ("Narrow-width pass") is the ticket that owns exactly this question.
Recording it now so that ticket starts from a known defect rather than
rediscovering it.

## Files

- new: `components/layout/breadcrumb.tsx`
- changed: `components/file/file-header.tsx`, `components/layout/header.tsx`,
  `app/(protected)/loan-files/[id]/layout.tsx`, `lib/navigation.ts`
- deleted: `components/file/file-tabs.tsx`, `lib/loan-files/tabs.ts`,
  `lib/loan-files/tabs.test.ts`

## Review pass — a route you could reach and then not leave

Reviewed on request from the session running the epic. Two defects fixed, two
judgement calls confirmed, and one raised-not-fixed overruled.

### Below `md` a file had no navigation at all — fixed, not recorded

Raised in the hand-off with an offer to record it for LP-UI-037, and this is the
one place to overrule that. LP-UI-037 owns narrow-width *design*; this is a route
becoming unreachable. You could open a file on a phone and have no way to get to
Documents or Verification — not "cramped", not "unpolished", **gone** — and the
tab strip that used to serve that case was removed by this ticket tonight.

A regression is not scheduled, it is undone. And the fix is small because the
work was already done: `contextSection(pathname)` already returns the file's
sections, so the header's mobile menu now carries the column's own items below a
separator, marked current with `activeItemHref` — the same longest-match rule the
column uses, so the two cannot disagree about where you are.

It adds nothing on the dashboard, whose column is saved views and whose `items`
are empty. A bare section heading with no entries would be worse than nothing.

### The breadcrumb and the file header disagreed about a nameless file

`{file?.primary_borrower_name ?? fileId}` — the id fallback is right for the
LOADING case, which the hand-off reasoned about carefully and got right. Left in
place after the file resolves it also answers "this file has no borrower", and
then it prints the id twice on one line: once as the title, once in the chip
immediately beside it that exists to carry exactly that.

`FileHeader`, three feet below, already says "Unnamed file". Two answers to what
the file is called, on one screen. The breadcrumb now says the same words, and
the id fallback is scoped to the case it was written for.

### On the measurement, and what a test can honestly add

The hand-off's account of measuring the strip is the most useful thing in it:
four attempts, three of which produced a number that looked like a result and was
not — a different `[aria-busy]` element, a live region that resolved faster than
the sample, an error state, an auth loader. It found a real 2px jump and fixed it.

That measurement is the browser's job and this is not a re-run of it; jsdom has
no layout. What the new test pins is the MECHANISM the measurement confirmed —
both branches are the same element with the same min-height — which is what an
edit would break. Mutation-checked by giving the skeleton branch its own wrapper,
which is exactly the shape of the defect that was found by hand.

Worth being precise about the limit: this test would not catch a change to the
shared constant, because both branches move together and the property still
holds. That is correct — the property is "they agree", not "they are 54px".

### Confirmed, not changed

- **Deleting `tabs.ts` and `file-tabs.tsx` is safe.** The `phase` strings are
  passed to `TabPlaceholder` as literals at each call site
  (`phase="Phase 4.5"` and so on) — nothing read them through `FILE_TABS`.
  Checked across `app/`, `components/` and `lib/`.
- **The breadcrumb's `useLoanFile` costs no request.** The file layout calls
  `useLoanFile(params.id)` and the breadcrumb calls
  `useLoanFile(loanFileIdFromPath(pathname))`; both are the same URL segment, so
  both produce the query key `["loan-file", <id>]` and React Query serves one
  request. Same key ⇒ one fetch is a stronger guarantee than a counted request,
  because it cannot drift with timing.
- **Showing the URL id before the file resolves is right**, and the reasoning
  holds: the id is real, already on screen, and a skeleton would flicker a word
  into a bar and back for a query that usually hits cache. The UUID case the
  hand-off worried about is narrower than it feared — rows navigate by
  `display_id`, so a UUID only appears if someone hand-built the URL, and then
  the UUID is what they typed.

### Verification

`tsc` clean, `biome` clean over 228 files, **617 tests** (from 605), build
compiles. Every fix mutation-checked:

| mutation | result |
| --- | --- |
| revert the mobile menu to top-level destinations only | 2 tests fail |
| fall back to the id after the file resolves | 1 test fails |
| give the skeleton branch its own wrapper | 1 test fails |

One test was strengthened before it went in. The "adds nothing on the dashboard"
case asserts a menu item is ABSENT, which passes just as well when the menu never
opened — which is precisely the broken-probe-reads-as-a-feature failure the
hand-off described hitting with Radix's pointerdown. It now asserts a positive
alongside it.
