"""Invitations over the API (LP-MB-Admin-04)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

from app.models.user import UserRole

_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    roles: list[UserRole]


class InvitePublic(BaseModel):
    """One pending invitation on the People page. Never the token or its hash."""

    id: UUID
    email: str
    roles: list[UserRole]
    invited_by_name: str | None
    created_at: datetime
    last_sent_at: datetime
    expires_at: datetime
    send_count: int
    #: Past its expiry: the link no longer works, Resend issues a new one.
    expired: bool


class InviteIssued(BaseModel):
    """A create or resend. ``accept_url`` is set ONLY when no mail transport is configured, so the
    admin can pass the link on; with a transport the link goes by email and is never returned."""

    invite: InvitePublic
    accept_url: str | None


class TokenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str


class InviteLookup(BaseModel):
    """What the person holding the link sees before accepting."""

    company_name: str
    email: str
    roles: list[UserRole]
    invited_by_name: str | None


class InviteAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    first_name: _Name
    last_name: _Name
    password: str
