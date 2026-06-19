"""MISMO import record (LP-52) — catch-all storage + audit trail.

One row per MISMO import of a loan file. It is the home for everything the import
produced beyond the typed core:

- **catch_all** — LP-51's everything-else (every non-core MISMO leaf, grouped by
  section) as JSON, so nothing is lost and it's available later without
  re-parsing.
- **parse_warnings** — the needed-now fields that were missing/odd (LP-51).
- **raw_file_path** — a reference to the original MISMO file preserved in the
  storage layer for **audit** (the source-of-truth baseline must be auditable).
  The bytes are stored by the upload path (LP-53/54); this holds the reference.
- **source_format** / **status** — how it arrived and how it landed.

Tenant-scoped **transitively** via the loan file (ADR-053) — no own
``company_id`` — and cascades from the file. It is the audit trail and the
foundation for future re-import / versioning (deferred). PII in the catch-all is
access-controlled (tenant-scoped) and never logged.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import LONG_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class MismoImportStatus(StrEnum):
    """How a MISMO import landed.

    ``COMPLETED`` — parsed and mapped cleanly. ``PARTIAL`` — parsed with warnings
    (some needed-now data missing). ``FAILED`` — could not be used. Small, stable
    set → a CHECK-enum (ADR-037).
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class MismoImport(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A single MISMO import of a loan file — catch-all + audit (LP-52)."""

    __tablename__ = "mismo_imports"

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # "xml" | "html" (LP-51 source_format) — small, but kept a flexible string
    # since it's a parser detail, not a domain enum.
    source_format: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    status: Mapped[MismoImportStatus] = mapped_column(
        str_enum(MismoImportStatus),
        default=MismoImportStatus.COMPLETED,
        nullable=False,
    )

    # LP-51 outputs: the needed-now warnings and the everything-else catch-all.
    parse_warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    catch_all: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

    # Reference to the original MISMO file preserved in the storage layer (audit).
    # The bytes are written by the upload path; this holds the storage path.
    raw_file_path: Mapped[str | None] = mapped_column(String(LONG_STRING), nullable=True)

    loan_file: Mapped[LoanFile] = relationship(back_populates="mismo_imports")
