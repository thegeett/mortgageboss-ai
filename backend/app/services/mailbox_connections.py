"""Route B connections, and the third inversion of the tenancy invariant (LP-808).

READ THIS BEFORE THE CODE.

The execution protocol §3.5 named exactly two places allowed to derive ownership from something a
stranger sent: `inbound_routing.resolve_loan_file_by_address` and `upload_links.resolve_link`. It
said a third is a blocking finding, and it said that if a third is ever sanctioned the line must be
amended in the same commit. :func:`resolve_connection_by_address` is that third, the line is amended
in this commit, and this docstring is the argument — offered so a human can reverse it, not to
settle it.

**Route B cannot work without one.** Its whole shape is that a company's admin routes their own
alias to an address we minted for them. Mail arrives at `co-<token>@` with no session and no user,
and the token is the only thing that says whose it is. There is no version of this feature where the
company is known some other way.

**Where it is the same shape as the two that exist**, which is §3.5's stated test:
one function; every failure — unknown token, wrong domain, revoked connection, soft-deleted
row, malformed address — collapsing to one answer; and the resolved row being the only thing that
says whose the data is.

**Where it is WEAKER, stated plainly rather than glossed.** The other two resolve a LOAN FILE, and
§3.5's test says so in those words. This resolves a COMPANY. A wrong answer from the other two
misfiles one message; a wrong answer from this one puts a message in the wrong company's queue
entirely. Two things narrow that and neither removes it:

* The connection decides only the COMPANY. Which FILE the message reaches is still the ladder, and
  the ladder's own rungs are scoped to that company — so the file-level invariant is unchanged and
  what is new is a company-level one.
* The token is 128 bits from `secrets`, matched on both halves of the address including the domain,
  exactly as `inbox_token` is.

**What would make it wrong:** if a fourth appears, or if this one is ever used to derive a company
for anything other than scoping a triage queue and the routing ladder.
"""

from __future__ import annotations

import re
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.base import utcnow
from app.models.helpers import only_active, scope_to_company
from app.models.mailbox_connection import (
    CONNECTION_TOKEN_BYTES,
    MailboxConnection,
    MailboxConnectionKind,
    MailboxConnectionStatus,
    MailboxVerification,
)

logger = get_logger(__name__)

#: `co-<token>@<domain>`. Deliberately the same shape as `lf-<token>@` and deliberately a different
#: prefix: the two resolve to different things, and a resolver that accepted either would make
#: "which kind of address is this" a question answered by whichever lookup happened to hit.
_CONNECTION_LOCAL_PART = re.compile(r"^co-(?P<token>[A-Za-z0-9_-]+)$")

#: No mail for this long means the routing rule is probably gone. `phase4.md` §3 asks for a
#: persistent banner and gives no number; four days is what its own example sentence uses ("no mail
#: received in 4 days"), so it is that rather than a figure invented here.
STALE_AFTER_DAYS = 4


def generate_connection_token() -> str:
    """A fresh company ingest token. 128 bits, matching `inbox_token` (ADR-397)."""
    return secrets.token_urlsafe(CONNECTION_TOKEN_BYTES)


def connection_token_in(address: str | None) -> str | None:
    """The connection token an address carries, or None.

    BOTH HALVES, like `inbox_token_in`. The domain is part of the credential: matching the local part
    alone would let a token lifted from staging resolve against production.
    """
    if not address:
        return None
    candidate = address.strip().strip("<>").lower()
    local, separator, domain = candidate.partition("@")
    if not separator or domain != settings.inbox_domain.lower():
        return None
    found = _CONNECTION_LOCAL_PART.match(local)
    return found.group("token") if found else None


async def resolve_connection_by_address(
    db: AsyncSession, *, address: str | None
) -> MailboxConnection | None:
    """THE THIRD INVERSION. An address in, a live connection or None out.

    Callers read `company_id` off the returned connection; nothing else here produces one. See the
    module docstring for why this exists and where it is weaker than the other two.

    Returns None for an unknown token, a revoked connection, a soft-deleted one, a well-formed
    address on the wrong domain, and a malformed address — deliberately indistinguishable, so the
    response cannot be used to probe which companies exist.
    """
    token = connection_token_in(address)
    if token is None:
        return None

    resolved = (
        await db.execute(
            only_active(
                select(MailboxConnection).where(func.lower(MailboxConnection.token) == token),
                MailboxConnection,
            )
        )
    ).scalar_one_or_none()

    if resolved is None or resolved.status is MailboxConnectionStatus.REVOKED:
        # METADATA ONLY — never the address, which contains the token and is therefore a capability.
        logger.info("inbound_connection_unresolved")
        return None
    return resolved


async def create_connection(
    db: AsyncSession,
    *,
    company_id: UUID,
    source_address: str | None = None,
    provider: str | None = None,
) -> MailboxConnection:
    """Mint a company ingest address. ``flush`` only; the caller commits."""
    connection = MailboxConnection(
        company_id=company_id,
        kind=MailboxConnectionKind.FORWARDED_ALIAS,
        token=generate_connection_token(),
        source_address=source_address,
        provider=provider,
        status=MailboxConnectionStatus.CONNECTED,
        verification=MailboxVerification.NOT_VERIFIED,
    )
    db.add(connection)
    await db.flush()
    # NEVER THE TOKEN OR THE ADDRESS IT BUILDS.
    logger.info("mailbox_connection_created", company_id=str(company_id), provider=provider)
    return connection


async def list_connections(db: AsyncSession, *, company_id: UUID) -> list[MailboxConnection]:
    """A company's connections, newest first."""
    stmt = select(MailboxConnection).order_by(MailboxConnection.created_at.desc())
    stmt = scope_to_company(stmt, MailboxConnection, company_id)
    return list((await db.execute(only_active(stmt, MailboxConnection))).scalars().all())


async def get_scoped_connection(
    db: AsyncSession, *, connection_id: UUID, company_id: UUID
) -> MailboxConnection | None:
    """One connection, only if this company owns it. None otherwise."""
    stmt = select(MailboxConnection).where(MailboxConnection.id == connection_id)
    stmt = scope_to_company(stmt, MailboxConnection, company_id)
    return (await db.execute(only_active(stmt, MailboxConnection))).scalar_one_or_none()


async def await_first_message(
    db: AsyncSession, *, connection: MailboxConnection
) -> MailboxConnection:
    """Move a connection to `AWAITING_FIRST_MESSAGE` once the steps have been handed over.

    NEVER BACKWARDS FROM `VERIFIED`. Re-sending the steps to an admin is an ordinary thing to do on a
    working connection, and a state machine that reset it would make a processor's help request look
    like an outage.
    """
    if connection.verification is MailboxVerification.NOT_VERIFIED:
        connection.verification = MailboxVerification.AWAITING_FIRST_MESSAGE
        await db.flush()
    return connection


async def record_arrival(db: AsyncSession, *, connection: MailboxConnection) -> MailboxConnection:
    """Mail arrived here. Flip to verified and reset the health counters. ``flush`` only.

    VERIFICATION IS AUTOMATIC AND HAS NO BUTTON. `phase4.md` §3: "the moment anything arrives at that
    address we flip it to verified". A button would let somebody mark a connection working before the
    admin had made the rule, and then the banner that exists to catch silence would never fire.

    `DEGRADED` IS CLEARED HERE TOO. A connection that went stale and then received something is
    working again, and leaving the status where it was would keep a banner up that is no longer true
    — which teaches a processor to ignore it.
    """
    connection.verification = MailboxVerification.VERIFIED
    connection.last_success_at = utcnow()
    connection.consecutive_failures = 0
    connection.last_error_code = None
    if connection.status is MailboxConnectionStatus.DEGRADED:
        connection.status = MailboxConnectionStatus.CONNECTED
    await db.flush()
    return connection


async def revoke_connection(
    db: AsyncSession, *, connection: MailboxConnection
) -> MailboxConnection:
    """Stop accepting mail at this address. Idempotent.

    THE ROW STAYS. `resolve_connection_by_address` refuses a revoked connection, so the address is
    dead — and the row is what makes an already-ingested message's provenance readable afterwards.
    """
    connection.status = MailboxConnectionStatus.REVOKED
    await db.flush()
    logger.info("mailbox_connection_revoked", connection_id=str(connection.id))
    return connection


def is_stale(connection: MailboxConnection) -> bool:
    """Whether this connection has gone quiet long enough to be worth a banner.

    ONLY ONCE IT HAS EVER WORKED. A connection that has never received anything is not stale, it is
    unfinished — and saying "no mail received in 4 days" to somebody whose admin has not made the
    rule yet describes a failure that has not happened and hides the one that has.
    """
    from datetime import timedelta

    if connection.verification is not MailboxVerification.VERIFIED:
        return False
    if connection.status is MailboxConnectionStatus.REVOKED:
        return False
    if connection.last_success_at is None:
        return False
    return utcnow() - connection.last_success_at > timedelta(days=STALE_AFTER_DAYS)


__all__ = [
    "STALE_AFTER_DAYS",
    "await_first_message",
    "connection_token_in",
    "create_connection",
    "generate_connection_token",
    "get_scoped_connection",
    "is_stale",
    "list_connections",
    "record_arrival",
    "resolve_connection_by_address",
    "revoke_connection",
]
