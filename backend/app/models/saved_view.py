"""Saved views — a named, reusable filter over the pipeline (LP-UI-015).

A saved view is what replaces the dashboard's four hard-coded pills: "Blocked to
submit", "Docs stale > 30d", "Ready to submit" are things a processing company
decides for itself, not things the product should enumerate.

**Scoping.** Every view belongs to a company and has an owner. `is_shared`
decides who else in that company sees it — a private view is the owner's alone,
a shared one is the team's. Company scoping is the same discipline as everywhere
else: the company is never taken from the request, only from the caller.

**The filter payload is JSON on purpose.** The set of things a processor filters
on will grow, and a column per filter would mean a migration per idea. It is
validated at the API boundary by `SavedViewFilters` rather than being free-form:
JSON here means "extensible", not "unchecked".
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
from app.models.enums import str_enum
from app.models.types import MediumStr

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.user import User


class SavedViewSort(StrEnum):
    """How a view orders its rows.

    ``ATTENTION`` is the pipeline's default (LP-UI-013) — most urgent first.
    The others exist because a saved view is also how someone builds a report,
    and "oldest first" is a different question from "worst first".
    """

    ATTENTION = "attention"
    UPDATED_DESC = "updated_desc"
    UPDATED_ASC = "updated_asc"
    AMOUNT_DESC = "amount_desc"


DEFAULT_SORT = SavedViewSort.ATTENTION


class SavedView(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """One named filter over the pipeline, owned by a user within a company."""

    __tablename__ = "saved_views"
    __table_args__ = (
        # A person should not end up with two views of the same name; two people
        # in the same company may. Scoped to the owner, not the company.
        #
        # PARTIAL, not a UniqueConstraint over (owner, name, deleted_at). In
        # Postgres a unique key containing a NULL treats every such row as
        # distinct, so two LIVE views — both with deleted_at NULL — did not
        # collide and the constraint enforced nothing it claimed. Verified by
        # inserting the duplicate before this changed. `postgresql_where` is the
        # same idiom `uq_findings_loan_file_rule_subject` uses for the same
        # reason, and it still frees the name on delete.
        Index(
            "uq_saved_views_owner_name",
            "owner_user_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    name: Mapped[MediumStr] = mapped_column(nullable=False)

    #: Validated at the API boundary by ``SavedViewFilters``. See the module
    #: docstring: JSON for extensibility, not to avoid validation.
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    sort: Mapped[SavedViewSort] = mapped_column(
        str_enum(SavedViewSort),
        default=DEFAULT_SORT,
        server_default=DEFAULT_SORT.value,
        nullable=False,
    )

    #: Shared views are visible to the whole company; private ones only to the
    #: owner. Sharing is the point — "Blocked to submit" is the same question
    #: for everyone, and N personal copies of it drift.
    is_shared: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    company: Mapped["Company"] = relationship()
    owner: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        shared = "shared" if self.is_shared else "private"
        return f"<SavedView {self.name!r} {shared} owner={self.owner_user_id}>"
