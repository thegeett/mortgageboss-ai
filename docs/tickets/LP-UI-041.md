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

---

## Review (LP-UI-041 / LP-UI-042 review commit)

Reviewed on request from the session running the epic. Three findings, one claim
corrected, and the CORS change is clean. `SPEC.md` remains modified by neither of
us and is left alone.

### 1. The blob leak was fixed in the wrong place, and still leaked

Revoking on the cache's `removed` event rather than on an effect keyed to the url
is exactly right, and it fixes the reported bug. But `useRevokeOnEviction` ran
**inside `usePageImage`**, so the subscription was torn down on unmount — while
eviction happens later by design, five minutes after the last observer goes away
(TanStack's default `gcTime`, which this app does not override).

So leaving the reviewer removed every listener, and when the cache finally dropped
the entries there was nobody to revoke them. Every page a processor had opened
stayed held, as a full-page PNG, for the rest of the session. A forty-page
document read end to end retains forty of them.

The old comment stated the requirement correctly — *"something must outlive the
component, because the cached url does"* — and a per-component subscription cannot
satisfy it. `revokePageImagesOnEviction(client)` is attached in `makeQueryClient`
now, so its life is the cache's life. Both existing tests were building a bare
`new QueryClient`, which no longer carries the subscription; they use the real
factory, because a hand-built client tests one the app never constructs.

This is the ticket's item 2, and the risk is not the one it named. It was not "the
url lives until gc" — it lived *past* gc, indefinitely.

### 2. `SHARP_TO = 1.65` is not a constant, and its test could not fail

The arithmetic behind it is right: the server renders at `DEFAULT_ZOOM = 2.0`, so a
612pt page arrives as 1224px, and in a 736px pane that is 1.66× of headroom. But
that makes it a **ratio against the pane**, and a processor drags the pane:

| pane | sharp up to |
|---|---|
| 560px | 2.19× |
| 736px | 1.66× |
| 1024px | 1.20× |
| 1440px | 0.85× |

At 1440 even FIT is already soft — the case a single number cannot express. And
the test asserted `FIT <= SHARP_TO` and steps below FIT, which passes for **any**
value ≥ 1: it would have passed at 1.0, at 5, at 100. Nothing in the app read the
constant at all.

Replaced with `sharpUpTo(renderedWidthPx, displayedWidthPx)` and tests that do real
arithmetic, including the wide-pane case. Both inputs are available now — the
rendered width via `X-Page-Width-Points`, readable thanks to this ticket's own CORS
fix.

*Also:* my first version added a `displayedWidthPx <= 0` guard and a test for it.
Division already returns `Infinity`, so removing the guard changed nothing and the
test could not fail. The guard is gone; the behaviour is still asserted, stated as
behaviour so nobody adds a branch to produce what already happens.

### 3. Two provenance links described the behaviour they no longer have

`?doc=` now redirects to the reviewer, and both `finding-card.tsx` and
`reconciliation-ledger.tsx` still documented it as opening the details drawer. The
ledger's is more than stale: it explained that the page number could not be a link
target because *"there is no page canvas in the product yet — LP-UI-030 builds that
canvas; the page becomes a link target there."* That canvas shipped, and this
ticket pointed `?doc=` at it. The blocker named in the comment is gone; what
remains is that the reviewer keeps its page in component state rather than the
URL. Both comments now say what is true, and the ledger's names the small piece of
work that would finish the thought.

### Confirmed, not changed

- **The CORS change is clean.** Exactly four `X-Page-*` names, no wildcard;
  `allow_origins` is configured rather than `*`; only the page endpoint emits those
  headers, so nothing else becomes readable. Exposing a page count to a client that
  already holds the page bytes discloses nothing it could not derive by paging.
- **All three `?doc=` call sites still work.** The redirect preserves the id and
  the reviewer resolves by id, so a link to a superseded document now works
  *better* than the drawer did — the drawer could only open what was in the loaded
  list.
- **The documents table's cell counts agree.** Header 6, body 6, skeleton 6. The
  two `DOCUMENT_COLUMNS.length + 1` assertions derive from one source and cannot
  disagree — but neither compared to the header, so LP-UI-037's rendered
  header-vs-body comparison is now here too. Verified by dropping the header's
  nameless Details cell: both existing assertions still pass; the new one fails.

### Verification

biome 0, tsc 0, **990 vitest**, build clean. Backend: ruff 0, format 0, mypy strict
0, **6,158 pytest** — run because the CORS change touches `app/main.py`. Seven
mutations, all caught.
