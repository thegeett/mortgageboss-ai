"""LoanTeamMember — a user who works a loan file (LP-MB-Admin-05, ADR-445).

A file's STAFF, distinct from its correspondents (``loan_file_participants``, LP-805): a team member is
a user of the file's company who works it; a participant is an address that may write to it.

A file-owned child (ADR-052): no ``company_id``; the service checks the user's company against the
file's. Soft-deleted on removal, so the timeline's "removed X" still names a row. At most one live
loan officer per file, and a person holds a slot once (partial unique indexes on live rows).
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum

if TYPE_CHECKING:
    from app.models.user import User


class TeamRole(StrEnum):
    """A slot on a file's team."""

    LOAN_OFFICER = "loan_officer"
    PROCESSOR = "processor"
    #: Reserved; not offered anywhere yet.
    ASSISTANT = "assistant"


class LoanTeamMember(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One person in one slot on one file."""

    __tablename__ = "loan_teams"
    __table_args__ = (
        Index(
            "uq_loan_teams_member_live",
            "loan_file_id",
            "user_id",
            "team_role",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # One live loan officer per file: two concurrent assignments cannot both win.
        Index(
            "uq_loan_teams_one_loan_officer",
            "loan_file_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND team_role = 'loan_officer'"),
        ),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    team_role: Mapped[TeamRole] = mapped_column(str_enum(TeamRole), nullable=False)
    #: NULL = the system (creation, the backfill).
    added_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="joined")
