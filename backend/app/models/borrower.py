"""Borrower model — a person applying on a loan file (LP-14).

A loan file has one or more borrowers: a primary borrower and zero or more
co-borrowers (a married couple, a parent co-signing, etc.). They are ordered on
the file by :attr:`Borrower.borrower_position`, and exactly one is flagged
:attr:`Borrower.is_primary`.

This model introduces two firsts for the schema:

  * **A one-to-many off the loan file** — :class:`~app.models.loan_file.LoanFile`
    gains a ``borrowers`` collection. Borrowers are *owned* by the file: the FK
    is ``ondelete=CASCADE`` so a (rare) hard-delete of a file removes its
    borrowers, though the normal flow soft-deletes (see :class:`SoftDeleteMixin`).

  * **Encrypted PII at rest** — the SSN, the most sensitive field in the system
    (GLBA-covered), is stored with :class:`~app.models.encrypted_types.
    EncryptedString`: ciphertext in the database, plaintext in Python, the key
    only in settings (ADR-051). The SSN must never reach a log, repr, or error —
    see :meth:`__repr__` and :attr:`masked_ssn`.

**Company scoping is transitive** (ADR-052): a borrower has no ``company_id`` of
its own. It belongs to a company only *through* its loan file. Tenant-isolated
queries scope the loan file (``scope_to_company(stmt, LoanFile, company_id)``)
and join/filter borrowers by ``loan_file_id`` — a borrower is reachable only via
a file the company owns. The same applies to :class:`~app.models.property.
Property`.
"""

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.encrypted_types import EncryptedString
from app.models.enums import str_enum
from app.models.types import MEDIUM_STRING, SHORT_STRING

if TYPE_CHECKING:
    from app.models.loan_file import LoanFile


class MaritalStatus(StrEnum):
    """Borrower marital status.

    Mirrors the URLA (form 1003) categories, which split unmarried into
    "unmarried" and "separated" because they differ for property-rights and
    spousal-consent purposes.
    """

    MARRIED = "married"
    UNMARRIED = "unmarried"
    SEPARATED = "separated"


class Borrower(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A borrower or co-borrower on a loan file.

    Names are required (a borrower is, minimally, a named person); everything
    else is nullable because details arrive incrementally (manual entry, a
    MISMO import, document extraction). The SSN in particular is frequently
    unknown at creation and filled in later.
    """

    __tablename__ = "borrowers"

    # --- Ownership ---------------------------------------------------------
    # Borrowers are owned by their loan file: ondelete=CASCADE means a hard
    # delete of the file removes them too. Normal operation soft-deletes
    # (deleted_at), so cascade only bites on a genuine hard delete.
    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # --- Identity ----------------------------------------------------------
    first_name: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    last_name: Mapped[str] = mapped_column(String(SHORT_STRING), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    # SSN — encrypted at rest (ADR-051). Stored as ciphertext in a text column;
    # read/written as plaintext here. Nullable: often unknown at creation.
    ssn: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)

    # Date of birth is sensitive but NOT encrypted in V1: it is needed for
    # ordering/credit-pull matching and is far lower-risk than the SSN. We keep
    # the encryption surface to the single highest-value field for now;
    # broadening it is a deliberate later decision (ADR-051).
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- Contact -----------------------------------------------------------
    email: Mapped[str | None] = mapped_column(String(MEDIUM_STRING), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(SHORT_STRING), nullable=True)

    # --- Application attributes -------------------------------------------
    marital_status: Mapped[MaritalStatus | None] = mapped_column(
        str_enum(MaritalStatus), nullable=True
    )

    # Exactly one borrower per file is the primary; the rest are co-borrowers.
    # Not enforced by a DB constraint in V1 (a partial unique index could come
    # later); set by the service that creates borrowers.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 1-based ordering of borrowers on the file (primary is typically 1).
    borrower_position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # --- Relationships -----------------------------------------------------
    loan_file: Mapped["LoanFile"] = relationship(back_populates="borrowers")

    @property
    def full_name(self) -> str:
        """The borrower's full name, skipping an absent middle name."""
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(part for part in parts if part)

    @property
    def masked_ssn(self) -> str | None:
        """The SSN masked for display as ``***-**-1234`` (last 4 only).

        Returns ``None`` if the SSN is unset. Strips any formatting so it works
        whether the stored value is ``123-45-6789`` or ``123456789``. This is
        the ONLY form of the SSN that should ever reach a UI or log.
        """
        if not self.ssn:
            return None
        digits = "".join(char for char in self.ssn if char.isdigit())
        return f"***-**-{digits[-4:]}"

    def __repr__(self) -> str:
        # NEVER include the SSN or full PII (name, DOB) in the repr — reprs end
        # up in logs and tracebacks. Identify by position + owning file only.
        return (
            f"<Borrower position={self.borrower_position} "
            f"primary={self.is_primary} loan_file_id={self.loan_file_id}>"
        )
