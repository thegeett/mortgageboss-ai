"""Outbound-draft schemas (LP-811a) — what a processor is shown before sending, and what they send."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.email_draft import DraftDecisionRequired
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


class SaveDraftBodyRequest(BaseModel):
    """A processor's own words, as the editor produced them (LP-853).

    ``body`` IS HTML AND IS NOT TRUSTED. It is sanitised server-side against the allowlist in
    `app/communications/sanitise.py` before it reaches the column — the editor is not a security
    boundary, and a request built by hand does not go through it at all.

    THERE IS NO `body_format` FIELD, and that is deliberate rather than an omission. A save from a
    person IS the edit; letting a caller declare "this one is still plain" would let the flag and
    the fact disagree, and the flag's entire job is that they cannot.
    """

    body: str = Field(min_length=1, max_length=200_000)
    #: Optional, like the send's. Omitting it means "the one already on the draft", which is a
    #: complete and true answer; the modal posts both because it edits both.
    subject: str | None = Field(default=None, max_length=256)


class SavedDraftPublic(BaseModel):
    """What a save stored — never the words back, the caller already has them."""

    id: UUID
    body_format: str
    subject: str | None


class SentCommunicationPublic(BaseModel):
    """Confirmation of a send — the envelope, never the content."""

    id: UUID
    status: str
    sent_at: datetime | None
    needs_items_requested: int


# --------------------------------------------------------------------------------------------- #
# The open-draft refusal (LP-850)
# --------------------------------------------------------------------------------------------- #
class NeedSummaryPublic(BaseModel):
    """One document, named as the processor asked for it."""

    id: UUID
    title: str


class OpenDraftPublic(BaseModel):
    """The draft that is already open, described well enough to decide about.

    CONTENTS AND AGE, NOT AN ID. "There is an open draft" is not something anybody can act on;
    "created Tue 14:02, asking for a bank statement and a pay stub" is, and it is what a processor
    remembers. Carried on the refusal itself so the dialog renders without a second round trip —
    which is also a second chance for the answer to have changed underneath it.
    """

    id: UUID
    created_at: datetime
    needs: list[NeedSummaryPublic]
    #: Whether a person has written their own words into it, which an append would overwrite.
    body_edited: bool
    #: LP-851 — the processor's own first line, so the warning can quote it rather than describe it.
    #: "Your changes will be lost" is abstract and gets dismissed; their own sentence does not. None
    #: when there is nothing quotable, and the dialog then drops the quotation rather than inventing
    #: one.
    edited_excerpt: str | None = None


class DraftDecisionPublic(BaseModel):
    """One party the caller has to answer for."""

    party: str
    open_draft: OpenDraftPublic
    #: What this request would add to that draft.
    adding: list[NeedSummaryPublic]


class WouldCreatePublic(BaseModel):
    """One party with nothing open — no decision needed, and the processor must still be told.

    LP-852's rule, at the point a request is refused: a draft to somebody the processor did not
    expect, created without their noticing, is a message that never gets sent.
    """

    party: str
    address: str | None
    needs: list[NeedSummaryPublic]


class DraftConflictPublic(BaseModel):
    """The 409 body — every party at once, because the UI must not have to ask twice.

    A processor who has just confirmed five documents and is then asked a second question clicks
    the primary without reading it. One refusal, one dialog, one answer.
    """

    decisions_required: list[DraftDecisionPublic]
    would_create: list[WouldCreatePublic]
    #: LP-850 REVIEW — the sentence shown if anything renders the envelope's `message` rather than
    #: this payload. The envelope reads this key, and its fallback is "Request failed", which tells
    #: a processor nothing about a refusal whose entire point is that THEY have to choose.
    message: str = ""

    @classmethod
    def of(cls, exc: DraftDecisionRequired) -> DraftConflictPublic:
        parties = [conflict.party.value for conflict in exc.decisions_required]
        if len(parties) == 1:
            summary = f"There is already an open draft to the {parties[0]}."
        else:
            summary = f"There are already open drafts to {len(parties)} parties."
        return cls(
            message=summary,
            decisions_required=[
                DraftDecisionPublic(
                    party=conflict.party.value,
                    open_draft=OpenDraftPublic(
                        id=conflict.draft_id,
                        created_at=conflict.created_at,
                        needs=[
                            NeedSummaryPublic(id=n.id, title=n.title) for n in conflict.carrying
                        ],
                        body_edited=conflict.body_edited,
                        edited_excerpt=conflict.edited_excerpt,
                    ),
                    adding=[NeedSummaryPublic(id=n.id, title=n.title) for n in conflict.adding],
                )
                for conflict in exc.decisions_required
            ],
            would_create=[
                WouldCreatePublic(
                    party=planned.party.value,
                    address=planned.address,
                    needs=[NeedSummaryPublic(id=n.id, title=n.title) for n in planned.adding],
                )
                for planned in exc.would_create
            ],
        )


# --------------------------------------------------------------------------------------------- #
# ✦ polish (LP-856)
# --------------------------------------------------------------------------------------------- #
class PolishRequest(BaseModel):
    """The text to rewrite — what is ON SCREEN, not what is stored.

    THE UNSAVED EDIT IS THE POINT. A processor presses polish having just typed something; reading
    the stored body would rewrite the version before their last sentence, and the proposal would
    differ from what they are looking at in a way nothing on screen explains.

    NAMED `body` DELIBERATELY, so `test_no_draft_save_route.py` sees it. That guard's property is
    "a route that takes body text from the client", and this one does — it simply does not WRITE it.
    The route is allow-listed there with that reason, which keeps the exception visible rather than
    hiding it behind a field called something else.
    """

    body: str = Field(min_length=1, max_length=200_000)


class PolishPublic(BaseModel):
    """A proposal, or the reason there is none.

    BOTH SHAPES IN ONE RESPONSE rather than an error status, because a refusal here is an ordinary
    outcome: `email_draft_enabled` is off in every environment, so "unavailable" is what a processor
    gets today and it is not a failure of the request.
    """

    #: The rewritten message. None when `refusal` says why not.
    polished: str | None
    #: A word the UI turns into a sentence, and the log groups by. None on success.
    refusal: str | None
