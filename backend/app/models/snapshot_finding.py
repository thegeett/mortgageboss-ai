"""Snapshot-based AI cross-source findings (LP-586) — persisted, with a STABLE identity."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, utcnow


class SnapshotFinding(Base, UUIDMixin):
    """One cross-source observation the AI made over a snapshot.

    IDENTITY IS CONTENT, NOT A ROW. `finding_key` is a hash of what the finding IS (its kind plus
    the sources it pairs), so the SAME observation on a later run resolves to the same key. That is
    what lets a processor's disposition survive a re-run: without it, dismissing a finding and having
    it return next run is a worse failure than a drifting count, because it trains people to stop
    dismissing anything.

    `snapshot_fingerprint` RECORDS WHICH SNAPSHOT PRODUCED IT — it is not the identity. A finding
    that persists across three snapshots keeps one `finding_key` and updates this column, so "when did
    we last see this" is answerable without inventing a new row each time.

    Tenant-scoped transitively through the loan file (ADR-053), cascading with it.
    """

    __tablename__ = "snapshot_findings"
    __table_args__ = (
        # One row per observation per file — the re-run path UPDATES rather than inserting a twin.
        UniqueConstraint("loan_file_id", "finding_key", name="uq_snapshot_findings_key"),
        Index("ix_snapshot_findings_loan_file", "loan_file_id"),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    # sha256 over (kind + the sorted source references) — see `_finding_key`.
    finding_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # The snapshot this was last observed in. Updated in place on a re-observation.
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    # The sources compared, as [{"label": …, "value": …}] — what makes it CROSS-source and what a
    # processor needs to check it without reopening every document.
    sources: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)

    # OPEN | SIGNED_OFF | NOT_AN_ISSUE — the processor's disposition, keyed to `finding_key` and so
    # carried across re-runs. Deliberately NOT an apply: this pass has no rule spec, no calibrated
    # threshold and no guideline, so it may not write to the loan.
    disposition: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class SnapshotFindingScan(Base):
    """The last snapshot this file's cross-source pass was ASKED about (LP-589).

    The cache decision cannot be derived from the findings themselves, and the first version tried.
    It checked `existing and all(row.fingerprint == current)`, which fails in two ways:

      * a file that genuinely produced NO findings has no rows to carry a fingerprint, so `existing`
        is falsy and it re-asked on every run, forever — the exact case the comment claimed was
        handled;
      * a finding a processor signed off and the model later stopped seeing keeps its OLD
        fingerprint, so `all(...)` never held again and the file re-asked forever after — and since
        the model's answer differs between calls, the tab moved on a file that had not changed.

    One row per loan file, recording what was asked. Zero findings is then a real, cacheable answer.
    """

    __tablename__ = "snapshot_finding_scans"

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), primary_key=True
    )
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
