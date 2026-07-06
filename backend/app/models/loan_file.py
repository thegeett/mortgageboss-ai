"""LoanFile model — the central entity of the system.

Everything in a loan processing engagement hangs off a loan file: borrowers,
properties, documents, extracted data, verification findings, and conditions
all reference it. This model implements the **three-identifier design** from
ADR-036:

  1. ``id`` — UUID primary key (from :class:`UUIDMixin`). Internal only; used
     for foreign keys and joins, never exposed externally.
  2. ``display_id`` — a non-sequential readable code (``LF-XXXX``) for humans
     to reference a file in the UI, conversation, and email subjects. Globally
     unique (ADR-048). An *identifier*: access is gated by auth + company
     scoping, so its predictability is low-risk.
  3. ``inbox_token`` — a cryptographically unguessable token used to build the
     borrower inbox email address. A *capability*: possession grants the
     ability to send documents into the file, so it must be unguessable and is
     never derived from the display ID.

Identifier generation lives in :mod:`app.services.loan_file_ids` and is wired
in by :func:`app.services.loan_files.create_loan_file` (ADR-050); the model
only holds the columns. The status lifecycle is described in ADR-049.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.lender import LoanProgram
from app.models.types import MEDIUM_STRING, SHORT_STRING, Money
from app.verification.confidence import AggressionLevel

if TYPE_CHECKING:
    from app.models.activity_log import ActivityLog
    from app.models.borrower import Borrower
    from app.models.communication import Communication
    from app.models.company import Company
    from app.models.document import Document
    from app.models.finding import Finding
    from app.models.lender import Lender
    from app.models.mismo_import import MismoImport
    from app.models.needs_item import NeedsItem
    from app.models.property import Property
    from app.models.stated_financials import StatedAsset, StatedLiability
    from app.models.verification import Verification

# Domain for the borrower inbox address. A module constant for now; may move to
# settings later if it needs to vary per environment.
INBOX_DOMAIN = "inbox.mortgageboss.ai"


class LoanFileStatus(StrEnum):
    """The loan file lifecycle (ADR-049).

    The happy path runs DRAFT -> IN_PROCESSING -> READY_TO_SUBMIT -> SUBMITTED
    -> IN_CONDITIONS -> CLEAR_TO_CLOSE -> CLOSED. WITHDRAWN is a terminal exit
    that can occur from any earlier state. Transitions are not enforced by a
    state machine in V1 (any-to-any is allowed at the model level); workflow
    enforcement can come later.
    """

    DRAFT = "draft"
    IN_PROCESSING = "in_processing"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTED = "submitted"
    IN_CONDITIONS = "in_conditions"
    CLEAR_TO_CLOSE = "clear_to_close"
    CLOSED = "closed"
    WITHDRAWN = "withdrawn"


class LoanPurpose(StrEnum):
    """Why the loan is being taken out."""

    PURCHASE = "purchase"
    REFINANCE = "refinance"


class RefinanceType(StrEnum):
    """The kind of refinance (LP-77) — drives the LTV denominator + limit.

    A **rate/term** refinance changes the rate/term only and uses LTV limits close
    to a purchase; a **cash-out** refinance pulls equity out and carries a
    **stricter** LTV limit. Null when the loan is a purchase (or the refinance type
    is not yet stated).
    """

    RATE_TERM = "rate_term"
    CASH_OUT = "cash_out"


class AiNeedsStatus(StrEnum):
    """The state of LP-69's AI needs reasoning for this file (LP-71.5 visibility).

    AI reasoning runs as an async Celery task (enqueued at MISMO import); the
    deterministic floor (LP-68) is seeded synchronously and is independent of it.
    This field makes the async reasoning's state **visible** so a floor-only list is
    never silently presented as complete:

      ``PENDING`` (enqueued — more needs may still appear) → ``COMPLETED`` (the
      reasoning ran) | ``FAILED`` (the AI call failed — the list may be incomplete).

    ``None`` means no AI reasoning was triggered for this file (e.g. a manually
    created file). The signal is informational, never blocking — the import and the
    floor succeed regardless.
    """

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class LoanFile(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A single loan file being processed toward underwriting submission.

    Many fields are nullable because a file can be created manually before its
    details are known and filled in later (e.g. from a MISMO import or by the
    processor): ``lender_id``, ``loan_program``, ``loan_purpose``, and
    ``loan_amount`` may all be unset at creation.
    """

    __tablename__ = "loan_files"

    # --- Identifiers (ADR-036) ---------------------------------------------
    # Both are globally unique with a DB constraint as the final safety net.
    # display_id is collision-checked at creation; inbox_token relies on its
    # entropy. Neither is derived from the other.
    display_id: Mapped[str] = mapped_column(
        String(SHORT_STRING), unique=True, index=True, nullable=False
    )
    inbox_token: Mapped[str] = mapped_column(
        String(SHORT_STRING), unique=True, index=True, nullable=False
    )

    # --- Ownership ---------------------------------------------------------
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    # Nullable: the lender may be unassigned when the file is first created.
    lender_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lenders.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )

    # --- Loan attributes (all nullable; may arrive via MISMO/processor) -----
    loan_program: Mapped[LoanProgram | None] = mapped_column(str_enum(LoanProgram), nullable=True)
    loan_purpose: Mapped[LoanPurpose | None] = mapped_column(str_enum(LoanPurpose), nullable=True)
    # The refinance kind (LP-77) — drives the LTV denominator + limit. Null for a
    # purchase (or an as-yet-unstated refinance).
    refinance_type: Mapped[RefinanceType | None] = mapped_column(
        str_enum(RefinanceType), nullable=True
    )
    loan_amount: Mapped[Money | None] = mapped_column(nullable=True)

    # --- MISMO core loan terms (LP-52) — nullable; manual creation leaves empty.
    # (base_loan_amount → loan_amount, mortgage_type → loan_program, loan_purpose
    # already exist; these are the genuinely-missing terms.)
    note_amount: Mapped[Money | None] = mapped_column(nullable=True)
    # Note rate as a percent, e.g. 6.8750 — Numeric(7, 4), exact (never float).
    note_rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    lien_priority: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    amortization_type: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    amortization_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    application_received_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- Lifecycle ---------------------------------------------------------
    status: Mapped[LoanFileStatus] = mapped_column(
        str_enum(LoanFileStatus),
        default=LoanFileStatus.DRAFT,
        nullable=False,
    )

    # --- AI needs reasoning state (LP-71.5) — async, informational ----------
    # PENDING on import-enqueue → COMPLETED / FAILED when the task settles. NULL =
    # no AI reasoning triggered (e.g. a manually created file). Never blocks.
    ai_needs_status: Mapped[AiNeedsStatus | None] = mapped_column(
        str_enum(AiNeedsStatus), nullable=True
    )
    # Whether the cross-source verification is out of date (LP-78). Set True when
    # a document changes (upload / type override / replace) or a finding is
    # applied (the structured data changed); cleared when the cross-source pass
    # re-runs. A visible "re-run verification" indicator; auto-re-run is deferred.
    verification_stale: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # --- Aggression dial (LP-79) — the verification thoroughness for this file --
    # A per-file CONFIDENCE CUTOFF over the already-computed findings (LP-78): a
    # finding is in-scope (shown + blocking) at/above the active cutoff. NULL =
    # use the user's default (a per-file override dials a tricky file up/down). The
    # dial NEVER re-runs the AI and NEVER recolors a finding — it only changes
    # which stored findings are in scope (confidence ≠ severity, orthogonal axes).
    aggression_level_override: Mapped[AggressionLevel | None] = mapped_column(
        str_enum(AggressionLevel, name="aggression_level_override"), nullable=True
    )
    # The active level recorded when the file was marked ready to submit — "cleared
    # at <level> thoroughness" (auditability; "clear" is relative to thoroughness).
    # NULL until the file passes the submit gate.
    submitted_aggression_level: Mapped[AggressionLevel | None] = mapped_column(
        str_enum(AggressionLevel, name="submitted_aggression_level"), nullable=True
    )

    # --- Originating loan officer (free-text; the LO is not a system user) --
    loan_officer_name: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    loan_officer_email: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)

    # --- Relationships -----------------------------------------------------
    # No destructive cascade: company/lender are soft-deleted and the FKs are
    # ondelete=RESTRICT (ADR-044).
    company: Mapped["Company"] = relationship(back_populates="loan_files")
    lender: Mapped["Lender | None"] = relationship(back_populates="loan_files")

    # Borrowers (one-to-many) and the subject property (one-to-one, LP-14). Both
    # are owned by the file (FK ondelete=CASCADE on the child side). Borrowers
    # are ordered by their position so loan_file.borrowers is deterministic.
    # delete-orphan keeps the ORM in step with the DB cascade: removing a child
    # from the collection deletes it.
    borrowers: Mapped[list["Borrower"]] = relationship(
        back_populates="loan_file",
        order_by="Borrower.borrower_position",
        cascade="all, delete-orphan",
    )
    property: Mapped["Property | None"] = relationship(
        back_populates="loan_file",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # Uploaded documents (one-to-many, LP-15) — also an owned child of the file.
    documents: Mapped[list["Document"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    # Verification findings (one-to-many, LP-17) — owned child of the file; their
    # resolution state persists across verification runs (ADR-061).
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    # Verification runs (one-to-many, LP-18) — owned child of the file. (Findings
    # are NOT owned by a run; see Verification.findings / ADR-064.)
    verifications: Mapped[list["Verification"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    # Needs-list items (one-to-many, LP-19) — owned child of the file.
    needs_items: Mapped[list["NeedsItem"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    # Messages and the audit-trail timeline (one-to-many, LP-20) — owned children.
    communications: Mapped[list["Communication"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    # Stated financials carried at the deal level (LP-52) — owned children of the
    # file (DTI back-end / reserves are file-level).
    stated_liabilities: Mapped[list["StatedLiability"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    stated_assets: Mapped[list["StatedAsset"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )
    # MISMO import records (catch-all + audit, LP-52) — owned children of the file.
    mismo_imports: Mapped[list["MismoImport"]] = relationship(
        back_populates="loan_file",
        cascade="all, delete-orphan",
    )

    def get_inbox_address(self) -> str:
        """Return the borrower inbox email address for this file.

        Built from the cryptographic inbox token (ADR-036), e.g.
        ``lf-a7k4nq2x9m3p@inbox.mortgageboss.ai``.
        """
        return f"lf-{self.inbox_token}@{INBOX_DOMAIN}"

    def __repr__(self) -> str:
        return f"<LoanFile {self.display_id} ({self.status})>"
