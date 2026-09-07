"""What arrived attached to an inbound message (LP-804a).

ONE ROW PER PART THAT LOOKS LIKE A FILE, recorded before anything decides whether it is safe. The
bytes are not copied here — the raw `.eml` in S3 already holds them, and a second copy of a
borrower's document is a second thing to secure, retain and eventually destroy. What this table holds
is the inventory: what it claimed to be, how big it was, and what its bytes hash to.

THE SAFETY COLUMNS ARE PRESENT AND UNFILLED. `sniffed_content_type`, `scan_verdict`, `safety_state`
and `derived_storage_path` are LP-804b's, which sniffs magic bytes, sanitises PDFs and rasterises.
They exist here so that ticket is a service and a backfill rather than a migration on a table with
live rows — and so the DEFAULT is visible: everything starts `PENDING`, which is neither safe nor
unsafe, and nothing downstream may read a `PENDING` attachment as a document.
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.inbound_message import InboundMessage


class AttachmentSafetyState(StrEnum):
    """Whether this part may be treated as a document.

    ``PENDING`` is the default and the only state a freshly parsed attachment can be in. It is
    deliberately NOT a synonym for safe: LP-804b decides, and the malware scan (INFRA-2) is
    asynchronous, so "we have not looked yet" is a state that genuinely persists for a while and
    must not be readable as a pass.
    """

    PENDING = "pending"  # parsed; nothing has examined the bytes
    SAFE = "safe"  # sniffed to an allowed type, sanitised, scanned clean
    QUARANTINED = "quarantined"  # sniffed to something else, or the scan found something
    UNSUPPORTED = "unsupported"  # a real file of a type this product does not accept


class AttachmentDisposition(StrEnum):
    """What a processor did with it."""

    PENDING = "pending"
    ACCEPTED = "accepted"  # became a Document
    REJECTED = "rejected"
    DUPLICATE = "duplicate"  # the same bytes are already on the file


class InboundAttachment(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One attachment on one inbound message.

    A file-owned child in ADR-052's sense — reached only through its message, so it carries no
    ``company_id`` and scopes transitively through whatever routing eventually assigns.
    """

    __tablename__ = "inbound_attachments"
    __table_args__ = (
        # The same file attached twice to one message is one file. Content-addressed rather than
        # keyed on the filename, because a borrower forwarding a thread sends the same PDF under
        # three different names and a processor should be offered it once.
        Index(
            "uq_inbound_attachments_message_sha256",
            "inbound_message_id",
            "sha256",
            unique=True,
        ),
    )

    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )

    #: Exactly what the message called it, decoded but not otherwise touched. Kept because it is
    #: what a processor will recognise, and because a normalisation that loses information cannot be
    #: undone. NEVER LOGGED and never used to build a storage path — it is attacker-controlled text.
    filename_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The safe form: path separators, control characters and leading dots removed.
    filename_normalized: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)

    #: What the MESSAGE claimed. A claim, not a finding — LP-804b sniffs the bytes.
    declared_content_type: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    #: What the BYTES say. Null until LP-804b looks.
    sniffed_content_type: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Content address. The dedup key, and what a malware scan verdict is matched back to.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    #: How deep inside `message/rfc822` wrappers this part was found. 0 is the outer message.
    #: Recorded because a borrower forwarding a thread is the ordinary case, and "the PDF was three
    #: forwards down" is the difference between a parser that works and one that looks like it does.
    nesting_depth: Mapped[int] = mapped_column(nullable=False, default=0)

    #: GuardDuty's verdict (INFRA-2), verbatim. Null until the scan result arrives.
    scan_verdict: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    safety_state: Mapped[AttachmentSafetyState] = mapped_column(
        str_enum(AttachmentSafetyState),
        default=AttachmentSafetyState.PENDING,
        nullable=False,
    )
    #: Why it was refused, in words a processor can act on. Null when the state is SAFE.
    #:
    #: A STATE WITH NO REASON IS A DEAD END. "Quarantined" tells a processor nothing about whether to
    #: ask the borrower again, ask for a different format, or ask for a password — and those are
    #: three different conversations. This is prose written by US, not by a sender, so it is safe to
    #: display and safe to expose.
    safety_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The rasterised artefact LP-804b produces. The extraction path reads THIS, never the original.
    derived_storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    disposition: Mapped[AttachmentDisposition] = mapped_column(
        str_enum(AttachmentDisposition),
        default=AttachmentDisposition.PENDING,
        nullable=False,
    )
    #: Set when a processor accepts it and it becomes a document on the file.
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    inbound_message: Mapped["InboundMessage"] = relationship()
    document: Mapped["Document | None"] = relationship()

    def __repr__(self) -> str:
        return f"<InboundAttachment {self.safety_state} sha256={self.sha256[:12]}…>"
