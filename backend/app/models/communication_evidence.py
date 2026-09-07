"""What was actually sent, kept as evidence (LP-821).

`phase4.md` §6: *"The communication log is evidence. Append-only at the application layer, capturing
sender, recipient, the authenticated approver, template + version, the rendered body as sent, the
attachment manifest with hashes, the model draft / human edit / diff, model + prompt version, which
guardrails fired, and the inbound auth verdicts. Soft delete is fine for the UX; the audit record
must not be soft-deletable."*

WHY THIS IS A SECOND TABLE AND NOT MORE COLUMNS ON `Communication`. That row is soft-deletable, and
it is EDITED — `send_draft` overwrites `body` with the processor's edit, `LP-820` refreshes
`recipient` when an address is corrected, and LP-812 rebuilt part of it. Every one of those is right
for the UX and disqualifying for evidence: a record somebody can change is not one an auditor can
rely on, and §6's "must not be soft-deletable" is a property of the row, not of a policy about it.

SO: NO `SoftDeleteMixin`, NO `updated_at`, AND NOTHING WRITES ONE TWICE. The only operation is
insert. A correction is a new row that says what changed, never an edit — which is what "append-only
at the application layer" means when the application is the layer enforcing it.

WHAT IS RECOVERABLE FOR MESSAGES SENT BEFORE THIS TICKET, stated here because a future audit will
ask and the answer is not uniform:

* **Recoverable**: recipient, template + version, the body AS SENT, the inbound auth verdicts, and
  the attachment manifest — all still on the rows they were always on.
* **PERMANENTLY ABSENT**: the model draft and the human edit. `send_draft` overwrote `draft.body`
  with the processor's edit, so for anything sent before this ticket the composed version is not
  unstored — it is **gone**, and cannot be backfilled from anywhere. §6 asks for the draft, the edit
  and the diff; historical rows can supply only the third's right-hand side.
* **Absent but reconstructible with effort**: the approver. `send_draft` took `approver_user_id` and
  wrote it only into the activity log's detail, so it exists per message in `activity_logs` and is
  not on the message.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, utcnow
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.communication import Communication
    from app.models.loan_file import LoanFile


class EvidenceEvent(StrEnum):
    """What happened. One row per event, never an update to an earlier one."""

    SENT = "sent"
    #: LP-819 — the message came back. A separate row rather than a field on the send, because the
    #: send record must not change after the fact.
    DELIVERY_FAILED = "delivery_failed"
    RECEIVED = "received"


class CommunicationEvidence(Base, UUIDMixin):
    """One immutable record of one message event.

    NO `SoftDeleteMixin` AND NO `TimestampMixin`. The first is §6's requirement outright; the second
    is omitted because `updated_at` on an append-only row is a field that can only ever lie — either
    it equals `recorded_at` forever, or something updated a row that must not be updated.
    """

    __tablename__ = "communication_evidence"
    __table_args__ = (
        Index("ix_communication_evidence_loan_file_id", "loan_file_id"),
        Index("ix_communication_evidence_communication_id", "communication_id"),
        # ONE ROW PER (message, event). A send recorded twice is a duplicate an auditor has to
        # reconcile, and the retry that produced it is exactly the case this is likely to see.
        Index(
            "uq_communication_evidence_event",
            "communication_id",
            "event",
            unique=True,
        ),
    )

    #: RESTRICT, not CASCADE. Loan files are soft-deleted and never hard-deleted (ADR-044), so this
    #: cannot fire — and if a hard delete were ever added, the evidence is the last thing that should
    #: go with it.
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="RESTRICT"), nullable=False
    )
    #: SET NULL rather than RESTRICT. The message row is soft-deletable by design; if it were ever
    #: hard-deleted, the evidence must survive its subject rather than block the delete.
    communication_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("communications.id", ondelete="SET NULL"), nullable=True
    )

    event: Mapped[EvidenceEvent] = mapped_column(str_enum(EvidenceEvent), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    # --- §6's field set ----------------------------------------------------
    sender: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    #: The authenticated person who approved the send. NOT the person who drafted it — §6 asks for
    #: the approver, and on the copy-and-send path they are the same only by coincidence.
    approver_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    template_key: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What actually went out, at the moment it went out.
    body_as_sent: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What the drafter produced, BEFORE the processor edited it.
    #:
    #: THE ONE FIELD THAT CANNOT BE BACKFILLED. `send_draft` overwrites `Communication.body` with the
    #: edit, so for every message sent before this ticket the composed version is gone rather than
    #: unstored. Captured here at send time from then on; null on a historical row means "never
    #: recorded", which is different from "there was no draft" and the two must not be conflated.
    body_composed: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: `[{"filename": ..., "sha256": ..., "size_bytes": ...}]`. Empty for outbound, which carries no
    #: attachments by design (LP-815 — GLBA Safeguards; outbound carries a link, never a document).
    attachment_manifest: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    #: Which deterministic guard refused a composition — LP-810's `rejection_reason`.
    #:
    #: NULL MEANS "NOT RECORDED", NOT "NO GUARD FIRED", and the difference matters in an evidence
    #: record. `send_draft` has no access to the verdict today: LP-810's drafter runs earlier and
    #: returns prose, while the guard's reason lives in `email_draft_prose`. Threading it through is
    #: a service edit rather than a migration, and until it happens this column is structurally
    #: empty for every send. Reading an empty column as "the drafter was clean" is the failure this
    #: comment exists to prevent.
    guardrail_fired: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)

    #: Why a delivery failed — the provider's own words, on a `DELIVERY_FAILED` event.
    #:
    #: A SEPARATE COLUMN because it is a separate fact. This was written into `guardrail_fired`,
    #: which meant the ONLY thing that ever populated a field documented as "which guard refused a
    #: composition" was a bounce diagnostic — so `550 5.1.1 user unknown` read, to anyone following
    #: the model or the AI System Disclosure, as a compliance guard having fired. One column, two
    #: meanings, in the record that exists to be read by somebody who was not here.
    failure_reason: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    #: SES's verdicts on an inbound message, verbatim. Null for outbound.
    auth_verdicts: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    loan_file: Mapped["LoanFile"] = relationship()
    communication: Mapped["Communication | None"] = relationship()

    def __repr__(self) -> str:
        return f"<CommunicationEvidence {self.event} file={self.loan_file_id}>"
