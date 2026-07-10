"""Frozen per-run snapshot model (LP-204, ADR-241).

The Stage-1 snapshot: one immutable, per-run object that the assemblers
(LP-205/206/207) fill and the AI evaluator later reads. It is deliberately
**raw and un-correlated** — three independent sections with no field anywhere
that joins a document to a MISMO key or a borrower id. Correlation is the
evaluator's job downstream; the snapshot only *records* facts, honestly.

Three sections (built by later tickets, not here):

* ``mismo`` — flat ``key -> Field | PiiField`` (dotted keys like
  ``borrower.1.income.base_monthly``), every value the deterministic MISMO parse
  produced.
* ``documents`` — one :class:`DocumentSnapshot` per processed document:
  ``document_type`` + a nullable ``belongs_to`` (a *raw* borrower name or ``None``
  — a plain string, never a foreign key) + its extracted ``fields``.
* ``calculations`` — ``dti`` / ``ltv`` / ``mi`` / ``reserves``, each a
  :class:`Calculation` (``value`` + a ``breakdown`` whose lines keep their source
  tag) or ``None`` when not computed.

**Design invariants**

* **Frozen.** Every model is ``frozen=True`` + ``extra="forbid"``. Attribute
  reassignment raises. Sequences are ``tuple`` (not ``list``) so they cannot be
  appended to; the section ``dict``\\s are shallow-frozen (Pydantic blocks
  reassigning the attribute, not mutating dict *contents* — see ADR-241).
* **absent != empty.** Carried by the LP-203 primitives: a fact no source supplied
  is :meth:`Field.missing` (or omitted from its dict); a source-supplied blank is a
  present ``Field`` with a null/empty value. Both survive a JSON round-trip
  distinguishably.
* **Structurally un-correlated.** There is no linking/reconciliation field. The
  model *cannot* express "this document's account matches that MISMO asset".

**Naming.** snake_case attributes and snake_case JSON keys — the repo-wide
convention (no camelCase aliasing exists anywhere in the codebase). The phase
plan's ``documentType`` / ``belongsTo`` were illustrative; the implementation
follows the codebase (ADR-241).

Nothing populates or persists this yet (assemblers LP-205-207; persistence LP-209).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, field_validator
from pydantic import Field as PydanticField

from app.verification.snapshot.fields import Field, JsonScalar
from app.verification.snapshot.pii import PiiField

# The snapshot schema version, stamped on every built snapshot. Bump when the
# snapshot *shape* changes (not the PII-hash construction — that versions itself).
SNAPSHOT_SCHEMA_VERSION = 1

# A snapshot fact is either an ordinary field or a masked PII field. The two have
# disjoint key sets (``value`` vs ``display``/``match_hash``) and both
# ``extra="forbid"``, so Pydantic's smart union disambiguates them on parse without
# a discriminator tag — proven by the round-trip tests (ADR-241).
SnapshotField = Field | PiiField

_FROZEN = {"frozen": True, "extra": "forbid"}


def _json_scalar_or_raise(v: object) -> object:
    """Reject a non-JSON-scalar value instead of lossy-coercing it.

    Mirrors :class:`app.verification.snapshot.fields.Field`'s guard (ADR-240): a
    ``Decimal`` (money — DTI/LTV/reserves figures) would otherwise be silently
    floated and lose precision. The contract is that the LP-207 assembler stringifies
    ``Decimal``/``date`` first; enforce it here so a violation fails loudly at the
    calculation value rather than corrupting a figure downstream. (``bool`` is a
    ``JsonScalar`` member and an ``int`` subclass, so it is allowed.)
    """
    if v is not None and not isinstance(v, (str, int, float, bool)):
        raise ValueError(
            f"calculation value must be a JSON scalar (str/int/float/bool) or None, not "
            f"{type(v).__name__} — the assembler must stringify Decimal/date first"
        )
    return v


class CalcSource(StrEnum):
    """Provenance of a single calculation-breakdown line.

    Distinct vocabulary from :class:`FieldSource` (parsed/extracted): a calculation
    line can be a *stated* input, an *extracted* input, a *computed* intermediate,
    or a *manual* override — preserved verbatim from the existing calculators by the
    LP-207 assembler.
    """

    STATED = "stated"
    EXTRACTED = "extracted"
    COMPUTED = "computed"
    MANUAL = "manual"


class CalculationLine(BaseModel):
    """One line of a calculation breakdown: a label, its value, and its source tag."""

    model_config = _FROZEN

    label: str
    value: JsonScalar | None = None
    source: CalcSource | None = None

    @field_validator("value", mode="before")
    @classmethod
    def _value_is_json_scalar(cls, v: object) -> object:
        return _json_scalar_or_raise(v)


class Calculation(BaseModel):
    """A single computed figure plus the breakdown that produced it.

    Deliberately light: the four existing calculators (``services/dti.py``,
    ``ltv.py``, ``mi.py``, ``calculators.py``) own the real line shapes; LP-207 maps
    them into this general form, preserving each line's source tag. This ticket does
    not reimplement any calculation.
    """

    model_config = _FROZEN

    value: JsonScalar | None = None
    breakdown: tuple[CalculationLine, ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def _value_is_json_scalar(cls, v: object) -> object:
        return _json_scalar_or_raise(v)


class Calculations(BaseModel):
    """The four snapshot calculations; any is ``None`` when it was not computed."""

    model_config = _FROZEN

    dti: Calculation | None = None
    ltv: Calculation | None = None
    mi: Calculation | None = None
    reserves: Calculation | None = None


class DocumentSnapshot(BaseModel):
    """One processed document's contribution to the snapshot.

    ``belongs_to`` is a *raw* borrower name or ``None`` — a plain string, never a
    borrower foreign key — so the snapshot records what a document asserts without
    correlating it to a borrower entity (that resolution is a separate, recomputable
    LP-202 artifact the evaluator may consult, not a snapshot fact).
    """

    model_config = _FROZEN

    document_type: str
    belongs_to: str | None = None
    fields: dict[str, SnapshotField] = PydanticField(default_factory=dict)


class Snapshot(BaseModel):
    """The frozen, per-run, three-section loan-file snapshot.

    Rebuilt from scratch each run (LP-208) and, once built, immutable. Serializes to
    and round-trips from JSON (``model_dump_json`` / ``model_validate_json``); UUIDs
    and the timestamp render as strings and parse back.
    """

    model_config = _FROZEN

    loan_file_id: UUID
    run_id: UUID
    created_at: datetime
    snapshot_version: int = SNAPSHOT_SCHEMA_VERSION

    mismo: dict[str, SnapshotField] = PydanticField(default_factory=dict)
    documents: tuple[DocumentSnapshot, ...] = ()
    calculations: Calculations = PydanticField(default_factory=Calculations)
