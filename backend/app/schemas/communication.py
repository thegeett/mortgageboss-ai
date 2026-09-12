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

    #: LP-847 — MAY BE EMPTY, and that is the product's shape rather than a loosened validation.
    #:
    #: Nothing here transmits: "send" records that a PROCESSOR sent the message from their own mail
    #: client, to an address they may know perfectly well and have never typed into this system.
    #: LP-843 deliberately gives a party with no contact on file a draft with an empty To — and the
    #: bound here was `min_length=3`, so the ticket that made an empty To legitimate never looked at
    #: the control that refuses one. A processor could compose the message and never record sending
    #: it.
    #:
    #: `min_length` was never a format check either: it accepted "abc" (LP-841 review). Dropping it
    #: removes a bound that was protecting nothing, not a validation that was.
    recipient: str = Field(default="", max_length=256)
    body: str = Field(min_length=1)
    #: LP-831 — the subject the processor is actually sending.
    #:
    #: OPTIONAL, UNLIKE `body`, and the asymmetry is deliberate. `body` refuses to default because a
    #: stale draft recorded as sent while the processor had edited it is a false evidence row. A
    #: subject has no such gap: the modal shows the stored one and posts it back unchanged unless
    #: somebody edits it, and a caller that omits it is saying "the one already on the draft", which
    #: is a complete and true answer.
    subject: str | None = Field(default=None, max_length=256)


class SentCommunicationPublic(BaseModel):
    """Confirmation of a send — the envelope, never the content."""

    id: UUID
    status: str
    sent_at: datetime | None
    needs_items_requested: int
