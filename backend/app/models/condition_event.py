"""Append-only history for rounds and conditions (LP-904, spec §9.7).

Copies `finding_event.py`'s pattern, which enforces append-only **by shape**: `Base, UUIDMixin` and
nothing else. A `TimestampMixin` would add an `updated_at` that can only ever lie on a row nothing
updates; a `SoftDeleteMixin` would permit a mutating delete. `occurred_at` is the event's own time.

TWO DIFFERENCES FROM `FindingEvent`, both deliberate:

1. **It carries `company_id`.** A finding event is reached only through its finding, so it scopes
   transitively (ADR-052). A condition event is read directly — the round-details sheet builds its
   history from these rows by round id — so the scoping filter needs a column on the row.
2. **`detail` is NPI.** `FindingEvent.detail` is documented as "PII-safe structured context … never
   raw borrower data". This one holds what CHANGED: an edited wording, a note that was appended, the
   bucket a condition moved between. That is the lender's text, so the column is dropped from
   `readonly.condition_events` rather than scrubbed.

THERE WAS NO TEST TO COPY. `finding_event.py`'s immutability is asserted nowhere in the suite —
every test that touches it only READS event rows to check a lifecycle sequence. LP-904 writes that
guard for this table from scratch (`tests/models/test_condition_events_append_only.py`).
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, utcnow
from app.models.enums import str_enum

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class ConditionEventKind(StrEnum):
    """What happened. The first eleven are Stage 1's; the last eight are Stage 2's (LP-912, LP-915).

    WHAT IS ABSENT IS STILL THE POINT, AND THE LIST CHANGED IN STAGE 2 — so this paragraph is
    rewritten rather than left describing a file it no longer matches. `ROUND_COMPARED` used to be
    named here as forbidden, on the argument that a comparison row MANUFACTURES a lender answer: while
    nothing could confirm one, the row's existence was the only evidence the inference had run. LP-915
    adds it together with the confirm step that earns it — the comparison PROPOSES and the processor's
    click is what records a verdict — so the row no longer decides anything.

    **`CONDITION_CLEARED`, `CONDITION_WAIVED` and `CONDITION_REMOVED` stay absent permanently**, not
    until some later stage earns them. Each would STATE the lender's answer with nothing attached
    saying where it came from, and `cleared` is reachable only through a recorded verdict naming who
    said so and on what date (ADR-404, ADR-408). The mechanism in their place is
    `CONDITION_VERDICT_RECORDED`, whose detail carries that verdict — a pointer to evidence rather
    than a claim standing on its own. `tests/models/test_condition_events_append_only.py` asserts both
    halves: the three are absent AND the verdict kind is present, because asserting the absence alone
    would pass just as well against a product that could not record what the lender said at all.

    ADDING A MEMBER HERE IS A MIGRATION, AND NO TEST WILL TELL YOU SO. `kind` is VARCHAR + CHECK
    (ADR-037, via `str_enum`), so a new member changes what the code writes and nothing about what
    the database accepts — and conftest builds the schema with `create_all`, which regenerates the
    CHECK from this very enum. The suite therefore stays green against a database that would reject
    the value on the first real write. That is the LP-637 defect exactly;
    `tests/test_activity_type_migrations.py` guards `activity_type` against it and now guards
    `ck_condition_events_conditioneventkind` too.
    """

    ROUND_RECEIVED = "round_received"
    ROUND_PARSED = "round_parsed"
    ROUND_PARSE_FAILED = "round_parse_failed"
    #: A processor asked for a stored sheet to be read again (LP-909 §3).
    #:
    #: NOT `ROUND_RECEIVED` REUSED, THOUGH THAT WOULD HAVE SAVED A MIGRATION. Screen S1-09
    #: renders this history, and "Condition sheet received" for an event where nothing was received
    #: is the class of statement this stage keeps deleting from comments and screens. Adding it is
    #: permitted by ADR-404 precisely because something writes it — the rule forbids members nothing
    #: writes, not members that cost a constraint swap.
    ROUND_REPARSE_REQUESTED = "round_reparse_requested"
    ROUND_IMPORTED = "round_imported"
    ROUND_DISCARDED = "round_discarded"
    #: A round gained a later source — the PDF for a round that was pasted (LP-907).
    ROUND_ENRICHED = "round_enriched"
    CONDITION_CREATED = "condition_created"
    CONDITION_SEEN_AGAIN = "condition_seen_again"
    CONDITION_NOTE_ADDED = "condition_note_added"
    CONDITION_EDITED = "condition_edited"

    # --- Stage 2 (LP-912, ADR-408; the last two are LP-915's) --------------------------------- #
    #
    # EIGHT MEMBERS, AND THE CONSTRAINT SWAP IS IN THE SAME MIGRATION. The docstring above says
    # adding a member here is a migration and no test will tell you so — that is still true, and it is
    # now also watched: `_CASES` in `tests/test_activity_type_migrations.py` covers this constraint,
    # so an unswapped member fails there rather than on a processor's first click.
    #
    # WHAT IS STILL ABSENT IS AS DELIBERATE AS BEFORE. There is no `condition_cleared`: clearing is
    # `CONDITION_VERDICT_RECORDED` with a verdict naming who said so and where, because a bare
    # "cleared" event would be the app asserting the lender's answer without its provenance
    # (ADR-404, ADR-408). And there is still no `condition_removed` — nothing disappears. (LP-940's
    # `condition_withdrawn` is a soft delete of a hand-added row, with Undo; the row and its history stay.)

    #: Our track moved. Carries `from`/`to`, plus the reason a BACKWARD move requires.
    CONDITION_PREP_MOVED = "condition_prep_moved"
    #: The lender's answer was recorded: cleared, waived, or a manual "came back". The verdict itself
    #: — who said so, where, and on what date — travels in the detail.
    CONDITION_VERDICT_RECORDED = "condition_verdict_recorded"
    #: A cleared or waived condition was put back to open, with a reason. The old verdict stays in
    #: history: this says it was overruled, not that it never happened.
    CONDITION_REOPENED = "condition_reopened"
    #: THE ONE EVENT FOR A CAME-BACK (ADR-408, spec §6 rule 4). It carries BOTH from→to pairs — the
    #: lender status to `not_cleared` and our status back to `to_do` — because that is one statement by
    #: the lender with one consequence for us. `CONDITION_SEEN_AGAIN` still records the appearance
    #: (`round_numbers` derives from it, so the `R1 R2` chips would break without it), and
    #: `CONDITION_NOTE_ADDED` folds into this one when the note is what reopened the condition.
    CONDITION_CAME_BACK = "condition_came_back"
    #: Who it is waiting on was changed by hand (A2). The processor's choice outranks every hint.
    CONDITION_OWNER_CHANGED = "condition_owner_changed"
    #: A reworded pair was confirmed as one demand: the old condition is Replaced and points at the
    #: new one. Nothing is deleted.
    CONDITION_SUPERSEDED = "condition_superseded"
    #: LP-915. A round was compared against what was open before it, and the result was saved.
    ROUND_COMPARED = "round_compared"
    #: LP-919 — the app read a condition into items (detail: source, type id, confidence, status; no
    #: text), and she confirmed or replaced that reading (S3-03).
    CONDITION_READ = "condition_read"
    CONDITION_READING_CONFIRMED = "condition_reading_confirmed"
    #: LP-920 — the plan proposed for a condition (detail: next step, item count, reason key), a change
    #: she made to it (option, item added or removed, next step), and the round's plan confirmed.
    CONDITION_PLANNED = "condition_planned"
    CONDITION_PLAN_CHANGED = "condition_plan_changed"
    ROUND_PLAN_CONFIRMED = "round_plan_confirmed"
    #: LP-922 — a condition was put into a draft email (detail: recipient, communication id). The
    #: send is Phase 4's `communication_sent` activity plus this condition's `condition_prep_moved`.
    CONDITION_DRAFTED = "condition_drafted"
    #: LP-922 follow-up — she used the AI's polish of a draft (detail: warnings accepted; no text).
    CONDITION_DRAFT_POLISHED = "condition_draft_polished"
    #: LP-923 — evidence arrived and was checked by code (detail: document id, results counted — no
    #: figures); she accepted a failed check with a reason; she answered a finding (asked / explained).
    CONDITION_EVIDENCE_CHECKED = "condition_evidence_checked"
    CONDITION_EVIDENCE_ACCEPTED = "condition_evidence_accepted"
    CONDITION_FINDING_ANSWERED = "condition_finding_answered"
    #: LP-915. An imported round was switched between "full list" and "just some" (A7), which is what
    #: makes a comparison runnable — or withdraws its unconfirmed suggestions.
    ROUND_COMPLETENESS_CHANGED = "round_completeness_changed"
    #: LP-940 — a condition SHE ADDED BY HAND was withdrawn as entered in error, with her reason. It is
    #: soft-deleted, not removed: the row, its history and this event stay (ADR-404 as amended). Never
    #: a sheet condition, never one the lender has answered on, never one sent in a package.
    CONDITION_WITHDRAWN = "condition_withdrawn"
    #: LP-940 — Undo of a withdrawal: the condition is back on the file as it was.
    CONDITION_RESTORED = "condition_restored"
    #: LP-949 — an UNTYPED condition got its library type from the lender's code map: the file's lender
    #: was set (or changed), or a person confirmed the code in "Codes to review". Detail says which
    #: (`by`), the type and the lender. A typed condition is never re-typed.
    CONDITION_TYPED = "condition_typed"
    #: LP-949 — she said the lender the app detected on this round's sheet is not the file's lender.
    #: The suggestion stops showing for that round; nothing else changes.
    ROUND_LENDER_DECLINED = "round_lender_declined"
    #: LP-951 — she imported a sheet whose borrower or loan number did not match the file, after the
    #: warning. Detail says WHICH differed (`borrower_differs`, `loan_number_differs`), never the values.
    ROUND_WRONG_FILE_CONFIRMED = "round_wrong_file_confirmed"
    #: LP-953 — she linked a document to an item by hand (Link, Change, Upload here, or choosing
    #: "Already in the file"). Detail: the item key, the document id, the page. No document text.
    CONDITION_EVIDENCE_LINKED = "condition_evidence_linked"
    #: LP-953 — she removed a link; the evidence row is deleted and `condition_item_unlinks` keeps her
    #: decision so no automatic match puts it back.
    CONDITION_EVIDENCE_UNLINKED = "condition_evidence_unlinked"


class ConditionEvent(Base, UUIDMixin):
    """One immutable record of something that happened to a round or a condition."""

    __tablename__ = "condition_events"
    __table_args__ = (
        # One round's history in time order — the shape the round-details sheet reads (S1-09). A
        # composite also serves a plain round_id lookup by prefix, so no second index is needed.
        Index("ix_condition_events_round_occurred", "round_id", "occurred_at"),
        Index("ix_condition_events_condition_occurred", "condition_id", "occurred_at"),
        Index("ix_condition_events_loan_file_id", "loan_file_id"),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), nullable=False
    )
    #: Both nullable and at least one is set in practice: a round event has no condition, a
    #: condition event names the round it was seen on. Not enforced as a CHECK because
    #: `CONDITION_EDITED` outside an import legitimately has no round.
    round_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("condition_rounds.id", ondelete="CASCADE"), nullable=True
    )
    condition_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conditions.id", ondelete="CASCADE"), nullable=True
    )

    kind: Mapped[ConditionEventKind] = mapped_column(str_enum(ConditionEventKind), nullable=False)
    #: Null for a system event — a parse task has no actor, and naming the processor who uploaded
    #: the sheet as the actor of the parse would make the trail say something untrue.
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: NPI — what changed, which is the lender's text. Dropped from the readonly view.
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    loan_file: Mapped["LoanFile"] = relationship()

    def __repr__(self) -> str:
        return f"<ConditionEvent {self.kind} file={self.loan_file_id}>"
