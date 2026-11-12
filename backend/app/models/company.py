"""Company model — the tenant in our multi-tenant architecture.

A Company is a processing company (the customer). Every piece of business
data ultimately belongs to a company, and users belong to exactly one company.
This is the anchor of tenant isolation: see ``scope_to_company`` in
``app.models.helpers`` and the multi-tenancy section of ``docs/database.md``.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.company_settings import CompanySettings, parse_stored_settings
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import MediumStr, ShortStr

if TYPE_CHECKING:
    from app.models.lender import Lender
    from app.models.loan_file import LoanFile
    from app.models.user import User


class Company(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A processing company (tenant).

    The slug is a stable, human-readable identifier (e.g. ``"acme-mortgage"``)
    and is globally unique. ``settings`` holds per-company configuration as a
    JSON object (empty for now; structured as features land).
    """

    __tablename__ = "companies"

    name: Mapped[MediumStr] = mapped_column(nullable=False)
    slug: Mapped[ShortStr] = mapped_column(unique=True, index=True, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # The owner (ADR-440): one admin, created at onboarding, whom the app refuses to deactivate or
    # demote. Not a role and grants nothing. Nullable only for companies the LP-MB-Admin-01
    # migration found with no active admin; `scripts/transfer_owner` sets those by hand.
    # `use_alter` because `users.company_id` points back here: the FK is added after both tables.
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", use_alter=True), nullable=True
    )

    # Relationships
    # No destructive cascade: companies are soft-deleted, never hard-deleted in
    # normal operation, and the child FKs are ondelete=RESTRICT (ADR-044).
    # `foreign_keys` on both: companies and users are joined by two paths (users.company_id and
    # companies.owner_user_id), and SQLAlchemy will not choose between them.
    users: Mapped[list["User"]] = relationship(
        back_populates="company", foreign_keys="User.company_id"
    )
    # `post_update`: a company and its owner reference each other, so the owner is written by an
    # UPDATE after both rows exist.
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_user_id], post_update=True)
    lenders: Mapped[list["Lender"]] = relationship(back_populates="company")
    loan_files: Mapped[list["LoanFile"]] = relationship(back_populates="company")

    @property
    def settings_model(self) -> CompanySettings:
        """`settings` parsed: a missing key takes its default, an unknown one is kept, and a bad
        value takes its default rather than failing the request (see `parse_stored_settings`)."""
        return parse_stored_settings(self.settings, company_id=self.id)

    def __repr__(self) -> str:
        return f"<Company {self.slug}>"
