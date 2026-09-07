"""Communication model — messages in and out of a loan file (LP-20).

Records borrower document requests, lender condition responses, and inbound
borrower replies (which arrive via the loan file's inbox token, LP-13) — a single
timeline of everything said and heard about a file. It is the data foundation for
the Phase 4 communication module.

This ticket creates the **record** and a minimal create helper. Email **sending**
and inbound **routing** are Phase 4; here a communication is just persisted state.

LP-809 adds template provenance and the ``communication_needs_items`` join: a DRAFT document
request accumulates needs and regenerates its body from them, which the single ``needs_item_id``
column cannot express. That column is unchanged and still answers "which need was this message
about" for a sent, single-purpose message.

A communication is a separate model from :class:`~app.models.activity_log.
ActivityLog` (ADR-070): it carries message-specific fields (sender/recipient/
subject/body) that an event log doesn't need. A *sent* communication may also
produce an activity-log entry.

Like other file-owned children, a communication has no ``company_id`` — it is
company-scoped transitively through its loan file (ADR-052). The needs-item and
initiating-user links are ``SET NULL`` so the message survives if the referenced
row is removed.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile
    from app.models.needs_item import NeedsItem
    from app.models.user import User


class CommunicationDirection(StrEnum):
    """Whether the message was received by us or sent by us."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CommunicationChannel(StrEnum):
    """The medium of the message.

    V1 is **email only** (enabled by the loan file's inbox token, ADR-072).
    Other channels (phone, SMS, portal) can be added later as new VARCHAR + CHECK
    values without a type migration — listing them now would imply capabilities
    that don't exist yet.
    """

    EMAIL = "email"


class CommunicationStatus(StrEnum):
    """Delivery state. DRAFT/QUEUED/SENT/DELIVERED/FAILED are outbound; RECEIVED inbound."""

    DRAFT = "draft"  # outbound, not yet sent
    # LP-815 — composed and awaiting a transport, with no human left to approve it.
    #
    # NOT `DRAFT`, and the distinction is load-bearing. A draft is the accumulating document request
    # a processor reviews and edits; there is a partial unique index enforcing one open draft per
    # (file, template) and `get_open_draft` reads by that status. An automatic reply parked as a
    # DRAFT would be a second thing on the file waiting for a person who is never asked, and would
    # sit in a state whose whole meaning is "somebody still has to look at this".
    QUEUED = "queued"  # outbound, composed automatically, waiting to be transmitted
    SENT = "sent"  # outbound, sent
    DELIVERED = "delivered"  # outbound, delivery confirmed (if known)
    FAILED = "failed"  # outbound, send failed
    RECEIVED = "received"  # inbound


class Communication(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A message associated with a loan file."""

    __tablename__ = "communications"
    __table_args__ = (
        # LP-809 — ONE OPEN DRAFT PER (FILE, TEMPLATE KIND). Without it, two near-simultaneous
        # requests each find no draft, each create one, and the file holds two half-populated drafts
        # with no basis for choosing between them. Declared here as well as in the migration because
        # the test database is built by `create_all`: a constraint that exists only in the migration
        # is a constraint no test can violate, which is the same as not having one.
        #
        # PARTIAL. A file accumulates hundreds of SENT messages and they must not collide.
        Index(
            "uq_communications_open_draft",
            "loan_file_id",
            "template_key",
            unique=True,
            postgresql_where=text("status = 'draft' AND deleted_at IS NULL"),
            sqlite_where=text("status = 'draft' AND deleted_at IS NULL"),
        ),
    )

    # --- Ownership (owned child of the loan file, ADR-052) -----------------
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- Envelope ----------------------------------------------------------
    direction: Mapped[CommunicationDirection] = mapped_column(
        str_enum(CommunicationDirection), index=True, nullable=False
    )
    channel: Mapped[CommunicationChannel] = mapped_column(
        str_enum(CommunicationChannel),
        default=CommunicationChannel.EMAIL,
        nullable=False,
    )
    status: Mapped[CommunicationStatus] = mapped_column(
        str_enum(CommunicationStatus), index=True, nullable=False
    )
    sender: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Links + provenance ------------------------------------------------
    # The need this message concerns, if any (e.g. a document request). SET NULL:
    # the message survives if the need is removed.
    needs_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("needs_items.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # The user who initiated an outbound message; null for inbound/system. SET NULL.
    initiated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # e.g. an inbound email Message-ID, kept for threading/dedup.
    external_message_id: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)

    # --- Which template produced this body (LP-809) ------------------------
    # `phase4.md` §6 requires the communication record to capture "template + version" alongside the
    # rendered body, because that record is evidence. LP-817 pins each version to a content hash
    # (ADR-401) so a version identifies exactly one set of words — but only if the version that was
    # used is stored. These are that storage.
    #
    # NULL for inbound mail and for anything composed by hand: not every message comes from a
    # template, and a placeholder value would make "which template?" unanswerable in the one case
    # where the honest answer is "none".
    template_key: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="communications")
    needs_item: Mapped["NeedsItem | None"] = relationship()
    initiated_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Communication {self.direction}/{self.status} loan_file_id={self.loan_file_id}>"
