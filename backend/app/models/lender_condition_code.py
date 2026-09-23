"""The (lender, code) → meaning map (LP-904 schema, LP-910 data; ADR-407).

A lender condition code is that lender's own template id. `7086` is short funds to close at UWM and
means nothing at Champions, where the same demand is `268`. So the key is always `(lender, code)` and
never the code alone — a global table would be wrong on its first row and the error would be
invisible, since a lookup would return a plausible label for the wrong lender's template.

BECAUSE `lenders` IS COMPANY-SCOPED (ADR-045, unique slug per company), `(lender_id, code)` is
per-company by construction: two processing companies each working with UWM keep separate maps. That
is right for ownership and is exactly what makes SEEDING hard, which is why `lenders` gained
`canonical_lender_key` — see ADR-407's consequences.

`status` IS THE POINT OF THE TABLE, not decoration. An unknown code arriving on an import is recorded
as `OBSERVED_UNMAPPED` rather than dropped, so the map grows from what lenders actually send instead
of from what someone predicted. `times_seen` is what makes the backlog orderable: the unmapped code on
forty files is worth a domain expert's attention before the one seen once.

NOT NPI. A template id, a label the lender publishes, and counts — nothing borrower-derived, so the
whole table is exposed in `readonly.lender_condition_codes`.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, utcnow
from app.models.condition import BucketKind, OwnerHint
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.lender import Lender


class LenderCodeStatus(StrEnum):
    """How this row got here, and whether a human has looked at it."""

    SEEDED = "seeded"  # shipped in the LP-910 YAML and loaded
    OBSERVED_UNMAPPED = "observed_unmapped"  # arrived on an import; nobody has mapped it yet
    MAPPED = "mapped"  # a person reviewed an observed code and gave it a meaning


class LenderConditionCode(Base, UUIDMixin, TimestampMixin):
    """One lender's meaning for one of its own condition codes."""

    __tablename__ = "lender_condition_codes"
    __table_args__ = (
        # THE KEY (ADR-407). Unique per lender, never globally.
        Index("uq_lender_condition_codes_lender_code", "lender_id", "code", unique=True),
        # The review queue: unmapped codes for a lender, commonest first.
        Index("ix_lender_condition_codes_lender_status", "lender_id", "status"),
    )

    #: No `company_id`: scoped transitively through the lender, which carries one (ADR-052). A code
    #: row is only ever reached through its lender, unlike a round or a condition.
    lender_id: Mapped[UUID] = mapped_column(
        ForeignKey("lenders.id", ondelete="CASCADE"), nullable=False
    )
    #: As the lender prints it, leading zeros kept — "0006" is not 6.
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(MEDIUM_STRING), nullable=False)

    #: All four defaults are NULLABLE on purpose. An observed code has none of them until a person
    #: decides, and a default that guessed would be indistinguishable from one that was chosen.
    canonical_type_id: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)
    default_bucket_kind: Mapped[BucketKind | None] = mapped_column(
        str_enum(BucketKind, name="lender_condition_code_bucket_kind"), nullable=True
    )
    default_owner_hint: Mapped[OwnerHint | None] = mapped_column(
        str_enum(OwnerHint, name="lender_condition_code_owner_hint"), nullable=True
    )
    info_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[LenderCodeStatus] = mapped_column(
        str_enum(LenderCodeStatus), default=LenderCodeStatus.OBSERVED_UNMAPPED, nullable=False
    )
    #: Incremented on every import that carries this code — what orders the unmapped backlog.
    times_seen: Mapped[int] = mapped_column(default=0, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    lender: Mapped["Lender"] = relationship()

    def __repr__(self) -> str:
        return f"<LenderConditionCode {self.code} {self.status} lender={self.lender_id}>"
