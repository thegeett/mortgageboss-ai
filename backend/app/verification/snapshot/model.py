"""The frozen three-section snapshot model (LP-204, ADR-241).

The immutable container for a per-run snapshot, built on LP-203's ``Field`` /
``PiiField`` primitives. Nothing populates it yet — the assemblers (LP-205/206/207)
and the builder (LP-208) come later; this is the schema they code against and the
shape persisted as JSON (LP-209).

Three independent sections, **deliberately un-linkable**:

* ``mismo`` — a flat ``key → Field|PiiField`` map of parsed 1003/MISMO facts.
* ``documents`` — an ordered list of :class:`DocumentEntry`, each the extracted
  fields of one document plus a *resolved* ``belongs_to`` borrower reference
  (LP-202). The document's raw asserted name stays as an ordinary entry in
  ``fields``; ``belongs_to`` is the resolved link, never the raw name.
* ``calculations`` — the four calculators' output as ``{value, breakdown}``, each
  breakdown line keeping the calculator's own per-line source tag.

**No cross-section correlation.** There is no field anywhere that references
another section's keys/entries — so a link *between* sections cannot even be
expressed. Correlating MISMO vs document facts is a downstream job, excluded here
by construction (ADR-241).

**Absent ≠ empty** survives at both levels: a ``Field``/``PiiField`` no source
supplied is absent (LP-203); a whole section can likewise be ``absent`` (not built
/ failed), distinct from present-but-empty (e.g. "no documents yet" = a present,
empty list). Both survive JSON round-trip losslessly.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, model_validator
from pydantic import Field as PydField

from app.models.document_borrower_link import MatchMethod
from app.verification.snapshot.fields import Field
from app.verification.snapshot.pii import PiiField

# The on-disk snapshot shape version. Bump when the structure changes so a reader
# always knows which shape it holds (readers branch on this; see ADR-241).
SNAPSHOT_VERSION = 1

# A snapshot cell is either a plain fact or a masked PII fact. The two are
# mutually exclusive under LP-203's ``extra="forbid"`` (``value`` vs
# ``display``/``match_hash``), so the union round-trips unambiguously.
SnapshotField = Field | PiiField


class BorrowerLink(BaseModel):
    """A resolved document→borrower reference (LP-202), self-describing in the blob.

    Carries the borrower id plus the match provenance (confidence + method) so a
    reader needs no DB join. This references a borrower *entity*, not another
    snapshot section — the one allowed correlation, and the deliberate opposite of
    matching raw names across sections at read time.
    """

    model_config = {"frozen": True}

    borrower_id: UUID
    confidence: float
    method: MatchMethod


class MismoSection(BaseModel):
    """The parsed-MISMO facts: a flat ``key → Field|PiiField`` map.

    ``absent`` marks the section as not-built/failed (distinct from a present-empty
    map — no MISMO facts). Keys are free strings (e.g.
    ``"borrower.1.income.base_monthly"``) — deliberately unconstrained so new facts
    never need a schema change.
    """

    model_config = {"frozen": True}

    facts: dict[str, SnapshotField] = PydField(default_factory=dict)
    absent: bool = False

    @model_validator(mode="after")
    def _absent_is_empty(self) -> MismoSection:
        if self.absent and self.facts:
            raise ValueError("an absent MismoSection carries no facts")
        return self

    @classmethod
    def present(cls, facts: dict[str, SnapshotField] | None = None) -> MismoSection:
        return cls(facts=facts or {}, absent=False)

    @classmethod
    def missing(cls) -> MismoSection:
        return cls(absent=True)

    @property
    def is_present(self) -> bool:
        return not self.absent


class DocumentEntry(BaseModel):
    """One document's contribution: type + resolved borrower(s) + extracted fields.

    ``belongs_to`` is ``None`` when no borrower resolved, or a **non-empty** list of
    :class:`BorrowerLink` (one, or many for a joint document). The document's raw
    asserted name is NOT here — it stays as an ordinary entry in ``fields``.
    """

    model_config = {"frozen": True}

    document_type: str | None = None
    belongs_to: list[BorrowerLink] | None = None
    fields: dict[str, SnapshotField] = PydField(default_factory=dict)

    @model_validator(mode="after")
    def _belongs_to_null_or_nonempty(self) -> DocumentEntry:
        # None = unresolved; a list must carry at least one link (use None for none),
        # so "resolved to nobody" can't masquerade as an empty list.
        if self.belongs_to is not None and len(self.belongs_to) == 0:
            raise ValueError("belongs_to is None (unresolved) or a non-empty list — never []")
        return self


class DocumentsSection(BaseModel):
    """The ordered documents. An empty ``entries`` list is PRESENT ("no documents
    yet"); ``absent`` marks the section not-built/failed — a distinct state.
    """

    model_config = {"frozen": True}

    entries: list[DocumentEntry] = PydField(default_factory=list)
    absent: bool = False

    @model_validator(mode="after")
    def _absent_is_empty(self) -> DocumentsSection:
        if self.absent and self.entries:
            raise ValueError("an absent DocumentsSection carries no entries")
        return self

    @classmethod
    def present(cls, entries: list[DocumentEntry] | None = None) -> DocumentsSection:
        return cls(entries=entries or [], absent=False)

    @classmethod
    def missing(cls) -> DocumentsSection:
        return cls(absent=True)

    @property
    def is_present(self) -> bool:
        return not self.absent


class CalcBreakdownLine(BaseModel):
    """One itemized calculator input, keeping the calculator's own source tag.

    ``source`` is the calculator vocabulary (``stated`` / ``computed`` /
    ``extracted`` / ``manual`` / ``override``) — a free string, NOT the
    ``FieldSource`` used elsewhere, and deliberately unconstrained so a new tag
    round-trips.
    """

    model_config = {"frozen": True}

    key: str
    label: str
    amount: str | None = None  # money serialized as an exact string
    source: str
    overridden: bool = False


class CalculationEntry(BaseModel):
    """One calculator's output: headline ``value`` map + itemized ``breakdown``.

    ``value`` holds stringified headline numbers (e.g. ``{"back_end_dti": "43.10"}``)
    so the blob serializes exactly. The container never computes — it holds what a
    calculator produced (LP-207 maps them in).
    """

    model_config = {"frozen": True}

    value: dict[str, str | bool | None] = PydField(default_factory=dict)
    breakdown: list[CalcBreakdownLine] = PydField(default_factory=list)


class CalculationsSection(BaseModel):
    """The four calculators (DTI / LTV / MI / reserves). Cash-to-close is NOT here.

    Each entry is ``None`` when that calculator's output is absent; ``absent`` marks
    the whole section not-built.
    """

    model_config = {"frozen": True}

    dti: CalculationEntry | None = None
    ltv: CalculationEntry | None = None
    mi: CalculationEntry | None = None
    reserves: CalculationEntry | None = None
    absent: bool = False

    @classmethod
    def present(
        cls,
        *,
        dti: CalculationEntry | None = None,
        ltv: CalculationEntry | None = None,
        mi: CalculationEntry | None = None,
        reserves: CalculationEntry | None = None,
    ) -> CalculationsSection:
        return cls(dti=dti, ltv=ltv, mi=mi, reserves=reserves, absent=False)

    @classmethod
    def missing(cls) -> CalculationsSection:
        return cls(absent=True)

    @model_validator(mode="after")
    def _absent_is_empty(self) -> CalculationsSection:
        if self.absent and any((self.dti, self.ltv, self.mi, self.reserves)):
            raise ValueError("an absent CalculationsSection carries no calculators")
        return self

    @property
    def is_present(self) -> bool:
        return not self.absent


class Snapshot(BaseModel):
    """The immutable per-run snapshot — three independent sections + metadata.

    Frozen: a constructed snapshot cannot be mutated (mutation raises). ``mismo`` /
    ``documents`` / ``calculations`` default to present-empty sections. There is no
    field correlating sections — a cross-section link cannot be expressed.
    """

    model_config = {"frozen": True}

    loan_file_id: UUID
    run_id: UUID
    created_at: datetime
    snapshot_version: int = SNAPSHOT_VERSION

    mismo: MismoSection = PydField(default_factory=MismoSection)
    documents: DocumentsSection = PydField(default_factory=DocumentsSection)
    calculations: CalculationsSection = PydField(default_factory=CalculationsSection)
