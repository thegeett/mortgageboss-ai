"""UserInvite — an admin's invitation for a person to join the company (LP-MB-Admin-04).

The emailed link carries a one-time token; only its SHA-256 is stored here (``app.core.tokens``), so a
copy of this table cannot be used to accept anything. One open invite per address per company (a
partial unique index). Expired invites keep their row; inviting the address again reuses it.

"Open" means not accepted, not revoked and not expired: :attr:`UserInvite.is_open`. The database index
can only say the first two, because "now" is not something an index can hold.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, utcnow

#: How long a sent link stays valid.
INVITE_VALID_DAYS = 7


class UserInvite(Base, UUIDMixin, TimestampMixin):
    """One invitation: an address, the roles it will get, and where the link stands."""

    __tablename__ = "user_invites"
    __table_args__ = (
        # One OPEN invite per address per company. Expired rows still count here (an index cannot
        # compare with now), which is why inviting over an expired one reuses its row.
        Index(
            "uq_user_invites_company_id_email_open",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    #: Stored lowercase and stripped.
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Role values (`UserRole`), never empty.
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    #: `hash_token(token)`. The raw token is emailed and never stored.
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: When the link was last (re)issued; the once-a-minute resend throttle reads it.
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    send_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_open(self) -> bool:
        """Not accepted, not revoked, and not past its expiry: the link works."""
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > utcnow()

    @property
    def is_expired(self) -> bool:
        """Not accepted or revoked, but past its expiry: listed as expired, resendable."""
        return self.accepted_at is None and self.revoked_at is None and self.expires_at <= utcnow()
