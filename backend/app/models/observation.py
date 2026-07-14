"""The observation channel + graduation log (LP-320) — safety for the unbounded real world.

§3D "the unbounded real world" + §7 "cross-source discovery lane": when the AI meets a document or
fact NOT in the tag vocabulary (a gift letter, a divorce decree, a trust agreement…), it must NOT
invent a formal tag and must NOT drop the information. It records a STRUCTURED OBSERVATION — a
schemaless envelope that INFORMS a human (and feeds graduation), but NEVER drives an automated
finding resolution. Only governed tags + rules resolve findings; that boundary is what keeps
extensibility from becoming a false-green vector.

Two tables:

* :class:`Observation` — one structured-but-schemaless record of something outside the vocabulary,
  file-owned and append-only. It may ``relate_to`` a finding (fail-closed to human review) but can
  never resolve it — the rule engine does not read this table.
* :class:`GraduationCandidate` — a running, PII-SAFE tally of recurring observation TYPES (by a
  normalized signature). Production frequency ranks which unknowns a human (with Priya) should
  formalize into a tag+rule next. It holds type + count + timestamps ONLY — never raw values — so
  it is safe as a system-wide (cross-file) signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.finding import Finding


class Observation(Base, UUIDMixin, TimestampMixin):
    """A structured, schemaless record of something OUTSIDE the tag vocabulary (§3D / §7).

    Recorded when the AI cannot map a document/fact to a known vocabulary tag — instead of inventing
    a formal tag or dropping the information. It INFORMS: a human sees the structured context, and it
    feeds graduation. It NEVER resolves a finding — ``relates_to_finding_id`` attaches it for human
    review (fail-closed), but the rule engine does not read observations, so one cannot flip a
    verdict. Append-only (file-owned, no soft-delete).
    """

    __tablename__ = "observations"
    __table_args__ = (
        # The two read shapes: a file's observations, and a finding's attached observations
        # (fail-closed review). observation_type is separately indexed for the graduation rollup.
        Index("ix_observations_loan_file", "loan_file_id"),
        Index("ix_observations_relates_to_finding", "relates_to_finding_id"),
        Index("ix_observations_type", "observation_type"),
    )

    # File-owned scoping (like findings — no company_id; the loan file carries the tenant).
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(nullable=False)  # the snapshot run that produced it

    # The document / entity id (a content_id) this observation concerns.
    about: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)
    # A FREE string the AI chose (e.g. "document_purpose", "unusual_credit", "gift_letter_asserted").
    # Deliberately unconstrained — the whole point is facts the vocabulary does NOT enumerate.
    observation_type: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # natural-language what-it-is
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # What it bears on (both nullable): a finding it attaches to (fail-closed review), and/or a
    # subject content_id. relates_to_finding_id is SET NULL on finding delete — the observation
    # OUTLIVES the finding (it is discovery data, not the finding's child).
    relates_to_finding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("findings.id", ondelete="SET NULL"), nullable=True
    )
    relates_to_subject: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    produced_by: Mapped[str] = mapped_column(String(SHORT_STRING), default="ai", nullable=False)
    # Does this look like it should become a formal tag? Drives graduation + fail-closed review.
    needs_tag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    relates_to_finding: Mapped[Finding | None] = relationship()

    def __repr__(self) -> str:
        return (
            f"<Observation {self.observation_type} about={self.about} needs_tag={self.needs_tag}>"
        )


class GraduationCandidate(Base, UUIDMixin, TimestampMixin):
    """A recurring observation TYPE the vocabulary is missing — a PII-safe, ranked-by-frequency tally.

    One row per normalized observation signature; ``occurrences`` counts how often it recurred across
    runs/files. This is the self-improving loop's input: the most frequent candidates are what a
    human (with Priya) formalizes into a tag+rule next. Holds type + signature + count + timestamps
    ONLY — NEVER a raw observation value/reasoning — so it is safe as a system-wide signal across
    tenants. ``created_at`` = first seen, ``updated_at`` = last seen (bumped on each increment).
    """

    __tablename__ = "graduation_candidates"

    # The normalized signature (a canonicalized observation_type) — one candidate per signature.
    signature: Mapped[str] = mapped_column(String(MEDIUM_STRING), unique=True, nullable=False)
    observation_type: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    occurrences: Mapped[int] = mapped_column(default=1, nullable=False)

    def __repr__(self) -> str:
        return f"<GraduationCandidate {self.signature!r} x{self.occurrences}>"
