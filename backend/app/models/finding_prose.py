"""The finding-prose cache (LP-527) — composed text keyed by the facts it was composed from."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class FindingProse(Base):
    """One cached composition.

    ⚠️ A PURE CACHE — no foreign key, no loan file, no run. A row is a function of its key alone, so it
    can be truncated at any time and two loan files whose facts coincide share the sentence. It exists
    for DETERMINISM first: without it the same unchanged finding is worded differently every run, which
    reads to a processor as though something changed.
    """

    __tablename__ = "finding_prose"

    fact_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
