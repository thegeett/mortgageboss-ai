"""One processor's writing voice, so a draft sounds like them (LP-822).

Spec 4.1 asks that drafted emails match the processor's voice. That requirement collides with
LP-810's central design decision, which scopes the per-draft fact bundle to "the requested needs
plus borrower name and file basics — nothing else", on bug-008's lesson that a wide bundle reworded
every draft whenever anything in it changed.

**The resolution is two caches, not one wider bundle.** Voice belongs to a PERSON and changes when
they edit it. Facts belong to a DRAFT and change when the file does. Keyed together, editing a
signature block would invalidate every draft's content, and a new document on a file would re-derive
a voice that did not move. Keyed apart, each invalidates on its own terms — which is why this table
is keyed on ``user_id`` and carries no loan-file reference at all.

**No ``company_id``.** The profile hangs off exactly one user, and a user carries their company, so
scoping is transitive — the same reasoning ADR-052 applies to file-owned children, applied to a
user-owned row. A denormalised copy would be a second answer to "which company is this?" that can
drift from the first when a person moves, for a column no query here needs: every read is "the
profile for this authenticated user".
"""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import String

from app.models.base import Base, TimestampMixin, UUIDMixin
from app.models.types import MediumStr

if TYPE_CHECKING:
    from app.models.user import User

#: The longest an exemplar may be. Exemplars illustrate VOICE — how a request opens, how a chase
#: stays warm — and a paragraph shows that as well as a whole thread does. The cap is also a
#: containment measure: see the warning in `exemplars` below.
MAX_EXEMPLAR_CHARS = 1200

#: How many exemplars are useful. The plan says "two or three"; more is not a richer voice, it is a
#: longer prompt and more places for a borrower's details to hide.
MAX_EXEMPLARS = 3


class StyleProfile(Base, UUIDMixin, TimestampMixin):
    """The greeting, closing, signature and exemplars one processor writes with.

    Deliberately NOT soft-deletable. There is one row per user and the way to stop using it is to
    clear it or delete it outright; a soft-deleted profile would leave a drafter choosing between a
    tombstone and the default, and the safe answer to "no profile" is already the default.
    """

    __tablename__ = "style_profiles"

    #: One profile per user. UNIQUE, and CASCADE on delete: a voice with nobody to belong to is not
    #: a record worth keeping, and it holds nothing about a loan file that anyone would audit.
    #: No separate `index=True`: `unique=True` already builds a unique btree index on this
    #: column, and a second non-unique one on the same column is writes and storage for nothing.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    #: How they open. Contains ``$borrower_first_name`` where a name goes, matching the template
    #: library's placeholder convention so one substitution pass covers both.
    greeting: Mapped[MediumStr] = mapped_column(nullable=False)
    #: How they sign off — "Thanks," / "Best regards," / "Kind regards,".
    closing: Mapped[MediumStr] = mapped_column(nullable=False)
    #: The block under the closing: name, title, company, phone. Multi-line, so Text.
    #:
    #: DELIBERATELY NOT PASSED THROUGH `validate_exemplars`, and the asymmetry is the point rather
    #: than an oversight: a signature block is SUPPOSED to carry a phone number and an email address
    #: — the processor's own. The exemplar guard exists to catch a THIRD PARTY's identifiers in
    #: pasted text; running it here would refuse every real signature. Do not "fix" the
    #: inconsistency by extending the guard to this column.
    signature_block: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: Two or three short excerpts showing how this person writes.
    #:
    #: THESE MUST BE REDACTED BEFORE THEY ARE STORED, and that is a real constraint rather than a
    #: preference. The spec's collection list asks Priya for "examples of her current borrower-request
    #: emails (templates and actual sends)", and an actual send contains a borrower's name, their
    #: address, and what they owe. An exemplar is put in front of the model on EVERY draft, for every
    #: borrower — so one borrower's details stored here can surface in another borrower's email, and
    #: no amount of prompt instruction reliably prevents it.
    #:
    #: `services.style_profile.validate_exemplars` refuses the identifier shapes it can recognise.
    #: That is a tripwire for the obvious cases, NOT a guarantee: it matches shapes, and a name is
    #: not shaped like anything. The control that actually holds is that whoever enters an exemplar
    #: redacts it first.
    exemplars: Mapped[list[str]] = mapped_column(
        ARRAY(String(MAX_EXEMPLAR_CHARS)), nullable=False, default=list
    )

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<StyleProfile user_id={self.user_id}>"
