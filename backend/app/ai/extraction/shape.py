"""Reusable extraction shape (LP-39a) — typed core + grouped catch-all + source.

Every document extraction shares one shape so the pieces downstream are uniform:

  * **Typed core** — the mortgage-decision-relevant fields, named and typed, each a
    :class:`TypedField` carrying the coerced ``value`` plus its :class:`SourceLocation`.
    The deterministic verification engine (Phase 3) consumes these typed values.
  * **Grouped catch-all** — *everything else* on the document, captured as
    :class:`CatchAllSection`\\ s (section → ``{label, value, page, snippet}``). Nothing
    is lost: processors see the full document and the Phase 3 AI cross-source layer has
    the full material to catch discrepancies (e.g. an undisclosed decree obligation).
  * **Source location** — every field (typed and catch-all) carries the ``page`` and a
    verbatim ``snippet`` it was read from, so a finding traces to the exact document line.

These types are reused by W-2 (LP-39b) and bank statement (LP-39c). Catch-all values
stay **strings** (not coerced); only the typed core is coerced. See ADR-144/145.

**Per-field confidence (LP-201).** Each typed-core field can carry a nullable
``confidence`` (0..1): the model's self-rating for that field, or ``None`` when the
model gave no number — **never a fabricated default**. The provenance tag is *not*
stored beside it; it is derived at read time from whether ``confidence`` is present
(:meth:`ConfidenceSource.for_confidence`), so the number and its tag can never
disagree. The slot is additive and nullable, so existing readers of ``value`` are
unaffected.
"""

from pydantic import BaseModel, Field


class SourceLocation(BaseModel):
    """Where on the document a value was read from (the trust/audit anchor)."""

    page: int | None = None
    snippet: str | None = None  # verbatim text the value was read from


class TypedField[T](BaseModel):
    """A typed-core value plus where it came from and how sure the model was.

    ``value`` is ``None`` when the field is absent/illegible (honest null, never
    fabricated) or when a present value couldn't be coerced — in the latter case
    ``source`` is still kept so the processor can see what the model read.

    ``confidence`` (LP-201) is the model's per-field certainty in ``[0, 1]``, or
    ``None`` when the model gave none. A ``None`` confidence is a legitimate,
    correct state — nothing is defaulted. The provenance tag is derived from this
    value at read time via :meth:`ConfidenceSource.for_confidence`, not stored, so
    there is no second field that could contradict it.
    """

    value: T | None = None
    source: SourceLocation | None = None
    confidence: float | None = None


class CatchAllField(BaseModel):
    """One captured field outside the typed core — value kept as a string."""

    label: str
    value: str | None = None
    source: SourceLocation | None = None


class CatchAllSection(BaseModel):
    """A named group of catch-all fields (e.g. "Earnings", "Deductions")."""

    section: str
    fields: list[CatchAllField] = Field(default_factory=list)
