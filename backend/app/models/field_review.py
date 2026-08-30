"""FieldReview model (LP-UI-033) — a processor's verdict on ONE extracted field.

The reviewer's keyboard loop is `Enter` accept, `R` reject, `E` correct. Each of
those is a claim by a named person about a specific value, and this is where the
claim lives.

**Beside the value, never on top of it.** The extraction is what the model read; a
review is what a person decided about what the model read. Writing the correction
into ``extracted_data`` would destroy the first to record the second, and the
question "what did the model actually say?" is the one every accuracy
investigation starts from (LP-508's whole ledger is that question).

**KEYED ON THE EXTRACTION, not on the document.** A re-extraction produces a new
version with possibly different values, and a verdict recorded against the old one
must not silently vouch for the new. So a re-extraction leaves the reviews behind
and the fields return to unreviewed — which is the honest answer, and the one that
costs a processor a second pass rather than costing an underwriter a wrong file.
See ADR-393.

Unique active row per (extraction, field_key), soft-delete to revert — the
CalculatorOverride/DTI/LTV override lifecycle (LP-76/77/87), unchanged. The
immutable trail is the activity log; this table holds the current verdict.

File-owned child: no ``company_id``, scoped transitively through the document's
loan file (ADR-052).
"""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import LongStr, ShortStr

if TYPE_CHECKING:
    from app.models.extraction import Extraction
    from app.models.user import User


class FieldVerdict(StrEnum):
    """What the processor decided about one extracted value.

    ``ACCEPTED`` — read the document, the value is right. ``CORRECTED`` — the value
    is wrong and here is the right one (in ``corrected_value``). ``REJECTED`` —
    could not verify it: the page is illegible, the document is the wrong one, the
    figure is not there. Rejected is NOT "wrong"; it is "I could not tell", which
    is a different and useful thing for the next person to know.
    """

    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class FieldReview(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One processor verdict on one field of one extraction version."""

    __tablename__ = "field_reviews"
    __table_args__ = (
        # One LIVE verdict per field per extraction. A PARTIAL unique index — the
        # uniqueness applies only to rows that are not soft-deleted, so a field can
        # be reviewed, reverted and reviewed again. The WHERE clause is
        # Postgres-specific (`postgresql_where`), matching
        # `uq_extractions_document_id_current`.
        #
        # A three-column UniqueConstraint including `deleted_at` would look
        # equivalent and is not: two reverts landing in the same microsecond would
        # collide, and every revert would have to invent a distinct timestamp.
        Index(
            "uq_field_reviews_extraction_field_active",
            "extraction_id",
            "field_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    extraction_id: Mapped[UUID] = mapped_column(
        ForeignKey("extractions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    #: The typed-core key, e.g. ``gross_pay``.
    field_key: Mapped[ShortStr] = mapped_column(nullable=False)
    verdict: Mapped[FieldVerdict] = mapped_column(str_enum(FieldVerdict), nullable=False)
    #: The value the processor says is right (CORRECTED only). A STRING, exact as
    #: typed: coercing here would lose what they actually entered, and the audit
    #: question is what they entered.
    corrected_value: Mapped[LongStr | None] = mapped_column(nullable=True)
    #: Why — required for REJECTED (an unverifiable field with no reason tells the
    #: next processor nothing), optional otherwise.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    extraction: Mapped["Extraction"] = relationship()
    reviewed_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<FieldReview {self.field_key}={self.verdict} extraction={self.extraction_id}>"
