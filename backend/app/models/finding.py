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

from sqlalchemy import JSON, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MediumStr

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

    ``ACCEPTED_RISK`` records that a processor reviewed a (typically yellow) flag
    and chose to proceed with a compensating factor; ``WAIVED`` that it does not
    apply; ``RESOLVED`` that the underlying issue was fixed.
    """

    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED_RISK = "accepted_risk"
    WAIVED = "waived"


class FindingOrigin(StrEnum):
    """Which generator produced a finding (the *two-generator* seam, LP-74).

    Findings flow into one shared model from more than one generator. LP-74's
    deterministic rule engine emits ``DETERMINISTIC_RULE`` findings (a typed
    field compared to a threshold — auditable, no AI). The Phase-3 AI
    cross-source layer (LP-78) feeds the *same* model as ``AI_CROSS_SOURCE``.
    The column lets a reader tell the two apart without the findings path being
    engine-exclusive. (LP-75 does the fuller findings-model extension —
    confidence / resolution / blocking; this is the minimal field needed to
    emit in the uniform shape now.)
    """

    DETERMINISTIC_RULE = "deterministic_rule"
    AI_CROSS_SOURCE = "ai_cross_source"


class Finding(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A single verification result against a loan file."""

    __tablename__ = "findings"

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

    # --- Resolution lifecycle + trail (ADR-060/061) ------------------------
    resolution_status: Mapped[FindingResolutionStatus] = mapped_column(
        str_enum(FindingResolutionStatus),
        default=FindingResolutionStatus.OPEN,
        index=True,
        nullable=False,
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SET NULL: the finding's resolution trail survives if the resolving user is
    # removed (the note still records the decision).
    resolved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
