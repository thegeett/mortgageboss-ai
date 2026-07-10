"""Snapshot record model (LP-209, ADR-246) — the immutable per-run snapshot at rest.

One row per verification run holds the full LP-204 ``Snapshot`` as a single JSONB
blob (``snapshot_json``), NOT shredded into columns. The row is **immutable**:
insert-only, no update path, and — deliberately — **no ``updated_at`` and no
soft-delete** (a ``TimestampMixin`` would add ``updated_at``; a ``SoftDeleteMixin``
would allow a mutating "delete"). Append-only history is what lets a processor jump
back to a previous run's state, so a run's snapshot is never rewritten.

* ``run_id`` is UNIQUE — one snapshot per run. It is a bare UUID, **not** a FK to
  ``verifications``: the builder (LP-208) *receives* ``run_id`` and never mints it
  from a verification row, so no matching row is guaranteed to exist (mirrors how
  ``findings.verification_id`` began as a bare UUID, ADR-063).
* ``loan_file_id`` is an indexed FK to the owning loan file (CASCADE, ADR-052) —
  many runs per file.

Immutability is enforced **in code** (no update method exists; the write path is
insert-only) — the repo has no DB-level append-only trigger/REVOKE pattern to reuse
(ADR-246).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class SnapshotRecord(Base, UUIDMixin):
    """The immutable, per-run persisted snapshot (one JSONB blob)."""

    __tablename__ = "snapshot_records"
    __table_args__ = (UniqueConstraint("run_id", name="uq_snapshot_records_run_id"),)

    # One snapshot per run. Bare UUID (not a FK to verifications — see module docs).
    run_id: Mapped[UUID] = mapped_column(nullable=False)

    # The owning loan file (owned child, CASCADE, ADR-052); many runs per file.
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # When the snapshot was BUILT (the snapshot's own created_at), tz-aware.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The LP-204 schema version the blob follows (readers branch on it).
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # The full snapshot, verbatim, as one JSONB blob (not shredded into columns).
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # No updated_at / deleted_at by design — the row is append-only (LP-209).

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<SnapshotRecord run_id={self.run_id} loan_file_id={self.loan_file_id} "
            f"v{self.snapshot_version}>"
        )
