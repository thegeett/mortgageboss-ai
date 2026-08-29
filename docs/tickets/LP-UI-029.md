# LP-UI-029 — Bounding-box coordinates in extraction

- **Ticket:** LP-UI-029 — does the extraction pipeline store bounding boxes?
- **Epic:** Ledger redesign → Epic E (Document reviewer) · **BLOCKS** LP-UI-030…033
- **Status:** Investigated — answer below. **Decision open**; no ADR written yet.
- **Date:** 2026-08-29
- **Raised early** because Epic E (~2 weeks) cannot be scheduled honestly until
  this is answered.

## The question

The reviewer's highlight needs a rectangle. Does the pipeline have one?

## Answer: no, and it cannot get one from the model

**`SourceLocation` carries `page` and `snippet`, nothing else.**
`backend/app/ai/extraction/shape.py:30`:

```python
class SourceLocation(BaseModel):
    """Where on the document a value was read from (the trust/audit anchor)."""
    page: int | None = None
    snippet: str | None = None  # verbatim text the value was read from
```

**There is no coordinate anywhere upstream of it, and no OCR stage that would
have produced one.** Documents reach the model as native base64 `document`
blocks — `build_document_block` (`backend/app/ai/client.py:135`) hands Claude the
whole PDF and the model reads it directly. There is no rasterisation step, no
Textract, no OCR engine, nothing that computes page geometry. `pdf_utils.py` is
explicit that it is *"a DEV-ONLY tool… not a pipeline step. The production
pipeline reads documents with AI directly (full-document native reading,
LP-38/39)"*. So the coordinate does not exist and is not being dropped somewhere —
it is never computed. Asking the model for one would be asking it to invent
numbers it has no way to measure.

Storage is `Extraction.extracted_data`, a JSON blob of `TypedField`s
(`backend/app/models/extraction.py:124`), so adding a `bbox` key needs no DDL —
only a shape change and a backfill for existing rows.

## The snippet-matching fallback is viable — measured, not assumed

The ticket proposes deriving the box by finding the snippet in the page's text
layer. That depends on the snippet actually being populated, so it was measured
against staging rather than assumed.

```sql
select count(*) filter (where v->>'value' is not null)                              as valued_fields,
       count(*) filter (where v->>'value' is not null and v->'source'->>'page'    is not null) as with_page,
       count(*) filter (where v->>'value' is not null and v->'source'->>'snippet' is not null) as with_snippet
from extractions e, lateral jsonb_each(e.extracted_data::jsonb) as f(k, v)
where jsonb_typeof(v) = 'object';
```

| measure | count |
|---|---|
| extractions on staging | 84 |
| top-level typed fields | 1,875 |
| fields carrying a `source` key | 1,875 (100%) |
| fields with a non-null **value** | 1,456 |
| …of those, with `page` | **1,443 (99.1%)** |
| …of those, with `snippet` | **1,443 (99.1%)** |
| null-valued fields that still carry a snippet | 1 |

The anchor text is there on essentially every extracted value, and it is absent
in exactly the right place — a field the model reported as absent carries no
snippet. `page` and `snippet` are populated together, never one without the other.

**PyMuPDF is already a dependency** (`pymupdf>=1.27.2.3`, used by `pdf_utils.py`),
and `page.search_for(text)` returns rectangles directly, so the interim needs no
new package — only a service that opens the stored PDF, searches page `n` for the
snippet, and normalises the rect against the page box.

## What is still unmeasured

Two numbers decide how well the fallback actually performs, and neither can come
from SQL — both need the document bytes:

1. **What share of stored documents have a usable text layer.** `search_for` finds
   nothing on a scan. `pdf_utils.has_text` already computes exactly this signal
   and is described as informational, so a one-off pass over stored documents
   would produce the number.
2. **Whether the snippet matches the text layer verbatim.** The model transcribes
   what it reads; PDF text extraction returns what is encoded. Ligatures, soft
   hyphens, column order and whitespace runs are the usual sources of drift, and a
   snippet that is *almost* right finds nothing under an exact search. This wants a
   measured hit rate on real files with a normalised-comparison fallback, not an
   assumption.

The ticket's own instinct is right, and worth keeping: the fallback fails on
scans, which is where confidence is already lowest — so it degrades in the
direction where the processor is already being asked to look closely.

## Recommendation

Do not block Epic E on true coordinates. Ship snippet matching, and treat the box
as **derived and optional**: `bbox: tuple[float, float, float, float] | None`,
normalised and page-relative as the ticket specifies, computed at read time or
cached, and **absent rather than approximate** when the search fails. The reviewer
then needs a designed no-box state — page `n` shown, snippet quoted, no rectangle —
which it needs anyway, because 0.9% of valued fields have no page either.

What that costs: the reviewer cannot promise a highlight on every field, so the
mockup's Review screen needs a state for "we know the page, not the spot".

The alternative — a real OCR/geometry stage — buys exact boxes on scans too, and
costs a new pipeline stage, a second read of every document, and a per-page bill,
for a feature that is a convenience over a snippet the processor can already read.

**This is a scheduling and architecture decision, so it is left open rather than
recorded as an ADR here.** Once it is made, the ADR goes in `decisions.md` and
this ticket becomes the implementation record.

## Files inspected

- `backend/app/ai/extraction/shape.py` — `SourceLocation`, `TypedField`
- `backend/app/ai/client.py` — `build_document_block`, `build_document_message`
- `backend/app/services/pdf_utils.py` — PyMuPDF text layer, `has_text`, dev-only
- `backend/app/models/extraction.py` — `extracted_data` JSON storage
- staging `readonly.extractions`, via `./scripts/deploy staging query`
