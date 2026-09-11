"""The communication timeline (LP-812) — one file's history, once each.

Every route declares :data:`ScopedLoanFile`, so the file is fetched and company-scoped before
anything here runs. Nothing in this module derives a `company_id`.

WHAT IT RETURNS AND WHAT IT DOES NOT. Subjects and filenames travel — a processor scanning a
timeline needs to recognise a message — and message BODIES do not. The body lives on the message
itself, is dropped from every readonly view, and putting it in a list would make a screen anybody
scrolls past the fullest copy of a borrower's prose in the product.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.dependencies import CurrentUser, ScopedLoanFile
from app.core.database import DbSession
from app.services.timeline import TimelineEntry, TimelineFilter, build_timeline

router = APIRouter(prefix="/loan-files/{file_identifier}/timeline", tags=["communications"])


class TimelineAttachmentPublic(BaseModel):
    """One attachment on an inbound message, and what became of it (LP-825 review).

    THE DISPOSITION IS THE HALF THAT WAS MISSING. The manifest sent filenames alone, so a document
    accepted into the file rendered identically to one nobody has looked at — and the sentence that
    used to answer it, `inbound_triage`'s "A document arrived by email and was accepted", left the
    timeline when LP-825 stopped it reading the activity log.
    """

    name: str
    disposition: str


class TimelineEntryPublic(BaseModel):
    """One thing that happened, as the screen renders it."""

    id: UUID
    kind: str
    at: datetime
    summary: str
    direction: str | None
    status: str | None
    subject: str | None
    counterparty: str | None
    actor_user_id: UUID | None
    attachments: list[TimelineAttachmentPublic]
    is_important: bool
    unread: bool
    detail: dict[str, Any]
    #: LP-841 — which party tab this belongs under, or None for anything that belongs under none.
    #: Sent from the server for the reason the FILTER is (see `read`): a bucket derived on the
    #: client is a second definition of "the lender's messages", and when the two drift a draft
    #: exists with an empty tab in front of it.
    party: str | None

    @classmethod
    def of(cls, entry: TimelineEntry) -> "TimelineEntryPublic":
        return cls(
            id=entry.id,
            kind=entry.kind.value,
            at=entry.at,
            summary=entry.summary,
            direction=entry.direction,
            status=entry.status,
            subject=entry.subject,
            counterparty=entry.counterparty,
            actor_user_id=entry.actor_user_id,
            attachments=[
                TimelineAttachmentPublic(name=a.name, disposition=a.disposition)
                for a in entry.attachments
            ],
            is_important=entry.is_important,
            unread=entry.unread,
            detail=entry.detail,
            party=entry.party,
        )


class TimelinePublic(BaseModel):
    """The timeline, plus the one thing the screen needs beside it.

    `inbox_address` IS HERE because spec 4.3 asks for it on this screen: a processor telling a
    borrower where to send documents needs it in front of her, and the timeline is where she is
    when she notices nothing has arrived. It is a bearer capability (ADR-397) returned to an
    authenticated user of the owning company, through the one accessor.
    """

    entries: list[TimelineEntryPublic]
    inbox_address: str
    #: How many arrived messages nobody has opened — the badge (§C.5: "without the badge the queue is
    #: pull-only and an evening reply sits unseen until she happens to open the tab").
    #:
    #: COUNTED OVER THE WHOLE FILE, not over `entries`. A filtered or truncated page would otherwise
    #: report a badge that shrank when somebody clicked a pill, which is a number that teaches its
    #: reader to distrust it.
    unread_count: int
    #: True when the history is longer than this response. There is no pagination yet (escalated in
    #: LP-812), so the alternative was dropping the oldest entries in silence — a page that looks
    #: complete and is not. A caller that ignores this is no worse off than before; one that reads
    #: it can say "older entries not shown" rather than implying there are none.
    truncated: bool


@router.get("", response_model=TimelinePublic)
async def read(
    loan_file: ScopedLoanFile,
    db: DbSession,
    current_user: CurrentUser,
    filter: Annotated[TimelineFilter, Query()] = TimelineFilter.ALL,
) -> TimelinePublic:
    """This file's messages and activity, newest first, each event appearing once.

    THE FILTER IS A SERVER CONCERN. Sent, received, drafts and activity are defined by
    `services/timeline`, and defining them again on the client is how a "sent" pill starts showing
    drafts — two definitions of one word that nothing forces to agree.
    """
    from app.services.email_reply import unread_count

    entries, truncated = await build_timeline(db, loan_file=loan_file, wanted=filter)
    return TimelinePublic(
        entries=[TimelineEntryPublic.of(entry) for entry in entries],
        inbox_address=loan_file.get_inbox_address(),
        truncated=truncated,
        unread_count=await unread_count(db, loan_file=loan_file),
    )
