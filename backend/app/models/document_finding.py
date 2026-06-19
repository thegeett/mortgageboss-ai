"""DocumentFinding model — single-document observations that may affect the loan (LP-66).

A :class:`DocumentFinding` is one **observation** surfaced from a SINGLE document:
something the document *asserts* that may bear on the loan — an obligation
(alimony/child support), a property interest, an income item, a possible
discrepancy. It is recorded **as data** (not just text) and surfaced to the
processor now; it is the feedstock the implications engine (LP-67) and Phase 3's
cross-source verification consume later.

**Uniform across tiers (the point).** The SAME finding shape is produced by the
**Tier 3 generic analyzer** (``key_findings`` for an unrecognized document) AND by
the **Tier 1 divorce-decree** extractor (its support obligations, LP-63) — via one
shared recording mechanism (:func:`app.services.document_findings.create_document_finding`).
So LP-67 + Phase 3 consume findings identically regardless of which tier surfaced
them.

**Distinct from :class:`app.models.finding.Finding`.** That model is the Phase 3
*verification result* (a rule's red/yellow/green flag against the whole loan file,
with a resolution trail). A ``DocumentFinding`` is an *input observation* from one
document; Phase 3 reads these and may *produce* a verification ``Finding``. Two
different things — hence two models / two tables (``document_findings`` vs
``findings``).

**Tenant-scoped transitively** (ADR-052): a finding belongs to its source
``document`` (FK ``ondelete=CASCADE``) and has no ``company_id`` of its own — it is
company-scoped through ``document -> loan_file -> company``.
"""

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import SHORT_STRING

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentFindingType(StrEnum):
    """What kind of observation a finding is (a small, refine-with-Priya set).

    Flexible enough to cover what a document asserts; ``OTHER`` is the catch-all so
    the generic analyzer never has to force a novel observation into a wrong slot.
    """

    OBLIGATION = "obligation"  # a recurring debt (alimony, child support, ...)
    PROPERTY_INTEREST = "property_interest"  # an interest in / award of property
    INCOME_RELATED = "income_related"  # an income item / source
    DISCREPANCY_CANDIDATE = "discrepancy_candidate"  # something that may not match elsewhere
    OTHER = "other"


class DocumentFindingStatus(StrEnum):
    """Where a finding is in the human-in-the-loop lifecycle (refined in Phase 3)."""

    OPEN = "open"  # surfaced, not yet triaged
    REVIEWED = "reviewed"  # a processor looked at it
    DISMISSED = "dismissed"  # not relevant to this loan


class DocumentFinding(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One structured observation surfaced from a single document (LP-66)."""

    __tablename__ = "document_findings"

    # --- Source linkage (tenant-scoped via document -> loan_file -> company) -- #
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- What was observed -------------------------------------------------- #
    finding_type: Mapped[DocumentFindingType] = mapped_column(
        str_enum(DocumentFindingType), index=True, nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)  # human-readable

    # --- Structured-but-flexible details ------------------------------------ #
    # The common typed fields most findings share (an obligation's amount +
    # frequency), plus a flexible JSON catch-all for the varied specifics (a
    # property finding's address, a party, two-value pairs, ...). Findings differ
    # in shape, so the typed fields are nullable and the catch-all carries the rest.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # --- Human-in-the-loop status (default open; Phase 3 resolves) ---------- #
    status: Mapped[DocumentFindingStatus] = mapped_column(
        str_enum(DocumentFindingStatus),
        default=DocumentFindingStatus.OPEN,
        index=True,
        nullable=False,
    )

    # --- Relationships ------------------------------------------------------ #
    document: Mapped["Document"] = relationship()

    def __repr__(self) -> str:
        return f"<DocumentFinding {self.finding_type}/{self.status} document_id={self.document_id}>"
