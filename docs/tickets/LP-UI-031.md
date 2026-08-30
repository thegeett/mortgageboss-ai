# LP-UI-031 — Field ↔ box bidirectional linking

Epic E (the document reviewer). Builds on LP-UI-030's three-pane shell and its
server-rendered page images.

## What the ticket asked for

Link the extracted-fields pane to the page image in both directions: focus a
field and the viewer goes to where it was read from; hover or click a highlight
on the page and the matching field is picked out. Hold `Alt` to reveal every
other candidate at once. And the guardrail the ticket singles out — *"if a field
is already selected and the user clicks a different value on the document,
navigate to that other field rather than overwriting the selected field's value.
It is the single most common destructive misclick in this entire interaction
pattern."*

## What was built

**Backend — `app/services/field_boxes.py`, `GET /documents/{id}/boxes`.**
The extraction already records the verbatim text each value was read from.
`page.search_for()` locates that text and returns its rectangle, normalised 0..1
against the page box so the overlay works at any zoom without being told which
zoom the image was rendered at. PyMuPDF, the same library that renders the page
in LP-UI-030 — one library is one coordinate space, and a box a few points off is
worse than no box because it points confidently at the wrong words.

The endpoint sits behind the same tenant gate as `/download`: a box is derived
from the document's own text, so it is exactly as sensitive as the page it
describes.

**Frontend — `box-overlay.tsx`, `use-field-selection.ts`, and the wiring in the
review route.** Three directions, one selection hook.

## What the numbers say

Measured over the 105 stored PDFs, 752 valued fields:

| | | |
|---|---|---|
| 548 | 72.9% | found on the cited page |
| 32 | 4.3% | cited a page **the document does not have** |
| 89 | 11.8% | snippet absent from the text layer entirely |
| 83 | 11.0% | document is a scan, no text layer at all |

So a box is absent for roughly a quarter of fields. The reviewer's no-box state
is ordinary rather than exceptional, and the screen says so in words rather than
leaving a field that simply never highlights.

## Decisions

**The 32 are a fabricated citation, not a near miss.** Not one of them cites a
wrong-but-existing page — every one names a page beyond the document's length,
"p.7" of a three-page letter. There is therefore no cited page to render, and
searching the rest of the document is the only way to show the processor
anything. The service does that, and `cited_page_exists=False` travels with the
result so the screen can say *the extraction cited a page this document does not
have* rather than quietly substituting a better answer. Correcting the model
silently is how a provenance trail stops being one.

**Clicking a box navigates; it never fills.** `useFieldSelection` returns what a
click did (`selected` / `navigated` / `reselected`) so a caller can act on the
distinction rather than infer it from the state afterwards. Filling a value
happens only from the field's own editor. The outcome is computed against a ref
rather than inside the `setState` updater — the updater runs after the call
returns, so deciding there reported every click as `selected`. The test caught
that, not the reading.

**A snippet matching more than `MAX_MATCHES` (8) places on a page yields no
box.** A bare "Total" appears forty times on a bank statement; painting the page
and calling it provenance is worse than showing none.

**`Alt` is held, not toggled.** It is a peek at what else the extraction found,
not a mode to be left switched on. The handler clears on `blur` as well as
`keyup`, because alt-tabbing away is the ordinary way to leave this page and the
keyup then lands in another window.

**A field with no value gets no note.** Saying "not locatable" about a field the
extraction never filled reads as a lookup failure rather than an empty field —
caught on screen, not in review, and the disclosure now needs a citation to fail
before it will speak.

**One PDF open per request, not one per field.** `find_all_field_boxes` opens the
document once and searches for every field inside it. The per-field entry point
remains for a single lookup.

## Two things found while checking the work

**The rings never drew.** `cn()`'s tailwind-merge groups `outline` (style) with
`outline-1` (width) and keeps only the later one, leaving `outline-style: none`.
Every box was present, positioned and invisible; the opacity assertions passed
throughout. Fixed with `[outline-style:solid]`, which belongs to no merge group,
and a test that asserts on the class list rather than on opacity.

**A 2px border inside the box covered the word.** A box is the text's own
bounding rectangle, which on a pay stub is about ten pixels tall. The highlight
is an `outline` with `outline-offset-1` — outside the rectangle, leaving the
glyphs legible, which is the entire point of highlighting them.

## Also fixed here

`users.reviewer_pane_split`, added in LP-UI-030, was neither exposed by a
readonly view nor excluded, so `test_no_model_column_drifts` was failing on
`main`. Excluded, with the reason recorded in that migration: the readonly
surface answers questions about loan data, and a processor's pane geometry
answers none of them. Not a privacy decision — it is two integers.

## Tests

- `tests/services/test_field_boxes.py` — 15, covering the cited page, the
  fabricated citation, the match cap, normalisation, and the batch path.
  Mutation-checked: silent page substitution, no match cap, absolute instead of
  normalised coordinates, never searching other pages, every field given the
  first field's answer, an unopenable document answering nothing, and a batch
  that never reports a relocation — all caught.
- `tests/api/test_documents_endpoints.py` — the endpoint behind its tenant gate.
- `box-overlay.test.tsx` (9), `citation-note.test.tsx` (6),
  `use-field-selection.test.ts` (6). Mutation-checked: the guardrail removed, a
  reselect reported as a navigation, the deferred-updater bug, hover reassigning
  the selection, every page's boxes drawn over one page, unselected boxes always
  visible, a box named by its coordinates, width measured from the origin, focus
  no longer linking back, a bad citation silently corrected, an unfilled field
  told it could not be located — all caught.

Checked in light and dark. CI green: biome, tsc, 756 vitest; ruff, mypy strict,
6093 pytest.

## Note on the local `.env`

`ANTHROPIC_MODEL_ANALYSIS` is pinned to Sonnet in `backend/.env` while LP-628
moved the shipped default to Haiku, so `tests/ai/test_model_selection_lp457.py`
fails locally and passes in CI. Left alone — changing it changes which model the
Tier-3 analyzer uses on this machine, which is not this ticket's call.
