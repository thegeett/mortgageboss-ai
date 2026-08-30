# LP-UI-030 — Reviewer shell: three resizable panes

- **Ticket:** LP-UI-030
- **Epic:** Ledger redesign → Epic E (Document reviewer)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-029
- **ADR:** none new.

## The measurement LP-UI-029 left open, taken

LP-UI-029 answered "are there bounding boxes" (no) and recommended snippet
matching, explicitly leaving two numbers unmeasured because they need document
bytes rather than SQL. Both are measured now, over **105 real stored PDFs** (5
seed stubs excluded — a synthetic PDF whose entire text is `DEMO <filename>`
would have been counted as a snippet miss and blamed the approach for data that
was never a document):

| | fields | share |
|---|---|---|
| snippet found on the **cited** page | 548 | **72.9%** |
| findable on a **different** page | 28 | 3.7% |
| absent from the text layer entirely | 89 | 11.8% |
| on a scan (no text layer at all) | 83 | 11.0% |
| cited page out of range **and** absent | 4 | 0.5% |

**A derived box is reachable for ~77% of fields** with a document-wide fallback —
not the 99.1% that LP-UI-029's coverage figure could be read as promising. That
figure measured *snippet present*; this measures *snippet findable*. 12 of the
105 PDFs are scans.

**And a finding beyond boxes:** on 28 fields the snippet is real but sits on a
different page than the one recorded, and on 4 the cited page does not exist in
the document. So the page number is wrong on roughly 4% of fields — and
LP-UI-018's reconciliation ledger already shows processors "p.N" as provenance.
Raised rather than fixed here; it is an extraction-quality question.

## Why the page renders server-side

PyMuPDF is already on the production path, so this adds no dependency. The
stronger reason is that LP-UI-031 derives the highlight rectangle with
`page.search_for()`, which returns coordinates in the page's own point space.
Rendering the image with the same library means the box and the pixels come from
**one renderer**. Two engines would be two coordinate spaces, and a box a few
points off is worse than no box, because it points confidently at the wrong words.

The geometry travels in the response headers with the image, not in a second
request, because a caller placing a box needs both and fetching them separately
is how they drift.

## The no-page state is a designed state

`GET /documents/{id}/page/{n}` returns 404 for a scan, a non-PDF, and a page the
document does not have — all reachable, per the numbers above. The canvas says
which of those it is and keeps the fields panel with its snippets beside it,
because on a document with no page image the snippet is the only provenance a
processor has.

The endpoint is behind the same tenant gate as `/download`: a rendered page **is**
the document's content, so it is exactly as sensitive as the bytes.

## The three criteria

- **Split persists per user.** A new nullable `users.reviewer_pane_split` (JSON,
  hand-written migration — autogenerate proposes 18 destructive operations against
  this schema). `NULL` means never adjusted, which the reviewer renders as its own
  default rather than writing a value nobody chose. Validated server-side: a
  client could otherwise persist `[90, 5]`, give itself a pane it cannot grab, and
  have that survive to the next session.
- **Page canvas renders a real PDF page.** Verified against a stored document:
  612×792 points at 2x zoom, `private` cache only.
- **The drawer remains the fallback.** Untouched. The Documents tab still opens it,
  `?doc=` still works, and the reviewer is a separate route because reading one
  document closely is a different job from seeing what is on the file.

**Container queries** are on the fields pane in plain CSS rather than via a
Tailwind plugin: the rows reflow to the pane's own width, so dragging it from
320px to 720px relayouts without the window changing — which a media query cannot
answer, because it would lay out for a viewport the pane no longer fills.

## An entry point, deliberately

The Documents tab links to the reviewer. Without it the route is reachable only by
typing a URL — LP-UI-016's rule facing the other way: a screen nobody can get to
is not shipped.

## Tests

726 frontend (from 716) and 6,070 backend, with the two known model-selection
failures. Twelve mutations verified to fail across the renderer and the shell,
each with the edit confirmed to have landed.

**Four mutations that silently did not apply**, caught by an assertion in the
mutator rather than by reading the result: a shell helper lost its argument
passing, so every "12 passed" meant nothing. That is the fourth distinct route to
a green run that proves nothing — after a wrong path, an excluding `-k` filter,
and a wrong target file.

One test fixture corrected rather than worked around: `PDF_BYTES` in the document
endpoint tests is a header and a comment, which is enough for upload and download
because they move bytes, and not enough for anything that **opens** the file. The
page tests build a real PDF; asserting a render against a stub would have been
asserting a 404 and calling it success.

## Review pass — the split meant the same thing twice, and the 28 are worse than reported

Reviewed on request from the session running the epic. One gap closed, the
measurement re-run and one of its conclusions corrected, and both remaining calls
confirmed.

### The pane split had two definitions that agree by coincidence

Asked for directly, and they do agree: the browser clamps with `MIN_PANE = 10`
and `MAX_TWO = 90`, the server rejects `pct < 10` and `sum > 90`. Same set,
including the boundary — the clamp caps the first pane at 80 so the second always
has at least 10 left, and both are rounded to integers for a `list[int]` column.

Nothing pins it. Raise the server's floor to 15 and the browser goes on producing
splits it now rejects: a drag that saves nothing and says nothing, because the
value is written on drag end and the failure is a 422 nobody is watching for.

Guarded with the instrument this repo already uses for cross-boundary agreement
(`ledger-assets.test.ts`): the test reads the numbers out of
`schemas/preferences.py` and asserts every clamp output satisfies them.
Restating them in TypeScript would have been the second definition it exists to
prevent. Mutation-checked by raising the server floor — six cases fail.

### The measurement re-runs identically, and one flaw does not bite here

Re-ran the script rather than reading it, with one correction: it selected
**every** `Extraction`, including superseded versions, whose snippets belong to a
document that may since have been replaced — fields no screen shows. Filtering to
`is_current` reproduces the published numbers **exactly** (548 / 28 / 89 / 83 /
4 of 752), because no superseded extraction exists in this database. The flaw is
real as method and has no effect on this result.

Two notes on the rest of the method, both favourable:

- It uses `page.search_for()`, which is what LP-UI-031 will use to derive the
  box. "Findable" therefore means findable *by the mechanism that will do it*,
  which is the right instrument and not a proxy for it.
- `norm()` is defined and never called, so no whitespace normalisation is
  applied. `search_for` is fairly literal, so a snippet differing only in a line
  break counts as absent. That makes 76.6% a **lower bound**, which is the safe
  direction for a claim about reachability.

Excluding the five seed stubs is right and correctly counted separately: their
entire text is `DEMO <filename>`, and counting 43 fields against them as misses
would have blamed the approach for data that was never a document.

### The 28 are not "a different page" — the cited page does not exist

The one correction. The script buckets a recoverable snippet two ways:
`found_on_another_page` when the cited page is in range, and
`oob_found_elsewhere` when it is not. The output carries
**`oob_found_elsewhere: 28` and no `found_on_another_page` key at all** — and a
`Counter` only holds keys it incremented, so that count is zero.

So no field cites a wrong-but-existing page. All 28 cite a page number **the
document does not have**, alongside the 4 that are out of range and absent
entirely: **32 of 752 fields, 4.3%, cite a page that does not exist.**

That is a different and worse defect than an attribution drifting by a page. It
is the model inventing a page number — "p.7" of a three-page letter — and
LP-UI-018's ledger renders exactly that string to a processor as provenance, as
fact, on a compliance screen. Raised to the user with this review, along with the
12 of 105 scans for which no highlight is derivable at all.

### Confirmed, not changed

- **Server-side rendering with PyMuPDF.** Right, and the coordinate argument is
  the one that decides it. LP-UI-031 derives the box with `page.search_for()`,
  which returns page-space rectangles; rendering with a second engine means two
  coordinate spaces and a box a few points out — worse than no box, because it
  points confidently at the wrong words. The dependency question is secondary and
  would not have been enough on its own.
- **Validating the split server-side.** Right for the reason given: the value is
  JSON and it *survives*. A refresh does not fix a pane you cannot grab.
- **Correcting `PDF_BYTES` rather than working around it.** Right, and it is the
  fixture rule in a new shape: a stub that is a header and a comment is enough
  for upload and download, which move bytes, and not for anything that OPENS the
  file. Asserting a render against it would have asserted a 404 and called it
  success.

### The fourth route to one hazard

Four mutations that silently did not apply, because a shell helper lost its
argument passing. The family is now: a wrong path, an excluding `-k` filter
(mine), a wrong target file, and arguments never reaching the edit. All four
produce a green run that means nothing; none is visible in the result. The
`IndexError` is what surfaced this one, and the anchor assert is what would have.

### Verification

Frontend `tsc` and `biome` clean over 249 files, **735 tests**. Backend `ruff`
and `mypy` clean over 451 files.

| mutation | result |
| --- | --- |
| raise the server's pane floor above the browser's | 6 tests fail |
