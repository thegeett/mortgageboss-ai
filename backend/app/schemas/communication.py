"""Outbound-draft schemas (LP-811a) — what a processor is shown before sending, and what they send."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.email_send import MAILTO_MAX_CHARS


class OutboundDraftPublic(BaseModel):
    """The file's open document request, as a message ready to be copied or opened.

    ``mailto_available`` is computed server-side rather than left to the client to work out from
    ``mailto_max_chars``. Two places deciding the same thing is two places to disagree, and the
    disagreement here ships a truncated email — `mailto:` does not fail when it is too long, it opens
    a compose window containing half a message.
    """

    id: UUID
    subject: str
    body: str
    reply_to: str
    suggested_bcc: str
    mailto_available: bool
    #: Included so the UI can explain WHY the link is unavailable rather than just disabling it.
    mailto_max_chars: int = Field(default=MAILTO_MAX_CHARS)
    needs_item_count: int
    #: The primary borrower's email, or None when the file has no borrower with one (LP-823).
    #:
    #: SUGGESTED, NOT IMPOSED. The panel seeds its To: field from this and leaves it editable — a
    #: co-borrower, a corrected address and a borrower who asked to be written to elsewhere are all
    #: ordinary. Before this field the box started empty and every send was retyped by hand.
    #:
    #: NULLABLE FOR A REAL REASON: `borrowers.email` is nullable, so a file can have a borrower and
    #: no address. The panel must render that as an empty box, never as a claim.
    suggested_recipient: str | None = None


class SendDraftRequest(BaseModel):
    """What the processor is sending, and to whom.

    ``body`` is REQUIRED and is the processor's own text. It is not optional-with-a-fallback-to-the-
    stored-draft: the endpoint records what went out, and defaulting would let a stale draft be
    recorded as sent while the processor had edited it in a window that never posted.
    """

    recipient: str = Field(min_length=3, max_length=256)
    body: str = Field(min_length=1)


class SentCommunicationPublic(BaseModel):
    """Confirmation of a send — the envelope, never the content."""

    id: UUID
    status: str
    sent_at: datetime | None
    needs_items_requested: int
