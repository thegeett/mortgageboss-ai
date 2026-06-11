"""User model — a person who uses the system (processor or admin).

Each user belongs to exactly one company. Email is globally unique (ADR-042):
it identifies the user across the whole system and determines their company at
login. Passwords are stored only as hashes (``hashed_password``); the actual
authentication logic arrives in LP-22.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MediumStr, ShortStr

if TYPE_CHECKING:
    from app.models.company import Company


class UserRole(StrEnum):
    """User roles determining permissions.

    PROCESSOR: does loan processing work.
    ADMIN: additionally manages users and lender configuration.
    """

    PROCESSOR = "processor"
    ADMIN = "admin"


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A user of the system, belonging to one company."""

    __tablename__ = "users"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    email: Mapped[MediumStr] = mapped_column(unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[ShortStr] = mapped_column(nullable=False)
    last_name: Mapped[ShortStr] = mapped_column(nullable=False)
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole),
        default=UserRole.PROCESSOR,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="users")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
