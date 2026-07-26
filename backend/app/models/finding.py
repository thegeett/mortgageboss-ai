"""Finding model — individual verification results against a loan file (LP-17).

A :class:`Finding` is one flag produced by the verification engine (Phase 3):
**red** (blocking — must be addressed), **yellow** (review / may need a
compensating factor), or **green** (passed). Findings belong to the **loan file**
(a durable parent, ADR-061) so their resolution state — open / resolved /
accepted-risk / waived — *persists across verification runs*: a processor who
accepts a yellow flag as risk does not lose that when verification re-runs.

Each finding records the **rule** that produced it (``rule_id``, a flexible
dotted-namespace string, ADR-062), a human ``message``, structured ``details``
JSON (e.g. stated-vs-verified values), and a **resolution trail** (who resolved
it, when, and why). It references the verification run that produced it
(``verification_id``) and optionally the source document that triggered it.

Like other file-owned children, a finding has no ``company_id`` — it is
company-scoped transitively through its loan file (ADR-052).

``verification_id`` references the verification run that produced the finding.
It was created as a bare nullable UUID in LP-17 (the ``verifications`` table did
not exist yet, ADR-063); **LP-18 added the FK constraint** with
``ondelete=SET NULL`` (ADR-066). SET NULL — not CASCADE — because a finding
belongs to the loan file, not to a run, so deleting a run preserves the finding
and only nulls this reference (ADR-064).
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, MediumStr

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.loan_file import LoanFile
    from app.models.user import User
    from app.models.verification import Verification


class FindingStatus(StrEnum):
    """Severity of a finding (how a processor triages it)."""

    RED = "red"  # blocking — must be addressed
    YELLOW = "yellow"  # review / may need a compensating factor
    GREEN = "green"  # passed check


class FindingCategory(StrEnum):
    """What area of the file a finding concerns."""

    INCOME = "income"
    ASSETS = "assets"
    CREDIT = "credit"
    PROPERTY = "property"
    DOCUMENTATION = "documentation"
    CROSS_SOURCE = "cross_source"  # stated vs verified discrepancies
    REGULATORY = "regulatory"


class FindingResolutionStatus(StrEnum):
    """Where a finding is in its resolution lifecycle.

    The **verification** resolutions (LP-75) are the primary two — a finding must
    reach one of them before the file can submit; nothing is silently ignored:

    * ``APPLIED`` — the finding was *incorporated into the structured data* (e.g.
      an undisclosed obligation added to liabilities), which feeds the
      deterministic recompute (the AI↔deterministic interlock).
    * ``OVERRIDDEN`` — the processor *dismissed it with a recorded reason*
      (stored in ``resolution_note``; required).

    The earlier general-lifecycle states (LP-17) remain for backward
    compatibility and the document-finding flow: ``RESOLVED`` (the underlying
    issue was fixed), ``ACCEPTED_RISK`` (reviewed, proceed with a compensating
    factor), ``WAIVED`` (does not apply). Any non-``OPEN`` state is *resolved* for
    blocking purposes.
    """

    OPEN = "open"
    APPLIED = "applied"
    OVERRIDDEN = "overridden"
    RESOLVED = "resolved"
    ACCEPTED_RISK = "accepted_risk"
    WAIVED = "waived"

    @property
    def is_resolved(self) -> bool:
        """True for any terminal (non-open) state — i.e. not blocking."""
        return self is not FindingResolutionStatus.OPEN


class EvaluationOutcome(StrEnum):
    """What a rule evaluation CONCLUDED for one subject (LP-316) — a NEW, orthogonal axis.

    Distinct from :class:`FindingStatus` (the severity color a processor triages on) and
    :class:`FindingResolutionStatus` (where a human is in resolving it): this records the
    verification OUTCOME itself (§3D's fail-closed states). It maps from LP-315's ``Verdict``
    (fired→open, satisfied→satisfied, needs_review→needs_review, couldnt_check→couldnt_check;
    ``not_applicable`` subjects are not persisted). ``couldnt_check`` now PERSISTS a record —
    "we looked and could not check this, here is why" — where before it left none.
    """

    OPEN = "open"  # fired — a real, unresolved finding needing attention
    SATISFIED = "satisfied"  # the check passes — earned, not assumed (§3D)
    NEEDS_REVIEW = "needs_review"  # degraded/ambiguous — a human must look (LP-314a self_asserted, low-conf, contradiction)
    COULDNT_CHECK = "couldnt_check"  # a load-bearing tag was absent/unknown — fail-closed
    # LP-391 — applicable-but-manual: a BLOCKED rule (uncalibrated / no producer) found something in its
    # scope but is not yet automated. Surfaces to Tab 1 (Needs Attention) as an explicit "manual review —
    # automated check not yet active" — NEVER a trusted pass/fail (its would-be verdict is discarded).
    PENDING_AUTOMATION = "pending_automation"
    NO_LONGER_APPLIES = (
        "no_longer_applies"  # retired across runs (produced by LP-322, not single-run)
    )


class FindingOrigin(StrEnum):
    """Which generator produced a finding (the *two-generator* seam, LP-74).

    Findings flow into one shared model from more than one generator. LP-74's
    deterministic rule engine emits ``DETERMINISTIC_RULE`` findings (a typed
    field compared to a threshold — auditable, no AI). The Phase-3 AI
    cross-source layer (LP-78) feeds the *same* model as ``AI_CROSS_SOURCE``.
    The column lets a reader tell the two apart without the findings path being
    engine-exclusive. ``DOCUMENT_ANALYSIS`` covers the Phase-2 document-level
    findings (LP-66) — so the *three* generators share one shape (LP-75's uniform
    finding), distinguished only by this provenance marker.
    """

    DETERMINISTIC_RULE = "deterministic_rule"
    AI_CROSS_SOURCE = "ai_cross_source"
    DOCUMENT_ANALYSIS = "document_analysis"


class Finding(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A single verification result against a loan file."""

    __tablename__ = "findings"
    __table_args__ = (
        # Confidence is a probability in [0, 1] (LP-75) — guarded at the DB.
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        # A subject is ONE live finding per rule (LP-316). PARTIAL: only among live (non-deleted)
        # findings that HAVE a subject_key — so soft-deleted rows (the current reconcile's retire)
        # and legacy null-subject_key findings do not participate.
        Index(
            "uq_findings_loan_file_rule_subject",
            "loan_file_id",
            "rule_id",
            "subject_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND subject_key IS NOT NULL"),
        ),
    )

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # The verification run that produced this finding (LP-18 wired the FK).
    # SET NULL, not CASCADE: a finding belongs to the loan file, not to a run, so
    # deleting a run preserves the finding and just nulls this reference
    # (ADR-064/ADR-066). Nullable (a finding may predate or outlive a run).
    verification_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("verifications.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # The document that triggered the finding, if any (a finding may be
    # file-level). SET NULL: if the document is removed, the finding remains.
    source_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # ALL documents this finding was derived from (LP-114.1) — a cross-source finding compares
    # across documents, so its provenance is a SET, not one. A JSON array of document-id strings
    # (mirrors needs' source_facts), derived by value-matching the finding's cited value(s) to every
    # document whose extraction contains them (honest by construction — a doc is included only if it
    # genuinely contains the value). ``source_document_id`` above stays as the primary/trigger.
    source_document_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # --- What the rule found -----------------------------------------------
    # Flexible dotted-namespace string (e.g. "income.paystub_recency"), NOT an
    # enum: the rule catalog is large and finalized in Phase 3 (ADR-062).
    rule_id: Mapped[MediumStr] = mapped_column(index=True, nullable=False)
    # Which generator produced this finding (LP-74 two-generator seam). The
    # deterministic rule engine emits ``deterministic_rule``; the AI cross-source
    # layer (LP-78) will feed the same model as ``ai_cross_source``. Defaults to
    # ``deterministic_rule`` so existing/back-filled rows read as engine findings.
    origin: Mapped[FindingOrigin] = mapped_column(
        str_enum(FindingOrigin),
        default=FindingOrigin.DETERMINISTIC_RULE,
        server_default=FindingOrigin.DETERMINISTIC_RULE.value,
        index=True,
        nullable=False,
    )
    status: Mapped[FindingStatus] = mapped_column(
        str_enum(FindingStatus), index=True, nullable=False
    )
    category: Mapped[FindingCategory] = mapped_column(
        str_enum(FindingCategory), index=True, nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured supporting data, e.g. {"stated": 16400, "verified": 14200,
    # "variance_pct": 0.15}. Defaults to an empty dict.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # --- Confidence (LP-75) — the aggression dial's substrate --------------
    # How sure the system is the finding is real, in [0, 1]. Deterministic
    # threshold findings (LP-74) are certain (1.0); AI cross-source findings
    # (LP-78) vary. The dial (LP-79) filters on this; blocking gates on it.
    # Defaults to 1.0 (certain) so a finding without an explicit confidence — the
    # deterministic default — reads as fully trusted.
    confidence: Mapped[float] = mapped_column(
        Float, default=1.0, server_default="1.0", nullable=False
    )

    # --- Source location (LP-75) — the trust/audit anchor (page + snippet) --
    # WHERE the finding came from in the source document: a page number and a
    # VERBATIM snippet of the supporting text. Click a finding → see the exact
    # document line. Builds on extraction's per-field source location (Phase 1).
    # Nullable: a file-level / computed finding may have no single page+snippet.
    # (Bounding-box highlighting is deferred; page + snippet is V1.)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Resolution lifecycle + trail (ADR-060/061) ------------------------
    resolution_status: Mapped[FindingResolutionStatus] = mapped_column(
        str_enum(FindingResolutionStatus),
        default=FindingResolutionStatus.OPEN,
        index=True,
        nullable=False,
    )
    # The recorded reason a finding was resolved. REQUIRED when OVERRIDDEN (LP-75)
    # — the dismissal must be justified (enforced in the resolution service); also
    # the general note for the legacy lifecycle states.
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What an APPLIED finding incorporated into the structured data (LP-75), e.g.
    # {"action": "add_liability", "liability_id": "…", "monthly_payment": "800"}.
    # The record of the structured-data change the apply hook performed (a
    # recompute consumer — LP-76/77/78 — observes the change itself). Null unless
    # APPLIED.
    applied_record: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # SET NULL: the finding's resolution trail survives if the resolving user is
    # removed (the note still records the decision).
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Evaluation outcome + subject identity + provenance (LP-316) --------
    # The NEW outcome axis (open / satisfied / needs_review / couldnt_check / no_longer_applies).
    # Nullable — only tag-rule findings (AS-1) carry it; existing cross-source/document findings
    # leave it null (backward-compatible).
    evaluation_outcome: Mapped[EvaluationOutcome | None] = mapped_column(
        str_enum(EvaluationOutcome), index=True, nullable=True
    )
    # The STABLE per-subject identity: for a per-deposit rule this is the deposit's content_id
    # (LP-312) — never re-extracted amount/date, which drift across runs (§3D: subject_key from
    # stable tag values). Promoted from ``details`` JSON to a column so a subject is one finding
    # (the partial-unique index above). ``details.subject_key`` is still written for the existing
    # ``finding_identity`` reconcile substrate.
    subject_key: Mapped[str | None] = mapped_column(
        String(MEDIUM_STRING), index=True, nullable=True
    )
    # The load-bearing tags the verdict rested on, inline (§3D Move 1 — provenance tag→finding):
    # each ``{tag_id, value, confidence, reasoning, source_facts}``. A human reading the finding
    # sees WHY (e.g. the sourcing tag's "no matching debit, description-only" reasoning), never a
    # bare number. Null on non-tag-rule findings.
    load_bearing_tags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="findings")
    source_document: Mapped["Document | None"] = relationship()
    resolved_by: Mapped["User | None"] = relationship()
    # The run that produced this finding (nullable; SET NULL on run deletion).
    verification: Mapped["Verification | None"] = relationship(back_populates="findings")

    def __repr__(self) -> str:
        return (
            f"<Finding {self.rule_id} {self.status}/{self.resolution_status} "
            f"loan_file_id={self.loan_file_id}>"
        )
