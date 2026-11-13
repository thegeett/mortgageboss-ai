"""Staff invitations (LP-MB-Admin-04).

Admin functions take an :class:`~app.api.dependencies.Actor`, check ``users.manage`` and act in the
actor's company. The two public functions (``lookup_invite``, ``accept_invite``) take only the token.

THE TOKEN. Generated here, handed back to the caller to put in the email (or, with no mail transport,
the admin's copy-link), and stored only as ``hash_token(token)``. It is never logged, never audited
and never written anywhere else. Functions that issue a token return it; the API enqueues the email
AFTER its commit, so the worker cannot look the invite up before the row exists.

AN INVALID LINK SAYS NOTHING. Unknown, expired, revoked, used, and "the address became a user in the
meantime" are all ``None`` to the caller, which the API turns into one 404 sentence.
"""

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AlreadyOnTeam,
    DeactivatedOnTeam,
    ForeignEmail,
    InviteThrottled,
    NoRoles,
    TooManyInvites,
)
from app.core.permissions import Permission
from app.core.security import hash_password, validate_password_strength
from app.core.tokens import generate_token, hash_token
from app.models.base import utcnow
from app.models.user import User, UserRole, UserRoleAssignment
from app.models.user_invite import INVITE_VALID_DAYS, UserInvite
from app.services.authorization import ensure
from app.services.company_audit import AuditAction, log_company_action
from app.services.upload_links import usable_link_origin

if TYPE_CHECKING:
    from app.api.dependencies import Actor

#: A company may have at most this many open invitations at once.
MAX_OPEN_INVITES = 50
#: A link is not (re)sent for the same invitation more often than this.
RESEND_INTERVAL = timedelta(seconds=60)

ROLE_WORDS = {
    UserRole.ADMIN: "Admin",
    UserRole.LOAN_OFFICER: "Loan officer",
    UserRole.PROCESSOR: "Processor",
}


def accept_url(token: str) -> str:
    """The link a person follows. The token is in the FRAGMENT, which a browser never sends to a
    server, so no access log, proxy or referrer ever carries it (ADR-444)."""
    return f"{usable_link_origin()}/accept-invite#{token}"


def roles_in_words(roles: list[str]) -> str:
    return ", ".join(ROLE_WORDS[UserRole(role)] for role in roles)


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _issue(invite: UserInvite) -> str:
    """A new token and a new 7-day window on ``invite``; returns the raw token for the email."""
    token = generate_token()
    now = utcnow()
    invite.token_hash = hash_token(token)
    invite.expires_at = now + timedelta(days=INVITE_VALID_DAYS)
    invite.last_sent_at = now
    invite.send_count = (invite.send_count or 0) + 1
    return token


def _throttle(invite: UserInvite) -> None:
    if utcnow() - invite.last_sent_at < RESEND_INTERVAL:
        raise InviteThrottled()


async def _open_count(db: AsyncSession, company_id: UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(UserInvite)
        .where(
            UserInvite.company_id == company_id,
            UserInvite.accepted_at.is_(None),
            UserInvite.revoked_at.is_(None),
            UserInvite.expires_at > utcnow(),
        )
    )
    return count or 0


async def _audit(
    db: AsyncSession,
    actor_id: UUID | None,
    company_id: UUID,
    action: AuditAction,
    invite: UserInvite | None,
    summary: str,
    detail: dict[str, object],
) -> None:
    await log_company_action(
        db,
        company_id=company_id,
        actor_user_id=actor_id,
        action=action,
        target_type="invite",
        target_id=invite.id if invite is not None else None,
        summary=summary,
        detail=detail,
    )


async def create_invite(
    db: AsyncSession, actor: "Actor", email: str, roles: list[UserRole]
) -> tuple[UserInvite, str, bool]:
    """Invite ``email`` with ``roles``. Returns ``(invite, raw token, created)``.

    ``created`` is False when an open invite for the address already existed and was resent instead
    (the API answers 200 rather than 201). Refusals: ``AlreadyOnTeam``, ``DeactivatedOnTeam``,
    ``ForeignEmail`` (audited, and the caller must commit that row before answering),
    ``TooManyInvites``, ``InviteThrottled``, ``NoRoles``.
    """
    ensure(actor, Permission.USERS_MANAGE)
    address = _normalise_email(email)
    wanted = sorted({UserRole(role).value for role in roles})
    if not wanted:
        raise NoRoles()

    existing_user = await db.scalar(select(User).where(func.lower(User.email) == address))
    if existing_user is not None:
        if existing_user.company_id == actor.company_id:
            raise DeactivatedOnTeam() if not existing_user.is_active else AlreadyOnTeam()
        # Another company's person (ADR-444). Audited WITHOUT that company's name or id.
        await _audit(
            db,
            actor.user.id,
            actor.company_id,
            AuditAction.INVITE_REFUSED_FOREIGN_EMAIL,
            None,
            f"Could not invite {address}: the address is already in use on MortgageBoss",
            {"email": address},
        )
        raise ForeignEmail()

    # The row for this address that is not accepted or revoked (the partial unique index allows at
    # most one), locked so two admins inviting the same person at once do not both write.
    current = await db.scalar(
        select(UserInvite)
        .where(
            UserInvite.company_id == actor.company_id,
            UserInvite.email == address,
            UserInvite.accepted_at.is_(None),
            UserInvite.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if current is not None and current.is_open:
        # Inviting the same address again resends the open invite, under the same throttle.
        _throttle(current)
        token = _issue(current)
        await db.flush()
        await _audit(
            db,
            actor.user.id,
            actor.company_id,
            AuditAction.INVITE_RESENT,
            current,
            f"Resent the invitation to {address}",
            {"email": address, "roles": current.roles},
        )
        return current, token, False

    if await _open_count(db, actor.company_id) >= MAX_OPEN_INVITES:
        raise TooManyInvites()

    invite = current
    if invite is None:
        # A revoked invitation for this address is reused rather than left beside a new one.
        invite = await db.scalar(
            select(UserInvite)
            .where(
                UserInvite.company_id == actor.company_id,
                UserInvite.email == address,
                UserInvite.accepted_at.is_(None),
                UserInvite.revoked_at.is_not(None),
            )
            .order_by(UserInvite.revoked_at.desc())
            .limit(1)
            .with_for_update()
        )
    if invite is None:
        invite = UserInvite(company_id=actor.company_id, email=address, send_count=0)
        db.add(invite)
    else:
        # An expired or revoked row: a fresh invitation in the same row.
        invite.accepted_at = None
        invite.accepted_user_id = None
        invite.revoked_at = None
        invite.send_count = 0
    invite.roles = wanted
    invite.invited_by_user_id = actor.user.id
    token = _issue(invite)
    await db.flush()
    await _audit(
        db,
        actor.user.id,
        actor.company_id,
        AuditAction.INVITE_SENT,
        invite,
        f"Invited {address} as {roles_in_words(wanted)}",
        {"email": address, "roles": wanted},
    )
    return invite, token, True


async def _scoped_invite(db: AsyncSession, actor: "Actor", invite_id: UUID) -> UserInvite | None:
    """An invitation of the actor's company that is still pending (open or expired), locked."""
    invite: UserInvite | None = await db.scalar(
        select(UserInvite)
        .where(
            UserInvite.id == invite_id,
            UserInvite.company_id == actor.company_id,
            UserInvite.accepted_at.is_(None),
            UserInvite.revoked_at.is_(None),
        )
        .with_for_update()
    )
    return invite


async def resend_invite(
    db: AsyncSession, actor: "Actor", invite_id: UUID
) -> tuple[UserInvite, str] | None:
    """A new token and expiry for a pending invitation; the old link stops working.

    ``None`` for another company's, an accepted or a revoked invitation. ``InviteThrottled`` if the
    link was sent less than a minute ago.
    """
    ensure(actor, Permission.USERS_MANAGE)
    invite = await _scoped_invite(db, actor, invite_id)
    if invite is None:
        return None
    _throttle(invite)
    token = _issue(invite)
    await db.flush()
    await _audit(
        db,
        actor.user.id,
        actor.company_id,
        AuditAction.INVITE_RESENT,
        invite,
        f"Resent the invitation to {invite.email}",
        {"email": invite.email, "roles": invite.roles},
    )
    return invite, token


async def revoke_invite(db: AsyncSession, actor: "Actor", invite_id: UUID) -> UserInvite | None:
    """Cancel a pending invitation; its link stops working. ``None`` if there is none to cancel."""
    ensure(actor, Permission.USERS_MANAGE)
    invite = await _scoped_invite(db, actor, invite_id)
    if invite is None:
        return None
    invite.revoked_at = utcnow()
    await db.flush()
    await _audit(
        db,
        actor.user.id,
        actor.company_id,
        AuditAction.INVITE_REVOKED,
        invite,
        f"Cancelled the invitation to {invite.email}",
        {"email": invite.email},
    )
    return invite


async def list_invites(db: AsyncSession, actor: "Actor") -> list[UserInvite]:
    """Pending invitations, open and expired, newest first."""
    ensure(actor, Permission.USERS_MANAGE)
    rows = await db.scalars(
        select(UserInvite)
        .where(
            UserInvite.company_id == actor.company_id,
            UserInvite.accepted_at.is_(None),
            UserInvite.revoked_at.is_(None),
        )
        .order_by(UserInvite.created_at.desc(), UserInvite.id.desc())
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Public: the person holding the link
# --------------------------------------------------------------------------- #


async def lookup_invite(db: AsyncSession, token: str) -> UserInvite | None:
    """The invitation this token opens, if it is open; otherwise ``None``, never why."""
    invite: UserInvite | None = await db.scalar(
        select(UserInvite).where(UserInvite.token_hash == hash_token(token))
    )
    return invite if invite is not None and invite.is_open else None


async def accept_invite(
    db: AsyncSession, token: str, first_name: str, last_name: str, password: str
) -> User | None:
    """Create the person's account from the invitation and mark it accepted, all or nothing.

    ``None`` for any invalid link, and for an address that became a user anywhere since the invite
    was sent. Raises ``PasswordPolicyError`` for a weak password (the only refusal with a reason).

    Atomic inside the caller's transaction: the writes run in a SAVEPOINT, so a failure after the
    user is inserted leaves no user and the invitation open.
    """
    invite: UserInvite | None = await db.scalar(
        select(UserInvite).where(UserInvite.token_hash == hash_token(token)).with_for_update()
    )
    if invite is None or not invite.is_open:
        return None
    validate_password_strength(password)
    taken = await db.scalar(select(User.id).where(func.lower(User.email) == invite.email))
    if taken is not None:
        return None

    async with db.begin_nested():
        user = User(
            company_id=invite.company_id,
            email=invite.email,
            hashed_password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            is_active=True,
            roles=[
                UserRoleAssignment(
                    role=UserRole(role), granted_by_user_id=invite.invited_by_user_id
                )
                for role in invite.roles
            ],
        )
        db.add(user)
        await db.flush()
        invite.accepted_at = utcnow()
        invite.accepted_user_id = user.id
        await db.flush()
        await _audit(
            db,
            user.id,
            invite.company_id,
            AuditAction.INVITE_ACCEPTED,
            invite,
            f"{first_name} {last_name} accepted the invitation",
            {"email": invite.email, "roles": invite.roles},
        )
    return user
