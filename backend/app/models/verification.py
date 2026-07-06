"""Verification model — one execution of the verification engine (LP-18).

A :class:`Verification` represents a single run ("press of the verify button") of
the verification engine against a loan file — the engine itself is Phase 3. It
**groups** the findings that run produced (one run → many findings) and holds
run-level metadata: status, what triggered it, timing, denormalized summary
counts (red/yellow/green, ADR-065), and optional AI cost.

**Relationship subtlety (ADR-064).** Findings *reference* the run that produced
them (``findings.verification_id``), but findings belong to the **loan file** as
their durable parent — their resolution state persists across runs (ADR-061). So
deleting a run must **not** delete its findings: the FK on
``findings.verification_id`` is ``ondelete=SET NULL``, and the ``findings``
relationship here has **no** destructive cascade. The run itself, by contrast,
*is* an owned child of the loan file (FK ``ondelete=CASCADE``, ADR-052) with no
``company_id`` — scoped transitively through the file.

Run **status** (running/completed/failed) is about the run's own execution and is
entirely separate from a finding's red/yellow/green **status** (ADR-060).
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum

if TYPE_CHECKING:
    from app.models.finding import Finding
    from app.models.loan_file import LoanFile


class VerificationStatus(StrEnum):
    """Status of the verification run itself (not of its findings).

    A run is ``RUNNING`` while the engine works, ``COMPLETED`` when it finishes,
    or ``FAILED`` (reason in ``error_detail``). Distinct from ``FindingStatus``
    (red/yellow/green), which is per finding.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationTrigger(StrEnum):
    """What initiated the run — a processor (``MANUAL``) or the system."""

    MANUAL = "manual"
    AUTOMATIC = "automatic"


class Verification(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One execution of the verification engine against a loan file."""

    __tablename__ = "verifications"

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- Run state ---------------------------------------------------------
    status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus),
        default=VerificationStatus.RUNNING,
        index=True,
        nullable=False,
    )
    trigger: Mapped[VerificationTrigger] = mapped_column(
        str_enum(VerificationTrigger), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Denormalized summary counts (set by the engine, Phase 3 — ADR-065) -
    red_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    yellow_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    green_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- AI cost tracking (if the run used AI-assisted checks) --------------
    total_tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # A stable hash of the verification INPUTS (the stated + verified data the
    # cross-source pass compared), set when a pass completes (LP-78.1). A later
    # "Run verification" whose current inputs hash to the same value returns this
    # run's cached findings WITHOUT re-calling the AI — the back half of the
    # staleness model (don't re-ask the AI when nothing changed). 64-hex SHA-256.
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="verifications")
    # Findings reference this run but are NOT owned by it: NO destructive cascade
    # (ADR-064). They belong to the loan file; deleting a run SET NULLs their
    # verification_id rather than removing them. passive_deletes=True defers that
    # nulling to the database's ON DELETE SET NULL (the FK on findings) instead of
    # the ORM trying to load and null the children itself on parent delete.
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="verification", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Verification {self.status} loan_file_id={self.loan_file_id}>"
