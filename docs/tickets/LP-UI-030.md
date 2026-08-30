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
