"""NeedsItem model — outstanding requirements on a loan file (LP-19).

A :class:`NeedsItem` is one thing still required to move a file forward — a
document to collect or information to gather. The needs list is the processor's
running checklist answering "what am I still waiting on?" (ADR-067). It is
deliberately a **first-class entity**, not something derived purely from
findings, so a processor can add manual needs and later phases can generate needs
from verification findings (Phase 3), lender conditions (Phase 4.5), or a
file-creation template — see :class:`NeedsItemOrigin`.

A need moves through the LP-68 five-state arrival lifecycle
(:class:`NeedsItemStatus`): ``PENDING`` → ``RECEIVED`` (a matching document
arrived) → ``VERIFIED`` (it passed) | ``REJECTED`` (it failed); any →
``WAIVED``. ``REQUESTED`` (borrower-outreach, LP-19) is an orthogonal pre-existing
state. Orthogonally, a need carries a :class:`NeedsItemDisposition` (the
AI-proposes / processor-confirms lifecycle, LP-68 groundwork for LP-69/70) and a
source-agnostic ``origin`` (floor / suggestion / ai_reasoning / …). When satisfied
it links to the document that fulfilled it (``satisfied_by_document_id``).

Classification mirrors the document model: ``category`` reuses the stable
:class:`~app.models.document.DocumentCategory` enum (DB CHECK), while
``needs_type`` is a flexible app-layer string for the specific item (ADR-068,
mirroring ADR-053). Both ``category`` and the document/borrower links are
optional — a need may be file-level or borrower-specific.

Like other file-owned children, a needs item has no ``company_id`` — it is
company-scoped transitively through its loan file (ADR-052). The borrower and
satisfying-document links are ``SET NULL`` so the durable needs item survives if
the referenced row is removed (ADR-069).
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.document import DocumentCategory  # reused, not redefined (ADR-068)
from app.models.enums import str_enum
from app.models.types import SHORT_STRING, MediumStr

if TYPE_CHECKING:
    from app.models.borrower import Borrower
    from app.models.document import Document
    from app.models.document_finding import DocumentFinding
    from app.models.loan_file import LoanFile


class NeedsItemStatus(StrEnum):
    """Document-arrival lifecycle of a needs item (LP-68).

    The **five locked states** are the arrival/verification spine (deterministic —
    driven by document arrivals + processor actions, NOT AI):

      ``PENDING`` (the file needs this; not yet arrived — the default) →
      ``RECEIVED`` (a matching document arrived, not yet verified) →
      ``VERIFIED`` (the document passed — extraction succeeded; Phase 3 adds
      cross-source rules later) | ``REJECTED`` (a document arrived but failed —
      expired/illegible/wrong; the need is still open, with a reason). Any state →
      ``WAIVED`` (the processor decided it doesn't apply).

    ``REQUESTED`` (LP-19) is preserved as an **orthogonal, pre-existing** state on
    the borrower-outreach axis (the item was asked of the borrower; sending is
    Phase 4) — a need *awaiting arrival* may be ``PENDING`` or ``REQUESTED``, and
    both are satisfiable.
    """

    PENDING = "pending"  # needs this doc; not yet arrived (default)
    REQUESTED = "requested"  # asked of the borrower (LP-19; awaiting arrival)
    RECEIVED = "received"  # a matching doc arrived, not yet verified
    VERIFIED = "verified"  # the doc passed — the need is satisfied
    REJECTED = "rejected"  # a doc arrived but failed; still open, with a reason
    WAIVED = "waived"  # the processor decided it doesn't apply


class NeedsItemOrigin(StrEnum):
    """How the needs item was created — the source-agnostic provenance (LP-68).

    The needs engine HOLDS needs regardless of source. LP-68 wires the deterministic
    ``FLOOR`` (near-certain needs from the stated MISMO data) + ``SUGGESTION`` (from
    LP-67's findings-implications); LP-69 adds ``AI_REASONING`` (holistic AI
    proposals). ``MANUAL`` is a processor-added need; ``FINDING``/``CONDITION``/
    ``TEMPLATE`` are earlier-defined origins later phases populate.
    """

    MANUAL = "manual"
    FINDING = "finding"  # generated from a verification finding (Phase 3)
    CONDITION = "condition"  # generated from a lender condition (Phase 4.5)
    TEMPLATE = "template"  # generated from a file-creation template
    FLOOR = "floor"  # the deterministic floor, from the stated MISMO data (LP-68)
    SUGGESTION = "suggestion"  # ingested from an LP-67 finding-implication suggestion
    AI_REASONING = "ai_reasoning"  # an LP-69 holistic AI proposal


class NeedsItemDisposition(StrEnum):
    """The human-confirmation lifecycle (LP-68 groundwork for LP-69/70).

    Orthogonal to :class:`NeedsItemStatus` (the arrival lifecycle): disposition is
    "is this a real need?" — AI proposes (LP-69), the processor confirms/dismisses
    (LP-70). The deterministic floor is ``CONFIRMED`` (near-certain); a suggestion /
    AI proposal starts ``PROPOSED``.
    """

    PROPOSED = "proposed"  # surfaced (e.g. by AI), awaiting a processor decision
    CONFIRMED = "confirmed"  # a real need (the floor, or processor-confirmed)
    WAIVED = "waived"  # the processor waived it (mirrors the WAIVED status)
    DISMISSED = "dismissed"  # the processor judged the proposal not a real need


class NeedsItemPriority(StrEnum):
    """Triage priority of a needs item."""

    BLOCKING = "blocking"
    STANDARD = "standard"
    LOW = "low"


class NeedsItem(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """An outstanding requirement on a loan file."""

    __tablename__ = "needs_items"

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- What is needed ----------------------------------------------------
    title: Mapped[MediumStr] = mapped_column(nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reused DocumentCategory enum (ADR-068) so the needs list groups like the
    # document list. Nullable — a need may be uncategorized.
    category: Mapped[DocumentCategory | None] = mapped_column(
        str_enum(DocumentCategory), nullable=True
    )
    # Flexible app-layer string (e.g. "w2", "loe_large_deposit"), not an enum —
    # mirrors document_type (ADR-053). Indexed for filtering.
    needs_type: Mapped[str | None] = mapped_column(String(SHORT_STRING), index=True, nullable=True)

    # Optional target borrower — many needs are borrower-provided; some are
    # file-level. SET NULL: the need survives if the borrower row is removed.
    borrower_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("borrowers.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # --- Classification of the item itself ---------------------------------
    origin: Mapped[NeedsItemOrigin] = mapped_column(
        str_enum(NeedsItemOrigin),
        default=NeedsItemOrigin.MANUAL,
        nullable=False,
    )
    priority: Mapped[NeedsItemPriority] = mapped_column(
        str_enum(NeedsItemPriority),
        default=NeedsItemPriority.STANDARD,
        index=True,
        nullable=False,
    )
    status: Mapped[NeedsItemStatus] = mapped_column(
        str_enum(NeedsItemStatus),
        default=NeedsItemStatus.PENDING,
        index=True,
        nullable=False,
    )
    # The human-confirmation lifecycle (LP-68 groundwork for LP-69/70), orthogonal
    # to ``status``. Default PROPOSED; the floor sets CONFIRMED.
    disposition: Mapped[NeedsItemDisposition] = mapped_column(
        str_enum(NeedsItemDisposition),
        default=NeedsItemDisposition.PROPOSED,
        index=True,
        nullable=False,
    )
    # The "why" — explainability for a suggestion- / AI-derived need (LP-67/69).
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LP-634 — THE PROCESSOR-FACING SENTENCE, separate from `reasoning` above and deliberately so.
    #
    # `reasoning` is the ORIGIN's own record of why the need exists: a floor rule's trigger, the rules
    # that asked for it, or LP-69's argument. It is written for engineers and it is the composer's
    # INPUT. This column is the output — one plain sentence naming the stated fact and what the
    # document settles, in one voice whatever produced the row.
    #
    # Two columns rather than one because the first cut used one, and the composed sentence then fed
    # back in as its own input: the cache key moved every run, the model was re-asked every time, and
    # each answer was composed from the previous answer instead of from the file. Provenance and prose
    # are different things and drift into each other the moment they share a column.
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The SOURCE — the specific data that TRIGGERED the need (LP-110), so the reasoning is
    # FALSIFIABLE (the processor can verify the AI didn't misread). A list of structured facts
    # ``[{"kind", "label", "ref"?}]`` grounding to verifiable data, captured per origin: a FLOOR
    # need derives them DETERMINISTICALLY from the rule ("employment income is stated"); an
    # AI_REASONING need carries the FileContext fact(s) the model CITED (AI-identified — verify);
    # a SUGGESTION need instead uses ``source_finding_id`` (the finding chain below). ``ref`` links
    # to the underlying record (e.g. a finding id) where one exists. NULL = no captured source.
    source_facts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # The source finding for an ingested suggestion (LP-67) → the document-finding
    # it derives from. SET NULL: the durable need survives if the finding is removed.
    source_finding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_findings.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # --- Satisfaction + request trail --------------------------------------
    # The document that fulfilled the need. SET NULL: the need survives if the
    # document is removed (ADR-069); a later phase may re-open it.
    satisfied_by_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    satisfied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The reason a need was REJECTED (doc failed) or WAIVED (doesn't apply).
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Consolidation (LP-111) --------------------------------------------
    # A POSSIBLE-DUPLICATE flag the AI layer sets (never a silent delete): this proposed need looks
    # like a duplicate of ``duplicate_of_id`` — the processor confirms the merge or keeps both. The
    # deterministic layers (collapse-by-source / substance-identity) merge certain duplicates
    # outright; this is only the SEMANTIC residue they can't be sure of. SET NULL so the survivor
    # can be removed without stranding the flag.
    duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("needs_items.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # True once the processor has DISPOSED of a duplicate flag (confirmed the merge or said "keep
    # both") — so the AI flag pass never re-flags a pair the human already judged.
    duplicate_reviewed: Mapped[bool] = mapped_column(default=False, nullable=False)

    # --- Coverage (LP-631) -------------------------------------------------
    # A need is PROVISIONAL when it is written: LP-69 reasons at MISMO import, when the file has no
    # documents by construction, and the ingest path can only ever add. These three columns are how a
    # later pass says "the file already answers this" WITHOUT closing it (ADR-388) — the processor
    # disposes, exactly as they do for the duplicate flag above.
    #
    # Set by any source that reaches that conclusion: a deterministic guideline predicate (LP-632's
    # stated-liability vs credit-report tradelines), or the reasoner withdrawing its own proposal
    # (LP-633). SET NULL so removing the document does not strand the flag.
    covered_by_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # WHY, in words the processor can check against the document — "the credit report lists ALLY
    # FINANCIAL at $438/mo, matching the stated lease payment". A flag saying only "possibly covered"
    # asks them to redo the work the predicate just did.
    coverage_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True once the processor has DISPOSED of a coverage flag (dismissed the need, or kept it) — so no
    # pass re-flags a judgement already made. Mirrors ``duplicate_reviewed``.
    coverage_reviewed: Mapped[bool] = mapped_column(default=False, nullable=False)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="needs_items")
    borrower: Mapped["Borrower | None"] = relationship()
    # Both of these point at ``documents``, so each names its own FK — without that SQLAlchemy
    # cannot tell which column either relationship traverses (LP-631 added the second one).
    satisfied_by_document: Mapped["Document | None"] = relationship(
        foreign_keys=[satisfied_by_document_id]
    )
    # LP-631: the document a coverage flag points at, for display beside the note.
    covered_by_document: Mapped["Document | None"] = relationship(
        foreign_keys=[covered_by_document_id]
    )
    # The finding a SUGGESTION need derives from (LP-67) — LP-110 exposes its provenance
    # (the finding's description + its source document) as the need's source.
    source_finding: Mapped["DocumentFinding | None"] = relationship()

    def __repr__(self) -> str:
        return f"<NeedsItem {self.title!r} {self.status} loan_file_id={self.loan_file_id}>"
