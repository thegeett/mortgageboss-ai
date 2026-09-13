"""What this deployment can actually do (LP-857).

WHY AN ENDPOINT AND NOT A BUILD-TIME CONSTANT IN THE FRONTEND. The flag has two halves that must
agree: whether the Communication page offers the secure-upload and inbound panels, and whether a
generated request promises a borrower an upload link. The second is decided on the server when the
body is rendered. Two flags with two names, set in two places, would let a deployment hide the panel
and keep the promise — which is the failure this ticket exists to remove, not a new place to
introduce it.

WHAT DOES NOT BELONG HERE. This is what the SERVER can do, not what a user prefers or what a role is
allowed. Preferences live on `/users/me/preferences` and permissions are decided per route; a flag
that started meaning "this user may not" would be an authorisation check in the one place with no
resource to check against.

It is authenticated like everything else. Nothing here is secret — a processor can see the same fact
by looking at the page — but an unauthenticated route is a surface, and this one would exist only to
save a header.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import CurrentUser
from app.core.config import settings

router = APIRouter(tags=["capabilities"])


class Capabilities(BaseModel):
    """The switches a screen has to know about."""

    #: LP-857 — both ways a document comes back IN: the secure upload link and inbound mail. Off in
    #: v1, which is draft-only. The same value decides whether a request's closing sentence offers
    #: an upload link, so the page and the email cannot disagree.
    receiving: bool


@router.get("/capabilities", response_model=Capabilities)
async def get_capabilities(current_user: CurrentUser) -> Capabilities:
    """What this deployment can do. Read from settings; nothing here is per-user."""
    return Capabilities(receiving=settings.receiving_enabled)
