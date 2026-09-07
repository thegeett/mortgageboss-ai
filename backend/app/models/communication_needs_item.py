"""Which needs a draft email is asking for (LP-809).

A document-request draft ACCUMULATES. A processor clicks "request" on Tuesday, three more findings
land on Wednesday, and the borrower should receive one email listing everything — not four emails
arriving over two days, each asking for one thing. So the draft's contents are a set of needs that
grows and shrinks, and its body is REGENERATED from that set rather than appended to.

That is why this is a join table and not the ``Communication.needs_item_id`` column that already
exists. That column answers "which need was this message about", which is the right question for a
sent, single-purpose message and the wrong one for a draft that is still collecting. It stays as it
is; nothing here changes its meaning.

Rows are the draft's CONTENTS, so both sides CASCADE: a deleted draft takes its membership with it,
and a need that no longer exists cannot still be in an email. That differs deliberately from
``Communication.needs_item_id``'s ``SET NULL``, which preserves the historical fact that a sent
message concerned a need that has since gone. A draft has no history to preserve — it has not been
sent.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.communication import Communication
    from app.models.needs_item import NeedsItem


class CommunicationNeedsItem(Base, TimestampMixin):
    """One need included in one draft.

    Composite primary key rather than a surrogate id: the pair IS the identity, and a surrogate
    would allow the same need to be added to the same draft twice — which renders as the borrower
    being asked for the same document twice in one email.
    """

    __tablename__ = "communication_needs_items"

    communication_id: Mapped[UUID] = mapped_column(
        ForeignKey("communications.id", ondelete="CASCADE"), primary_key=True
    )
    needs_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("needs_items.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    communication: Mapped["Communication"] = relationship()
    needs_item: Mapped["NeedsItem"] = relationship()

    def __repr__(self) -> str:
        return f"<CommunicationNeedsItem {self.communication_id}/{self.needs_item_id}>"
