"""A message that arrived at a loan file's inbox (LP-803).

THE ROW EXISTS BEFORE ANYONE KNOWS WHOSE IT IS. Ingest pulls the raw `.eml` from S3, records what
SES said about it, and stops. Deciding which loan file — and therefore which company — it belongs to
is LP-805's, in the one resolver allowed to derive `company_id` from a resolved loan file. So both
`company_id` and `loan_file_id` are nullable here, and both are filled by routing.

That is a DEPARTURE from the plan's "company-owned", and it is the standing tenancy rule that forces
it: a company id derived anywhere but LP-805's resolver is a blocking finding, and ingest cannot
resolve without becoming that second place. See the ticket doc.

DEDUP, AND WHY IT IS SCOPED THE WAY IT IS. `ingest_key` is
``ses_message_id | normalized Message-ID | sha256(raw)``, and the uniqueness is
``(company_id, ingest_key)`` **NULLS NOT DISTINCT** — so an unrouted message (company_id NULL) still
deduplicates against other unrouted messages, which a plain unique index would not do, because in
SQL two NULLs are never equal and every duplicate would be admitted.

The scope matters for a reason beyond tidiness: `Message-ID` is a header the SENDER writes. Scoped
globally, anyone could suppress another company's message by forging a collision. Scoped per
company, they cannot. The window where that is not yet true is the unrouted set — and it is narrow,
because `ingest_key` prefers the SES message id, which SES assigns and a sender cannot choose. The
header fallback is reached only when there is no SES id at all, which today means the dev injector.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.loan_file import LoanFile


class InboundRoutingState(StrEnum):
    """Where a message stands between arriving and being filed.

    ``PENDING`` is not in `phase4.md`'s list and is added deliberately: the design names the four
    OUTCOMES of routing, and a message that has been ingested but not yet routed is in none of them.
    Reusing ``UNROUTED`` for it would make "routing decided it could not place this" and "routing has
    not looked yet" the same value — and the triage queue is built on exactly that distinction.
    """

    PENDING = "pending"  # ingested; routing has not run
    ROUTED = "routed"  # attached to a loan file
    UNROUTED = "unrouted"  # routing ran and could not place it — goes to triage
    QUARANTINED = "quarantined"  # held: failed authentication, or malware
    REJECTED = "rejected"  # refused outright; not shown as work


class InboundMessage(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One inbound email, as received. The raw bytes live in S3; this is what we know about them."""

    __tablename__ = "inbound_messages"
    __table_args__ = (
        # THE COMPANY IS NOT PART OF A MESSAGE'S IDENTITY, and this index used to say it was.
        #
        # It was `(company_id, ingest_key) NULLS NOT DISTINCT`, which dedups correctly for exactly as
        # long as nothing fills `company_id`. LP-807 wired routing into the ingest task, and routing
        # writes that column — so a redelivery no longer collided with the first copy (which had
        # moved from `(NULL, key)` to `(company, key)`), inserted a second row, and then raised a
        # UniqueViolation when routing tried to move IT to the same place. A redelivered message
        # therefore either duplicated or crashed the task, and SQS delivery is at-least-once by
        # design.
        #
        # LP-803's "the same message delivered twice produces exactly one row" passed throughout,
        # because nothing was routing: the whole test ran in the state where the flaw is invisible.
        #
        # A KEY A LATER STEP REWRITES IS NOT A KEY. `ingest_key` is `ses_message_id` when SES gave
        # one, which it always does on the real path and which is globally unique per delivery — one
        # message delivered to two of our addresses is ONE SES receipt and ONE bucket object, so it
        # is genuinely one row. See `compute_ingest_key` for the fallback and its limit.
        Index("uq_inbound_messages_ingest_key", "ingest_key", unique=True),
        Index("ix_inbound_messages_routing_state", "routing_state"),
    )

    # --- Ownership, filled by routing (LP-805) -----------------------------
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=True
    )
    loan_file_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loan_files.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # --- Identity and dedup ------------------------------------------------
    #: ``ses_message_id | normalized Message-ID | sha256(raw)``. Never null: the third form always
    #: exists, so a message with no usable header is still deduplicated by its bytes.
    ingest_key: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    #: SES's own id for the delivery. Not sender-controlled, which is why it is preferred.
    ses_message_id: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: The `Message-ID` header, normalised. SENDER-CONTROLLED — see the module docstring.
    message_id: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: The `References` header as a list, for threading. LP-818 is the first reader.
    references: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # --- Envelope ----------------------------------------------------------
    from_address: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    to_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Where the raw `.eml` is. The bytes are the record of what arrived; everything else on this row
    #: is derived from them and can be recomputed.
    raw_storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- What SES said about it --------------------------------------------
    #: spf / dkim / dmarc / dmarcPolicy / spam / virus, verbatim from the SES `receipt` object.
    #:
    #: FROM THE RECEIPT, NEVER FROM A HEADER. An `Authentication-Results` header in the message body
    #: is written by whoever sent it and can say anything. The receipt is SES's own finding about the
    #: delivery it accepted, and it is the only trustworthy source of these verdicts.
    #:
    #: Stored VERBATIM, including `GRAY`. Coercing an unknown or intermediate verdict to PASS is how
    #: a message that failed authentication becomes a borrower document.
    auth_verdicts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # --- Routing -----------------------------------------------------------
    routing_state: Mapped[InboundRoutingState] = mapped_column(
        str_enum(InboundRoutingState),
        default=InboundRoutingState.PENDING,
        nullable=False,
    )
    #: What routing matched on — the inbox token, a footer tag, a thread. LP-805 writes it.
    routing_signal: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    routing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Message kind ------------------------------------------------------
    #: A delivery status notification — a bounce. WITHOUT THIS FLAG a bounce files itself as a
    #: borrower document: it is an email, with an attachment, addressed to the file's inbox.
    is_dsn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: An out-of-office or other automatic reply. Never a document, and never worth a reminder.
    is_auto_reply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    company: Mapped["Company | None"] = relationship()
    loan_file: Mapped["LoanFile | None"] = relationship()

    def __repr__(self) -> str:
        return f"<InboundMessage {self.routing_state} ingest_key={self.ingest_key[:16]}…>"
