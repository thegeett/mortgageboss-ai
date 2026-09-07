"""A reminder a processor has already decided about (LP-814).

SUGGESTIONS ARE COMPUTED, NOT STORED. The three rules read `requested_at`, the needs list and the
activity log, and the answer is a function of those — so materialising it would mean a second copy
that goes stale the moment a document arrives, and a processor being nudged about something that
turned up an hour ago.

WHAT IS STORED IS THE DECISION. "Not now" and "not ever" are the only facts a query cannot derive,
because they are things a person chose. Everything else is re-derived on every read.

SNOOZE AND DISMISS ARE THE SAME ROW, and that is deliberate: a dismissal is a snooze with no end.
Two tables would make "is this suppressed?" two questions, and the second one is the one somebody
forgets.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import SHORT_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class ReminderKind(StrEnum):
    """Which rule produced a suggestion. `phase4.md` spec 4.5 names three.

    THE KIND IS PART OF THE IDENTITY, not decoration. A processor who snoozes "nobody has replied"
    has not snoozed "this file has gone quiet" — they are different observations about the same file
    and lead to different actions, and one suppressing the other is how the second stops being made.
    """

    #: A need was REQUESTED more than three days ago and nothing has arrived.
    NEEDS_ITEM_PENDING = "needs_item_pending"
    #: A message was sent more than five days ago and nothing has come back.
    NO_REPLY = "no_reply"
    #: Nothing at all has happened on this file for seven days.
    FILE_UNTOUCHED = "file_untouched"


class ReminderSnooze(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One suggestion a processor has put off, or refused.

    A file-owned child (ADR-052): reached only through its loan file, so it carries no `company_id`
    and scopes transitively.
    """

    __tablename__ = "reminder_snoozes"
    __table_args__ = (
        # ONE DECISION PER SUGGESTION. `subject_id` is the need or the message the rule fired about,
        # and NULL for a rule about the file itself — so this index carries NULLS NOT DISTINCT, or
        # every "file untouched" snooze would be a fresh row and none of them would suppress
        # anything. That is the LP-803 default again, in the direction where it bites.
        Index(
            "uq_reminder_snoozes_subject",
            "loan_file_id",
            "kind",
            "subject_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[ReminderKind] = mapped_column(str_enum(ReminderKind), nullable=False)

    #: What the rule fired about — a needs item, or a communication. NULL for a rule about the whole
    #: file. NOT A FOREIGN KEY, deliberately: it points at two different tables depending on `kind`,
    #: and a polymorphic FK is a constraint that can only be half-enforced. The reads that matter go
    #: through the suggestion builder, which starts from the live row and looks the snooze up.
    subject_id: Mapped[UUID | None] = mapped_column(nullable=True)

    #: When the suggestion comes back. NULL means never — a dismissal.
    #:
    #: A TIMESTAMP AND A NULL, not a separate `dismissed` boolean. "Come back on Thursday" and "stop
    #: telling me" are the same decision at different distances, and two fields would let a row say
    #: both.
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Why, in the processor's own words. Optional, never required — a snooze somebody has to justify
    #: is one they will not use, and an unused snooze means the suggestion stays and gets ignored,
    #: which is worse than either.
    note: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    loan_file: Mapped["LoanFile"] = relationship()

    def suppresses(self, *, now: datetime) -> bool:
        """Whether this decision still hides the suggestion.

        BOTH CONDITIONS IN ONE PLACE. Spread across the callers, one of them checks `snoozed_until`
        and forgets `deleted_at`, and a processor who un-snoozed something never sees it again.
        """
        if self.deleted_at is not None:
            return False
        return self.snoozed_until is None or self.snoozed_until > now

    def __repr__(self) -> str:
        return f"<ReminderSnooze {self.kind} file={self.loan_file_id}>"
