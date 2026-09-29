"""A round's package for the lender (LP-925, S3-10): one PDF and one note per ready condition.

`rows` is the package as she sees and edits it — per condition: the file name, the documents merged into
it, the pages, the note (and whether the AI drafted it, code wrote it, or she edited it), and the lender's
extra upload fields. When she marks it submitted, the row set is frozen as the record of what was sent.

The notes restate figures and names from the file (NPI), so no readonly view carries this table.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import str_enum


class PackageStatus(StrEnum):
    BUILT = "built"
    SUBMITTED = "submitted"


class ConditionPackage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "condition_packages"
    __table_args__ = (Index("ix_condition_packages_loan_file_id", "loan_file_id"),)

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[PackageStatus] = mapped_column(
        str_enum(PackageStatus),
        default=PackageStatus.BUILT,
        server_default=PackageStatus.BUILT.value,
        nullable=False,
    )
    #: `[{"condition_id", "code", "file_name"|null, "document_ids", "pages", "note",
    #:   "note_source": ai|code|edited, "fields": {"name_of_source", "date_verified"}, "included"}]`.
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    du_rerun_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
