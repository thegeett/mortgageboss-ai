"""The secure upload link a borrower is sent instead of an email attachment (LP-815).

WHY THIS EXISTS AT ALL, in one sentence from `phase4.md` §6: GLBA Safeguards 16 CFR 314.4(c)(3)
requires customer information to be encrypted in transit over external networks, so **outbound email
must not carry NPI** — it carries an authenticated, expiring link instead. Opportunistic STARTTLS is
not a defensible compensating control on its own.

THE TOKEN IS STORED AS A HASH, AND THAT IS THE DIFFERENCE FROM `inbox_token`. ADR-397 is explicit
that an inbox address is a bearer credential that never expires and is printed, forwarded and quoted
— it has to be, because a borrower types it into their mail client. This one does not: nobody has to
recognise it, so the plaintext exists only in the moment it is minted and in the message it is sent
in. What the database holds cannot be used to reach anything, which means a readonly view, a backup
or a leaked dump is not a way in.

EXPIRING, REVOCABLE, AND SCOPED TO ONE FILE. All three follow from the same reasoning: it is a
capability handed to somebody outside the company, over a channel we do not control, that will end
up in a mailbox we cannot clean.
"""

import hashlib
import secrets
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin, utcnow
from app.models.types import MEDIUM_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile

#: 256 bits. Larger than `inbox_token`'s 128 (ADR-397) for the plain reason that this one appears in
#: a URL, where it is the ONLY thing standing between a stranger and the ability to put a document
#: on a loan file — an inbox address at least requires composing mail to a domain we control.
TOKEN_BYTES = 32

#: Long enough to be useful to somebody who reads their email at the weekend, short enough that a
#: forwarded message does not stay live for a month. `phase4.md` gives no number; this one is stated
#: here rather than inlined so a later decision changes one place.
DEFAULT_TTL_HOURS = 72

#: How many documents one link may deliver before it is spent. A borrower asked for four documents
#: sends four files, often one at a time — a single-use link would be refused on their second
#: attempt and read as broken. Bounded so a leaked link is not an open drop box.
DEFAULT_MAX_USES = 20


def mint_token() -> str:
    """A fresh URL-safe token. Returned ONCE, never stored in this form."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The stored form of a token.

    PLAIN SHA-256, NOT A PASSWORD HASH, and the difference is worth stating because using bcrypt
    here would look more careful and be worse. A password is low-entropy and guessable, so its hash
    must be slow. This token is 256 bits of `secrets`, so it is not guessable at any speed — and it
    is verified on an unauthenticated request, where a deliberately slow hash is a denial-of-service
    lever anyone can pull. Fast and unguessable is the right pair.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class UploadLink(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One expiring capability to add documents to one loan file."""

    __tablename__ = "upload_links"
    __table_args__ = (
        # The lookup on the unauthenticated path, and the only way in. Unique because two links
        # cannot share a hash without one of them being unreachable.
        Index("uq_upload_links_token_hash", "token_hash", unique=True),
        Index("ix_upload_links_loan_file_id", "loan_file_id"),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    #: SHA-256 of the token. THE PLAINTEXT IS NEVER STORED — see the module docstring.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set when a processor withdraws it. Separate from `deleted_at`: revoking is a decision about
    #: the capability, and soft-deleting is a decision about the row.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Who it was sent to, so a processor can see which link went where. Recorded, never used to
    #: authenticate — the token is the credential and requiring the address as well would only make
    #: the link unusable from a different mailbox, which borrowers routinely have.
    recipient_email: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)

    uses: Mapped[int] = mapped_column(nullable=False, default=0)
    max_uses: Mapped[int] = mapped_column(nullable=False, default=DEFAULT_MAX_USES)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Why it was minted, in our own words. Shown to the borrower on the landing page, so it must
    #: never name a person or an address — "Documents for your loan application" and nothing more.
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)

    loan_file: Mapped["LoanFile"] = relationship()

    @property
    def is_spent(self) -> bool:
        return self.uses >= self.max_uses

    def is_usable(self, *, now: datetime | None = None) -> bool:
        """Whether this link may still deliver a document.

        EVERY CONDITION IN ONE PLACE. Spread across the callers, a later endpoint checks three of the
        four and the one it forgets is the one that matters.
        """
        moment = now or utcnow()
        return (
            self.deleted_at is None
            and self.revoked_at is None
            and not self.is_spent
            and self.expires_at > moment
        )

    def __repr__(self) -> str:
        return f"<UploadLink file={self.loan_file_id} expires={self.expires_at.isoformat()}>"
