"""Company model — the tenant in our multi-tenant architecture.

A Company is a processing company (the customer). Every piece of business
data ultimately belongs to a company, and users belong to exactly one company.
This is the anchor of tenant isolation: see ``scope_to_company`` in
``app.models.helpers`` and the multi-tenancy section of ``docs/database.md``.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.types import MediumStr, ShortStr

if TYPE_CHECKING:
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

    # Relationships
    # No destructive cascade: companies are soft-deleted, never hard-deleted in
    # normal operation, and the users FK is ondelete=RESTRICT (ADR-044).
    users: Mapped[list["User"]] = relationship(back_populates="company")

    def __repr__(self) -> str:
        return f"<Company {self.slug}>"
