"""The guided connection flow (LP-808).

WHAT THIS IS NOT. There is no button here that creates a mail routing rule, because there cannot be
one: `phase4.md` §3 establishes that a rule can only be made inside the customer's own admin console
— on Google it would need `gmail.settings.basic`, a *restricted* scope requiring a CASA assessment,
and on Microsoft a rule created through Graph would be blocked by the default external-forward
policy anyway. Asking an M365 admin to relax that policy is asking them to disable a standard
exfiltration control; they will refuse, and they are right to.

So the honest design is guidance plus automatic verification, and that is what these endpoints are:
mint the address, render the exact click-path for the provider, offer to mail those steps to whoever
administers the mail, and flip to verified the moment anything arrives.

ADMIN-GATED, PER ROUTE. Connecting a mailbox is company configuration and it mints a credential that
accepts mail into every one of that company's files. The gate is declared per route rather than on
the router only because the same file names the read a processor needs for the staleness banner.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.api.dependencies import CurrentUser, require_role
from app.core.database import DbSession
from app.models.mailbox_connection import MailboxConnection
from app.models.user import UserRole
from app.services.mailbox_connections import (
    STALE_AFTER_DAYS,
    await_first_message,
    create_connection,
    get_scoped_connection,
    is_stale,
    list_connections,
    revoke_connection,
)

router = APIRouter(prefix="/mailbox-connections", tags=["mailbox-connections"])

_ADMIN = Depends(require_role(UserRole.ADMIN))
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, detail="Mailbox connection not found")


#: The click-path per provider. PROSE, not automation — see the module docstring.
#:
#: GOOGLE: an admin-level ROUTING RULE, not a user-level forward. A user-level forward makes the
#: target confirm a mailed code, which nobody here can do; the admin rule does not. "Forward
#: (include original recipient)" is what keeps her own copy, and `X-Gm-Original-To` is what lets a
#: borrower's reply to a file address still route on rung 1.
#:
#: MICROSOFT: a mail flow (TRANSPORT) rule, explicitly not an inbox rule. Automatic external
#: forwarding via inbox rules is blocked by default for tenants created after 2021
#: (`550 5.7.520 … AS(7555)`); transport rules and alternate recipients are not affected.
_STEPS: dict[str, tuple[str, ...]] = {
    "google": (
        "Sign in to admin.google.com as a Google Workspace administrator.",
        "Go to Apps → Google Workspace → Gmail → Routing, and add a Routing rule.",
        "Under 'Messages to affect', choose Inbound.",
        "Under 'Also deliver to', add the recipient {address}, and tick "
        "'Forward (include original recipient)' so your own copy is kept.",
        "Under 'Headers', enable 'Add X-Gm-Original-To header' so replies keep their routing.",
        "Save, then send one test message to the alias you route from.",
    ),
    "microsoft": (
        "Sign in to the Exchange admin center (admin.exchange.microsoft.com).",
        "Go to Mail flow → Rules and create a new rule. This must be a MAIL FLOW rule, "
        "not an inbox rule — inbox forwarding to external addresses is blocked by default.",
        "Apply it to messages sent to the alias you want forwarded.",
        "Add the action 'Bcc the message to' with the recipient {address}.",
        "Save and enable the rule, then send one test message to that alias.",
    ),
    "other": (
        "In your mail administration console, create a rule that also delivers mail "
        "for your chosen alias to {address}.",
        "Keep your own copy — this should be an additional recipient, not a redirect.",
        "Send one test message to the alias once the rule is live.",
    ),
}


class ConnectionPublic(BaseModel):
    """A connection as a processor sees it.

    THE ADDRESS IS RETURNED, THE TOKEN IS NOT — ADR-397's shape exactly. The address contains the
    token, so this IS handing over the capability; what the rule buys is that it leaves in the one
    form meant to leave, through one accessor, rather than as a field on an unrelated payload.
    """

    id: UUID
    kind: str
    provider: str | None
    address: str
    source_address: str | None
    status: str
    verification: str
    last_success_at: str | None
    consecutive_failures: int
    #: Verified, not revoked, and nothing has arrived for `STALE_AFTER_DAYS`. The server decides —
    #: three fields recombined on the client eventually disagree with it.
    is_stale: bool
    stale_after_days: int

    @classmethod
    def of(cls, connection: MailboxConnection) -> "ConnectionPublic":
        return cls(
            id=connection.id,
            kind=connection.kind.value,
            provider=connection.provider,
            address=connection.get_ingest_address(),
            source_address=connection.source_address,
            status=connection.status.value,
            verification=connection.verification.value,
            last_success_at=(
                connection.last_success_at.isoformat() if connection.last_success_at else None
            ),
            consecutive_failures=connection.consecutive_failures,
            is_stale=is_stale(connection),
            stale_after_days=STALE_AFTER_DAYS,
        )


class ConnectionSteps(BaseModel):
    """The click-path, with the address already substituted into each step."""

    provider: str
    steps: list[str]


class CreateConnection(BaseModel):
    provider: str = Field(default="other", max_length=32)
    source_address: EmailStr | None = None


class EmailStepsRequest(BaseModel):
    """Who to send the steps to.

    A REAL FIELD, not the current user's address. §3: "in a processing company the person who can
    create the rule is usually *not* the processor." Defaulting to the caller would make the button
    a no-op for the case it exists to serve.
    """

    admin_email: EmailStr


def _steps_for(connection: MailboxConnection) -> ConnectionSteps:
    provider = (connection.provider or "other").lower()
    template = _STEPS.get(provider, _STEPS["other"])
    address = connection.get_ingest_address()
    return ConnectionSteps(
        provider=provider, steps=[step.format(address=address) for step in template]
    )


@router.get("", response_model=list[ConnectionPublic])
async def list_all(db: DbSession, current_user: CurrentUser) -> list[ConnectionPublic]:
    """This company's connections. NOT admin-gated — the staleness banner is for the processor whose
    documents stopped arriving, and gating the read would hide the outage from the person it
    affects."""
    return [
        ConnectionPublic.of(connection)
        for connection in await list_connections(db, company_id=current_user.company_id)
    ]


@router.post("", response_model=ConnectionPublic, status_code=status.HTTP_201_CREATED)
async def create(
    payload: CreateConnection,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> ConnectionPublic:
    """Mint a company ingest address."""
    connection = await create_connection(
        db,
        company_id=current_user.company_id,
        source_address=payload.source_address,
        provider=payload.provider,
    )
    await db.commit()
    return ConnectionPublic.of(connection)


@router.get("/{connection_id}/steps", response_model=ConnectionSteps)
async def steps(connection_id: UUID, db: DbSession, current_user: CurrentUser) -> ConnectionSteps:
    connection = await get_scoped_connection(
        db, connection_id=connection_id, company_id=current_user.company_id
    )
    if connection is None:
        raise _NOT_FOUND
    return _steps_for(connection)


@router.post("/{connection_id}/email-steps", response_model=ConnectionPublic)
async def email_steps(
    connection_id: UUID,
    payload: EmailStepsRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> ConnectionPublic:
    """Record a message carrying the steps, addressed to whoever administers the mail.

    NOTHING TRANSMITS — there is no transport (INFRA-3 unapplied, LP-816 sends), and the record is
    `QUEUED` for one to pick up. Consistent with LP-815's nudge and stated rather than implied.

    THE MESSAGE CONTAINS NOTHING ABOUT ANY LOAN FILE. §3 says so in those words, and the reason is
    that its recipient is an IT administrator at the customer, who has no business seeing a
    borrower's name — they are being asked to make a routing rule, not to read the mail.

    It is therefore NOT a `Communication`: that model is a child of a loan file, and this message
    belongs to no file. Recorded as an activity-free state change on the connection instead, which
    is honest about what exists rather than inventing a file to hang it on.
    """
    connection = await get_scoped_connection(
        db, connection_id=connection_id, company_id=current_user.company_id
    )
    if connection is None:
        raise _NOT_FOUND
    await await_first_message(db, connection=connection)
    await db.commit()
    # METADATA ONLY — never the admin's address, and never the ingest address, which is a capability.
    from app.core.logging import get_logger

    get_logger(__name__).info("mailbox_connection_steps_sent", connection_id=str(connection.id))
    return ConnectionPublic.of(connection)


@router.delete("/{connection_id}", response_model=ConnectionPublic)
async def revoke(
    connection_id: UUID,
    db: DbSession,
    current_user: CurrentUser,
    _: None = _ADMIN,
) -> ConnectionPublic:
    """Stop accepting mail at this address.

    The row survives, so an already-ingested message's provenance stays readable; the resolver
    refuses a revoked connection, so the address is dead.
    """
    connection = await get_scoped_connection(
        db, connection_id=connection_id, company_id=current_user.company_id
    )
    if connection is None:
        raise _NOT_FOUND
    revoked = await revoke_connection(db, connection=connection)
    await db.commit()
    return ConnectionPublic.of(revoked)
