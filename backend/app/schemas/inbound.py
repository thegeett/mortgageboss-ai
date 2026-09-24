"""Triage schemas (LP-806) — what a processor sees before deciding, and what they decide."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InboundAttachmentPublic(BaseModel):
    """One attachment on a message awaiting triage.

    `filename_original` IS RETURNED, and that is a deliberate exception to the rule that governs it
    everywhere else. It is attacker-controlled text and it is dropped from the readonly view — but a
    processor deciding whether to accept a file has to see what the sender called it, and the
    normalised form has had exactly the information they need for that removed. It is returned to an
    authenticated user of the owning company, over a route already scoped to their loan file, and it
    is never logged, never used to build a path, and never rendered as HTML.
    """

    id: UUID
    filename_original: str | None
    filename_normalized: str | None
    declared_content_type: str | None
    sniffed_content_type: str | None
    size_bytes: int
    safety_state: str
    safety_reason: str | None
    disposition: str
    nesting_depth: int


class InboundMessagePublic(BaseModel):
    """A message in the triage queue."""

    id: UUID
    loan_file_id: UUID | None
    routing_state: str
    routing_signal: str | None
    routing_confidence: float | None
    is_dsn: bool
    is_auto_reply: bool
    from_address: str | None
    subject: str | None
    received_at: datetime | None
    auth_verdicts: dict[str, str]
    attachments: list[InboundAttachmentPublic]


class AcceptAttachmentRequest(BaseModel):
    """How to accept one attachment.

    ``as_correspondence`` is the third answer: a lender's conditional-approval PDF is worth keeping
    and is not a borrower document. It satisfies no need and would be classified against a 166-type
    borrower taxonomy.
    """

    as_correspondence: bool = Field(default=False)


class AcceptAttachmentResponse(BaseModel):
    document_id: UUID | None
    disposition: str
    possible_duplicate: bool


class UseAsConditionSheetRequest(BaseModel):
    """Turn an emailed PDF into a condition round (LP-905, screen S1-13).

    ⚠️ `attach_to_round_id` IS ACCEPTED AND REFUSED, DELIBERATELY. Spec §LP-905 defines it as running
    "the LP-907 merge" when the file's newest round was pasted and has no PDF — and LP-907 does not
    exist yet. Declaring the field now keeps the endpoint's contract stable for the UI that will send
    it, while refusing it is honest: half a merge that silently created a second round instead would
    be worse than a clear "not yet".
    """

    attach_to_round_id: UUID | None = Field(
        default=None,
        description="Attach to an existing pasted round instead of starting a new one (LP-907).",
    )


class UseAsConditionSheetResponse(BaseModel):
    """The round the attachment became, and what happened to the attachment."""

    round_id: UUID
    status: str
    #: Always `correspondence` — the attachment is kept, never turned into a document (ADR-403).
    disposition: str
