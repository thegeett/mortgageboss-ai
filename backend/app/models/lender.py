"""Lender model — institutions that loan files are submitted to.

A Lender (e.g., UWM, Sun-West) belongs to a company. Each processing company
configures its own lenders, including contact info for **direct underwriter
communication** (per discovery: processors work directly with underwriters, not
account executives) and (in Phase 3) lender-specific overlay rules.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import LONG_STRING, MEDIUM_STRING, SHORT_STRING, MediumStr, ShortStr

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.loan_file import LoanFile


class LoanProgram(StrEnum):
    """Loan programs supported in V1.

    Reused by lenders (``supported_programs``) and loan files (LP-13).
    Jumbo and others (VA, USDA) are deferred to V2.
    """

    CONVENTIONAL = "conventional"
    FHA = "fha"


class Lender(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A lender configured by a company.

    The slug is unique **per company** (composite unique on ``company_id`` +
    ``slug``), not globally: two different processing companies may each work
    with UWM and each need a lender with slug ``"uwm"`` (ADR-045). Contrast with
    user email, which is globally unique because it is a login identity
    (ADR-042).
    """

    __tablename__ = "lenders"
    __table_args__ = (UniqueConstraint("company_id", "slug", name="uq_lenders_company_id_slug"),)

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    name: Mapped[MediumStr] = mapped_column(nullable=False)
    # Unique per company, not globally — see __table_args__ and ADR-045.
    slug: Mapped[ShortStr] = mapped_column(nullable=False)

    # Contact info — designed for direct underwriter communication.
    contact_email: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    portal_url: Mapped[str | None] = mapped_column(String(LONG_STRING), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(LONG_STRING), nullable=True)

    # Configuration. lender_overlays is structured in Phase 3 (empty for now);
    # supported_programs holds LoanProgram values, e.g. ["conventional", "fha"]
    # (ADR-046).
    lender_overlays: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    supported_programs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Phase 4.5 condition handling (LP-904) -----------------------------
    # Added by Stage 1's migration and UNUSED until Stage 3, except `canonical_lender_key`, which
    # LP-910's code-map seed reads.
    #
    #: ADR-407's consequence, and the answer to a STOP AND ASK. `lenders` is company-scoped with a
    #: slug unique only per company (ADR-045), each company choosing its own — so nothing reliably
    #: identifies "UWM" across tenants and a code-map seed keyed on a slug matches nothing on some
    #: and the wrong row on others. This is the deliberate, admin-set handle the seed matches on.
    #: NULL is not an error: that lender's codes simply arrive as `OBSERVED_UNMAPPED` on first
    #: import, which is the path any unknown code takes anyway.
    canonical_lender_key: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    #: The clause an insurance binder must name, e.g. "United Wholesale Mortgage ISAOA, ATIMA …".
    #: Read off a condition sheet's footer and kept per lender because it is the same on every file.
    #: NOT borrower data — it is the lender's own published mailing identity.
    mortgagee_clause: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: When same-day uploads stop being same-day, e.g. "20:00 America/New_York". A string rather
    #: than a time + tz pair because it is quoted to a processor verbatim and never computed on in
    #: Stage 1; Stage 3's countdown is what would earn the structure.
    condition_upload_cutoff: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    #: Free-form, per lender: which orders they place themselves, which portal quirks to expect.
    #: Prose an admin typed, so it is dropped from the readonly view for the same reason
    #: `lender_contacts.notes` is — free text is where a name arrives in a shape no scrubber predicts.
    condition_handling_notes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )

    # Relationships
    # No destructive cascade: companies are soft-deleted, never hard-deleted, and
    # the company_id FK is ondelete=RESTRICT (ADR-044).
    company: Mapped["Company"] = relationship(back_populates="lenders")
    loan_files: Mapped[list["LoanFile"]] = relationship(back_populates="lender")

    def __repr__(self) -> str:
        return f"<Lender {self.slug} (company={self.company_id})>"
