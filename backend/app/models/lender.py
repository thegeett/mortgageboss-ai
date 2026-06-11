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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import LONG_STRING, MEDIUM_STRING, SHORT_STRING, MediumStr, ShortStr

if TYPE_CHECKING:
    from app.models.company import Company


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

    # Relationships
    # No destructive cascade: companies are soft-deleted, never hard-deleted, and
    # the company_id FK is ondelete=RESTRICT (ADR-044).
    company: Mapped["Company"] = relationship(back_populates="lenders")

    def __repr__(self) -> str:
        return f"<Lender {self.slug} (company={self.company_id})>"
