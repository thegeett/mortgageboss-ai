"""Live progress for an in-flight verification run (LP-590)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class VerificationProgress(Base):
    """Which phase a running verification is in, visible WHILE it runs.

    ITS OWN TABLE, for two reasons that both matter.

    The run is ONE transaction: `run_rule_engine_pass` opens a single session and commits once at the
    end, so a progress column written on that session would be invisible to a poller until the run
    had already finished. Progress is therefore written from a SEPARATE short-lived session, and a
    separate session must not contend with the run's own row.

    And the run takes `SELECT … FOR UPDATE` on the `verifications` row to decide completion. Writing
    progress there would put a second session in contention with the completion lock at exactly the
    moment the run is trying to finish. A distinct row cannot.

    One row per run, replaced in place as the phase advances. Cascades with the run, so a deleted
    verification takes its progress with it.
    """

    __tablename__ = "verification_progress"

    verification_id: Mapped[UUID] = mapped_column(
        ForeignKey("verifications.id", ondelete="CASCADE"), primary_key=True
    )
    # The machine name of the phase — "build" / "stage_a" / "stage_b" / "rules" / "cross_source".
    # Deliberately the same vocabulary as `Degradation.stage`, so a degradation and a progress entry
    # name the same thing.
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    # Position in the sequence, so a caller can render "3 of 5" without knowing the phase list.
    phase_index: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_total: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
