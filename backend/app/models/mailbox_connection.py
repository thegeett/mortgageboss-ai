"""How a company's own mail reaches us (LP-808).

ROUTE B IS FORWARDING, NOT AN API. `phase4.md` §3 settles this for the pilot: a mail routing rule
can only be created inside the customer's own admin console — on Google it would need a *restricted*
scope (`gmail.settings.basic` → CASA), and on Microsoft an inbox rule created through Graph is
blocked by the default external-forward policy anyway. So the honest design is a guided flow with
automatic verification, and this table is what it produces.

BUILT FOR ROUTE C IT DOES NOT YET SERVE. `cursor`, `watch_expires_at` and
`encrypted_refresh_token` are unused by forwarding, and they are here so a Gmail or Graph
integration slots in without a schema migration on a table with live rows. That is the plan's own
instruction and it is the one case where an unused column is the cheaper choice.

STATUS IS STRUCTURED, NOT A BOOLEAN, because the frontend branches on it: "degraded" and
"needs reauthorization" are different sentences to a processor and lead to different actions. And
verification is a SEPARATE axis from health — a connection that has never received anything is not
broken, it is not finished.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.company import Company


class MailboxConnectionKind(StrEnum):
    """How mail gets from the company to us."""

    #: The per-file `lf-<token>@` address. Not a connection anybody configures — listed so the enum
    #: describes every path mail can take rather than only the ones with a row.
    TOKEN_ADDRESS = "token_address"
    #: Route B — an alias at the company's own domain, routed to `co-<token>@` by an admin rule.
    FORWARDED_ALIAS = "forwarded_alias"
    #: Route C, deferred. Present so adding it is a value, not a migration.
    GMAIL_API = "gmail_api"
    GRAPH = "graph"


class MailboxConnectionStatus(StrEnum):
    """Health. Separate from verification — see :class:`MailboxVerification`."""

    CONNECTED = "connected"
    #: Mail is arriving but something is wrong — stale, or failing intermittently.
    DEGRADED = "degraded"
    #: Route C only: the token expired and a person must sign in again.
    NEEDS_REAUTHORIZATION = "needs_reauthorization"
    REVOKED = "revoked"


class MailboxVerification(StrEnum):
    """Whether the routing rule has ever been seen to work.

    A SEPARATE AXIS FROM STATUS, and the distinction is what makes the guided flow honest. A
    connection minted five minutes ago is `NOT_VERIFIED` and perfectly healthy; one that received a
    message last week and nothing since is `VERIFIED` and unhealthy. Collapsing them would make the
    UI say "connected" to somebody whose admin has not created the rule yet.
    """

    NOT_VERIFIED = "not_verified"
    #: The steps were shown or sent; we are waiting for anything to arrive.
    AWAITING_FIRST_MESSAGE = "awaiting_first_message"
    #: Something arrived. Flipped automatically, never by a button.
    VERIFIED = "verified"


#: `co-<token>@<inbox domain>`. The company analogue of `lf-<token>@`, and a bearer credential in
#: exactly the same sense (ADR-397): anyone who can send to it gets their mail into this company's
#: triage queue. 128 bits, matching `inbox_token` for the same reason — it is printed in an admin
#: console, forwarded to whoever administers the mail, and never expires.
CONNECTION_TOKEN_BYTES = 16


class MailboxConnection(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One way a company's mail reaches us."""

    __tablename__ = "mailbox_connections"
    __table_args__ = (
        # The routing lookup, and the only way a forwarded message finds its company. Unique because
        # two connections sharing a token would make that lookup ambiguous, and the tie-break would
        # decide which company's queue a borrower's documents land in.
        Index("uq_mailbox_connections_token", "token", unique=True),
        # FUNCTIONAL, on `lower(token)`. The resolver compares case-insensitively — a relay may
        # rewrite the local part — and `lower(token)` cannot use the plain index above, which is
        # exactly the finding LP-805's review made about `inbox_token`: a sequential scan on the
        # hottest path, which is also the path an attacker probes for free.
        Index("ix_mailbox_connections_token_lower", func.lower(text("token"))),
        Index("ix_mailbox_connections_company_id", "company_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[MailboxConnectionKind] = mapped_column(
        str_enum(MailboxConnectionKind),
        default=MailboxConnectionKind.FORWARDED_ALIAS,
        nullable=False,
    )
    #: The token in `co-<token>@`. Stored in the CLEAR, unlike an upload link's — an admin types this
    #: into a routing rule and a person reads it back to check it, so it has to be recognisable.
    #: Same trade ADR-397 makes for `inbox_token`, and the same consequence: it is a capability.
    token: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    #: The company's own address that forwards here — `docs@herco.com`. Recorded so a processor can
    #: see what they told their admin to route; never used to authenticate anything.
    source_address: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: Which console the steps were rendered for. Free text rather than an enum: it selects help
    #: copy, and a provider we have no steps for is a real answer rather than an error.
    provider: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    status: Mapped[MailboxConnectionStatus] = mapped_column(
        str_enum(MailboxConnectionStatus),
        default=MailboxConnectionStatus.CONNECTED,
        nullable=False,
    )
    verification: Mapped[MailboxVerification] = mapped_column(
        str_enum(MailboxVerification),
        default=MailboxVerification.NOT_VERIFIED,
        nullable=False,
    )

    #: When mail last arrived. THE STALENESS SIGNAL, and the reason it exists: the worst failure on
    #: this path is silent — the rule was removed, nothing errored, and documents stopped arriving.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(nullable=False, default=0)

    # --- Route C, unused by forwarding (see the module docstring) ----------
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship()

    def get_ingest_address(self) -> str:
        """`co-<token>@<inbox domain>` — the address an admin routes mail to.

        THE ONE ACCESSOR, matching `LoanFile.get_inbox_address` and ADR-397's reasoning: the token
        field itself stays out of every response, and the capability is handed over in the one shape
        that is meant to be handed over.
        """
        return f"co-{self.token}@{settings.inbox_domain}"

    def __repr__(self) -> str:
        return f"<MailboxConnection {self.kind} {self.status} company={self.company_id}>"
