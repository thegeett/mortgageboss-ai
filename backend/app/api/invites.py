"""Staff invitations (LP-MB-Admin-04).

Two routers. ``router`` is the admin's (``users.manage``): create, list, resend, cancel. ``public_router``
has no authentication: the person holding the link looks it up and accepts it.

THE TOKEN TRAVELS IN REQUEST BODIES, never a path or query string, so it reaches no access log; the
emailed link carries it in the URL fragment, which a browser never sends (ADR-444). Every invalid-link
case answers the same 404 sentence.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.auth import issue_session
from app.api.dependencies import CurrentActor, require_permission
from app.core.database import DbSession
from app.core.errors import ForeignEmail
from app.core.permissions import Permission
from app.core.security import PasswordPolicyError
from app.models.base import utcnow
from app.models.company import Company
from app.models.user import User
from app.models.user_invite import UserInvite
from app.schemas.auth import TokenResponse
from app.schemas.invites import (
    InviteAccept,
    InviteCreate,
    InviteIssued,
    InviteLookup,
    InvitePublic,
    TokenBody,
)
from app.services import invites as service
from app.services.mail_sender import get_mail_sender
from app.services.override_attribution import resolve_user_names
from app.tasks.invites import send_invite_email

router = APIRouter(
    prefix="/invites",
    tags=["invites"],
    dependencies=[Depends(require_permission(Permission.USERS_MANAGE))],
)
public_router = APIRouter(prefix="/invites", tags=["invites"])

INVALID = "This invitation is no longer valid"
_INVALID = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INVALID)


async def _public(db: DbSession, invites: list[UserInvite]) -> list[InvitePublic]:
    names = await resolve_user_names(
        db, {i.invited_by_user_id for i in invites if i.invited_by_user_id is not None}
    )
    now = utcnow()
    return [
        InvitePublic(
            id=i.id,
            email=i.email,
            roles=i.roles,  # type: ignore[arg-type]
            invited_by_name=names.get(i.invited_by_user_id) if i.invited_by_user_id else None,
            created_at=i.created_at,
            last_sent_at=i.last_sent_at,
            expires_at=i.expires_at,
            send_count=i.send_count,
            expired=i.expires_at <= now,
        )
        for i in invites
    ]


async def _issued(db: DbSession, invite: UserInvite, token: str) -> InviteIssued:
    """Commit, then hand the email to the worker (it must find the committed row)."""
    await db.commit()
    sender = get_mail_sender()
    if sender is not None:
        send_invite_email.delay(str(invite.id), token)
    [view] = await _public(db, [invite])
    return InviteIssued(invite=view, accept_url=None if sender else service.accept_url(token))


@router.post("", response_model=InviteIssued, status_code=status.HTTP_201_CREATED)
async def create(
    payload: InviteCreate, db: DbSession, actor: CurrentActor, response: Response
) -> InviteIssued:
    """Invite a person. 201 for a new invitation; 200 when an open one existed and was resent."""
    try:
        invite, token, created = await service.create_invite(
            db, actor, str(payload.email), payload.roles
        )
    except ForeignEmail:
        await db.commit()  # the refusal's audit row is kept (ADR-444)
        raise
    if not created:
        response.status_code = status.HTTP_200_OK
    return await _issued(db, invite, token)


@router.get("", response_model=list[InvitePublic])
async def list_pending(db: DbSession, actor: CurrentActor) -> list[InvitePublic]:
    """Pending invitations, open and expired, newest first."""
    return await _public(db, await service.list_invites(db, actor))


@router.post("/{invite_id}/resend", response_model=InviteIssued)
async def resend(invite_id: UUID, db: DbSession, actor: CurrentActor) -> InviteIssued:
    """A new link and a new 7 days; the old link stops working."""
    issued = await service.resend_invite(db, actor, invite_id)
    if issued is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return await _issued(db, *issued)


@router.post("/{invite_id}/revoke", response_model=InvitePublic)
async def revoke(invite_id: UUID, db: DbSession, actor: CurrentActor) -> InvitePublic:
    """Cancel the invitation; its link stops working."""
    invite = await service.revoke_invite(db, actor, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    await db.commit()
    [view] = await _public(db, [invite])
    return view


@public_router.post("/lookup", response_model=InviteLookup)
async def lookup(payload: TokenBody, db: DbSession) -> InviteLookup:
    """What the link is for. Any link that does not work is the same 404."""
    invite = await service.lookup_invite(db, payload.token)
    if invite is None:
        raise _INVALID
    company = await db.get(Company, invite.company_id)
    names = await resolve_user_names(
        db, {invite.invited_by_user_id} if invite.invited_by_user_id else set()
    )
    return InviteLookup(
        company_name=company.name if company else "",
        email=invite.email,
        roles=invite.roles,  # type: ignore[arg-type]
        invited_by_name=names.get(invite.invited_by_user_id) if invite.invited_by_user_id else None,
    )


@public_router.post("/accept", response_model=TokenResponse)
async def accept(payload: InviteAccept, db: DbSession, response: Response) -> TokenResponse:
    """Create the account and sign in, as login does. 404 for any link that does not work;
    422 only for a weak password or a blank name."""
    try:
        user = await service.accept_invite(
            db, payload.token, payload.first_name, payload.last_name, payload.password
        )
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if user is None:
        raise _INVALID
    await db.commit()
    # Loaded with its company and roles, as `get_user_by_id` loads a signed-in user.
    signed_in = await db.scalar(
        select(User).where(User.id == user.id).options(selectinload(User.company))
    )
    assert signed_in is not None
    return issue_session(response, signed_in)
