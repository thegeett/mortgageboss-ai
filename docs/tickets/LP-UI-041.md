# LP-UI-041 — Three reports from the document preview

Not a planned ticket: three things reported from the running app after the epic
closed. All three are in the reviewer, and two of them were mine.

## 1. The Documents tab opened a drawer, not the document

Clicking a row opened the details drawer. A processor clicking a pay stub wants
to see the pay stub, and the mockup's Documents screen (`05-documents.png`) has
no drawer on it at all — opening a document is screen 06, the reviewer.

LP-UI-030 built that reviewer as a separate route and deliberately left the
drawer as the Documents-tab behaviour. That was the wrong call: it left the
product's main way into a document pointing at metadata about the document.

**The row opens the document now.** The drawer's own answers — type override,
version history, staleness, replace, delete, download — are not lost: they are a
click away on a details control at the end of each row, because they are a
different question from "show me this document".

`?doc=` on the Documents tab now goes to the reviewer too. It is a **provenance**
link — it arrives from a finding, a ledger row or a snippet, meaning "show me the
document this came from" — and it was answering with a metadata panel.

## 2. The preview sometimes showed a broken-image icon

Reported as intermittent; reproduced deterministically. Page 1 → page 2 → back to
page 1 gave `naturalWidth: 0` on a live blob URL, which the browser draws as its
broken-image icon.

**The cause.** `useRevokeOnUnmount` revoked the object URL in an effect cleanup
keyed on the URL — and that cleanup also runs when the URL merely **changes**.
Meanwhile TanStack went on serving that same cached object for five minutes. So
paging away revoked a URL the cache would hand back.

The URL's lifetime belongs to the cached object, so the revoke belongs to the
cache's eviction. It now runs on the cache's `removed` event. The memory
discipline the original was protecting is intact — a forty-page document still
does not leak forty images.

**And a second line of defence.** A fetch that fails had a state; an image that
fails to *decode* did not. `onError` now shows the same honest "no page image"
sentence, so the browser's icon cannot appear whatever the cause. The state holds
*which* image failed rather than a boolean, so the next page is unaffected without
a reset effect that could lag a render.

## 3. The pager did not say how long the document was

It showed "Page 1" with no total, and Next was never disabled — so a reader could
click past the last page into a blank canvas with nothing explaining it.

**The count rides with the page.** The renderer already has the document open, so
counting there costs nothing; a second endpoint would reopen the same file to
answer a question this one already knows. The control now reads "Page 1 of 3",
Previous is disabled on the first page and Next on the last.

`null` means "not told" and is not the same as zero — the count arrives with page
1, and until it does the control guards only the lower bound.

## The latent bug found on the way

**None of the `X-Page-*` headers were readable by the browser.** A browser reads
no custom response header cross-origin unless the server names it in
`expose_headers`, and the CORS middleware named none. So since LP-UI-030
`widthPoints` and `heightPoints` had been arriving as **0** and `zoom` as its
fallback `1`.

Nothing depended on them yet — the highlight boxes are normalised percentages and
the image is sized by CSS — so it looked like it worked. The page count would
have been the first consumer, and it would have failed silently in exactly the
same way.

Four headers are now exposed, and the comment says why `allow_headers` (which is
about the *request*) does not help.

## Tests

- `lib/api/page-image.test.tsx` (5) — the URL surviving a page change, a working
  URL on the way back, revocation on eviction, and the count parsed as `null`
  rather than `0` when absent.
- `components/file/documents/reviewer/page-canvas.test.tsx` (10) — the broken
  image replaced by the explanation, a fresh chance for the next page and the next
  document, the pager's total, and both bounds.
- `document-list.test.tsx` — the row opening the document and the details button
  opening the drawer, including that the details click does not also navigate.
- `tests/api/test_documents_endpoints.py`, `tests/services/test_page_render.py` —
  the count on the header and from the renderer.

Mutation-checked, 13 across the three fixes, all caught bar two that were bad
mutations rather than gaps: one changed a constant used on both sides of the
comparison it was meant to break, and one hid a table cell rather than removing
it, which jsdom counts either way.

CI green by exit code: biome, tsc, 968 vitest; ruff, ruff format, mypy strict,
6158 pytest. Verified live in the browser for all three reports.
