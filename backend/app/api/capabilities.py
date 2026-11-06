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

LP-1009 — `inbox` is the one exception to "what the server can do": it is a fact about the caller's
company, read per request, because mail arrives per company. It is still a capability, not a
permission: the inbound routes scope to the company whatever this says.

It is authenticated like everything else. Nothing here is secret — a processor can see the same fact
by looking at the page — but an unauthenticated route is a surface, and this one would exist only to
save a header.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import CurrentUser
from app.core.config import settings
from app.core.database import DbSession
from app.services.mail_domain import company_receives_mail

router = APIRouter(tags=["capabilities"])


class Capabilities(BaseModel):
    """The switches a screen has to know about."""

    #: LP-857 — the secure upload link. Off in v1. The same value decides whether a request's closing
    #: sentence offers an upload link, so the page and the email cannot disagree.
    receiving: bool
    #: LP-1009 — incoming mail on the Communication tab: this company has a mail domain that receives
    #: (`active` or `problem`). Separate from `receiving`, which must not change what borrowers are
    #: promised.
    inbox: bool
    #: LP-858 §5 — whether ✦ polish is wired to anything. `email_draft_enabled` is off in every
    #: environment, and the button was rendering and then refusing: *"Polish is not available on
    #: this environment."* That reads as breakage, and a processor cannot switch it on. Served here
    #: so the button is ABSENT rather than present-and-failing — the page's own principle, applied
    #: to the one control LP-857 did not reach.
    polish: bool


@router.get("/capabilities", response_model=Capabilities)
async def get_capabilities(current_user: CurrentUser, db: DbSession) -> Capabilities:
    """What this deployment can do, and whether the caller's company receives mail."""
    return Capabilities(
        receiving=settings.receiving_enabled,
        inbox=await company_receives_mail(db, current_user.company_id),
        polish=settings.email_draft_enabled,
    )
