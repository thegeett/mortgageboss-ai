"""The fact namespace (LP-118.6) — the assembled, typed, immutable per-run fact object.

Phase 3.5's data-driven engine reads ONE assembled fact object per verification run — the
"fact namespace" — holding everything a rule might read about a loan file, gathered from its
scattered homes (enum columns, stated-entity rows, extraction JSON, on-demand calculators) into
one **entity-addressable** structure, computed once, and persisted as a per-run snapshot. This
module is the SHAPE; :mod:`app.verification.fact_namespace.builder` assembles it.

Design (grounded in ``docs/audits/fact-namespace-foundation.md`` + ADR-239):

* **Immutable + typed.** Frozen Pydantic models (the CrossSourceFacts/FileFacts discipline, plus
  typed JSON round-trip for the snapshot — Decimal stays Decimal, enums stay enums, date stays
  date). Nothing here executes a rule.
* **Entity-addressable, respecting the REAL model shape.** Per-borrower for identity/income/
  employers; **file-level** for liabilities/assets/documents (the audit's uneven addressing —
  liabilities/assets are NOT per-borrower); **single** property; materialized transactions; a
  compute-once ``computed`` block. ``borrowers[].documents[]`` is SHAPED but left empty (the
  borrower↔document linking is LP-118.8).
* **ABSENT ≠ EMPTY ≠ present.** Every slot is a :class:`Fact`. ``absent=True`` means *known to be
  missing* — no data source yet (credit tradelines: no schema), dropped at import (borrower current
  address, property county), or uncomputable (LTV with no appraised value). A ``Fact`` with a value
  is present; an empty ``list`` value with ``absent=False`` means the source exists but has no rows.
  LP-119's awaiting-data honesty depends entirely on this distinction — absent is never zero/empty.
* **None is first-class.** An unset enum column is ``None`` (→ applicability ``UNKNOWN`` later).
* **PII.** SSN is stored MASKED (last-4) only — the snapshot is a persisted record; full SSN stays
  in its encrypted column and is never written here.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

SNAPSHOT_SCHEMA_VERSION = 1


class FactSource(StrEnum):
    """Where a fact came from — provenance for the audit + the trust surface."""

    ENUM = "enum"  # a normalized enum column (program/purpose/occupancy/type)
    STATED = "stated"  # a stated-entity row (MISMO import or manual)
    EXTRACTION = "extraction"  # materialized from a document's extraction JSON
    COMPUTED = "computed"  # a calculator output (compute-once)
    CANONICAL_MAP = "canonical_map"  # canonicalized deterministically via the curated map
    CANONICAL_AI = "canonical_ai"  # canonicalized via the AI fallback (silent-misread risk)
    UNMAPPED = "unmapped"  # canonicalization miss — fallback seam produced no answer
    ABSENT_NO_SCHEMA = "absent_no_schema"  # no extractor/schema produces this yet
    ABSENT_NOT_PERSISTED = "absent_not_persisted"  # parsed at import but dropped (store-everything)
    ABSENT_UNCOMPUTABLE = "absent_uncomputable"  # a calculator's inputs are missing


class Fact[T](BaseModel):
    """One typed fact slot with an explicit present / empty / ABSENT tri-state.

    - **present:** ``value`` is set and ``absent`` is False.
    - **empty:** ``value`` is ``None`` (scalar) or ``[]`` (list) and ``absent`` is False — the
      source exists but yielded nothing (e.g. no assets on file).
    - **ABSENT:** ``absent`` is True — the fact is *known to be missing* (no data source, dropped
      at import, or uncomputable). Never conflate with empty/zero. ``source`` names WHY.
    """

    model_config = ConfigDict(frozen=True)

    value: T | None = None
    absent: bool = False
    source: FactSource | None = None
    # Set for AI-canonicalized values (the silent-misread risk — flagged for the eval set).
    confidence: float | None = None

    @classmethod
    def present(cls, value: T, *, source: FactSource, confidence: float | None = None) -> Fact[T]:
        return cls(value=value, absent=False, source=source, confidence=confidence)

    @classmethod
    def missing(cls, *, source: FactSource) -> Fact[T]:
        """A KNOWN-MISSING fact (absent) — no source, dropped at import, or uncomputable."""
        return cls(value=None, absent=True, source=source)

    @property
    def is_present(self) -> bool:
        return self.value is not None and not self.absent


# --------------------------------------------------------------------------- #
# Entity facts
# --------------------------------------------------------------------------- #


class IncomeItemFacts(BaseModel):
    """One stated income item (per-borrower). ``income_type_canonical`` is the frozen result of
    the build-time canonicalization of the raw string (map → AI-fallback → unmapped)."""

    model_config = ConfigDict(frozen=True)

    monthly_amount: Fact[Decimal]
    income_type_raw: str | None
    income_type_canonical: Fact[str]
    employment_income: bool | None


class EmployerFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str | None
    is_current: bool | None


class DocumentRef(BaseModel):
    """A reference to a document (file-level today). ``borrower_id`` is the slot the LP-118.8
    borrower↔document linking will fill; it stays ``None`` here."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_type: str | None
    present: bool
    current_extraction_id: str | None
    # The document's typed-core extraction values (value-only), materialized so rules/projections
    # can read documented fields (names, addresses, employers) without re-parsing the blob.
    fields: dict[str, str] = {}
    borrower_id: str | None = None  # LP-118.8 fills this; shaped-but-unlinked for now


class BorrowerFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    borrower_id: str
    position: int
    is_primary: bool
    first_name: str | None
    last_name: str | None
    full_name: str | None
    ssn_masked: Fact[str]  # MASKED only — full SSN is never persisted (PII)
    date_of_birth: Fact[date]
    current_address: Fact[str]  # ABSENT — parsed at MISMO import but not persisted (LP-118.7)
    income_items: list[IncomeItemFacts]
    employers: list[EmployerFacts]
    # SHAPED for borrowers[].documents[]; empty until LP-118.8 links documents to borrowers.
    documents: list[DocumentRef]


class PropertyFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    address: Fact[str]
    county: Fact[str]  # ABSENT — parsed at MISMO import but not persisted (LP-118.7)
    occupancy: Fact[str]  # OccupancyType value or None
    property_type: Fact[str]  # PropertyType value or None
    estimated_value: Fact[Decimal]
    purchase_price: Fact[Decimal]
    valuation_amount: Fact[Decimal]


class LiabilityFacts(BaseModel):
    """A stated liability — FILE-level (not attributable to a borrower, per the audit)."""

    model_config = ConfigDict(frozen=True)

    liability_type_raw: str | None
    liability_type_canonical: Fact[str]
    monthly_payment: Fact[Decimal]
    unpaid_balance: Fact[Decimal]
    holder_name: str | None


class AssetFacts(BaseModel):
    """A stated asset — FILE-level. ``is_gift`` is derived from the canonical asset type."""

    model_config = ConfigDict(frozen=True)

    asset_type_raw: str | None
    asset_type_canonical: Fact[str]
    is_gift: bool
    value: Fact[Decimal]
    holder_name: str | None


class TransactionFacts(BaseModel):
    """A bank-statement transaction, MATERIALIZED from the extraction JSON (buried → addressable)."""

    model_config = ConfigDict(frozen=True)

    source_document_id: str
    date: Fact[date]
    amount: Fact[Decimal]
    description: str | None
    transaction_type: str | None


class ComputedFacts(BaseModel):
    """Derived values computed ONCE per run via the existing calculators (compute-once). Each is
    ABSENT when its calculator could not produce a value (missing inputs) — never zero."""

    model_config = ConfigDict(frozen=True)

    ltv: Fact[Decimal]
    cltv: Fact[Decimal]
    hcltv: Fact[Decimal]
    front_end_dti: Fact[Decimal]
    back_end_dti: Fact[Decimal]
    mi_monthly: Fact[Decimal]  # present with value None can mean "MI not required" — see builder
    reserves_months: Fact[Decimal]


class DocumentedFacts(BaseModel):
    """Materialized DOCUMENTED-side aggregates (from extraction JSON) + the known-ABSENT markers
    for data no schema produces yet. Kept separate from the STATED entities so a rule comparing
    stated-vs-documented reads both sides explicitly."""

    model_config = ConfigDict(frozen=True)

    documented_employers: Fact[list[str]]
    documented_income_monthly: Fact[Decimal]  # aggregated where derivable; else absent
    # Known-ABSENT (extractor gaps from LP-116) — distinct from empty so LP-119 → awaiting-data.
    credit_tradelines: Fact[list[str]]  # credit_report has no schema
    documented_loan_amount: Fact[Decimal]  # note / closing disclosure not extracted
    occupancy_evidence: Fact[str]  # appraisal / lease not extracted


class FileFacts(BaseModel):
    """File-level enum + scalar facts (read directly from typed columns; None preserved)."""

    model_config = ConfigDict(frozen=True)

    program: Fact[str]  # LoanProgram value or None
    loan_purpose: Fact[str]  # LoanPurpose value or None
    refinance_type: Fact[str]  # RefinanceType value — the SEPARATE cash-out axis
    loan_amount: Fact[Decimal]
    note_amount: Fact[Decimal]
    note_rate_percent: Fact[Decimal]


class FactNamespace(BaseModel):
    """The assembled, immutable, entity-addressable per-run fact object (LP-118.6).

    This is what LP-119 (applicability), LP-120 (evaluators), and LP-140 (trust surface) will
    read. Persisted verbatim as the run's ``fact_snapshot`` — the auditable "what the engine saw"
    record; the source data stays in its typed homes.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: int = SNAPSHOT_SCHEMA_VERSION
    loan_file_id: str
    file: FileFacts
    borrowers: list[BorrowerFacts]
    property: PropertyFacts | None  # single property per file (uselist=False); None if none
    liabilities: list[LiabilityFacts]
    assets: list[AssetFacts]
    documents: list[DocumentRef]  # file-level; borrower link is LP-118.8
    transactions: list[TransactionFacts]
    computed: ComputedFacts
    documented: DocumentedFacts
