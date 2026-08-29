"""The need-prose cache (LP-634) — the composed reason, keyed by the facts it was composed from."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow


class NeedProse(Base):
    """One cached reason.

    A PURE CACHE, on the same terms as `FindingProse` — no foreign key, no loan file, no run. A row is
    a function of its key alone, so it can be truncated at any time and two files whose stated facts
    coincide share the sentence.

    It exists for DETERMINISM first. Without it an unchanged need is worded differently every run, and
    a processor re-reading the Need List sees movement where nothing moved — on the page they open
    first, which is the page this whole ticket is about.
    """

    __tablename__ = "needs_prose"

    fact_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    why: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
