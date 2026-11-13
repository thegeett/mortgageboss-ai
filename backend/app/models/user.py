"""User model — a person who uses the system — and the roles they hold.

Each user belongs to exactly one company and holds one or more roles (ADR-440): the set lives in
``user_roles``, one row per role, and capability is the union. ``users.role`` is the single role of
LP-12, kept unread and unwritten for one release so the migration can be rolled back.

Email is globally unique (ADR-042):
it identifies the user across the whole system and determines their company at
login. Passwords are stored only as hashes (``hashed_password``); the actual
authentication logic arrives in LP-22.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin, utcnow
from app.models.enums import str_enum
from app.models.types import MediumStr, ShortStr
from app.verification.confidence import DEFAULT_AGGRESSION, AggressionLevel


class RowDensity(StrEnum):
    """How tall a table row is for this user (LP-UI-010).

    An ergonomic preference, not view state: a processor decides once and every
    dense surface follows. Compact is the default because the product is a
    worklist — at 28px rows a processor scanning forty files sees twenty-four of
    them rather than fifteen.
    """

    COMPACT = "compact"
    COMFORTABLE = "comfortable"
    RELAXED = "relaxed"


DEFAULT_DENSITY = RowDensity.COMPACT


class MailClient(StrEnum):
    """Where this processor writes their email (LP-855).

    NOTHING IN A BROWSER CAN DETECT THIS. There is no API that reports which mail client a person
    uses, so it is asked rather than guessed — once, on the first draft.

    `MAILTO` IS THE SAFE ANSWER AND THE DEFAULT. It hands the message to whatever the computer
    already opens, which is the right answer for Apple Mail, Thunderbird and a locally installed
    Outlook, and the only one that cannot be wrong. The two web routes are better when they are
    right and useless when they are not: opening Gmail for somebody who does not use Gmail puts
    them in a sign-in page holding a message they cannot send.
    """

    GMAIL = "gmail"
    #: `outlook.office.com` — a work or school account on Microsoft 365.
    OUTLOOK_WORK = "outlook_work"
    #: `outlook.live.com` — a personal outlook.com or hotmail.com account.
    OUTLOOK_PERSONAL = "outlook_personal"
    #: Whatever this computer opens. The fallback, and what "Not now" selects.
    MAILTO = "mailto"


#: Not `MAILTO`, and the distinction is the whole of LP-855's picker.
#:
#: NULL MEANS "NOBODY HAS BEEN ASKED", which is different from "they chose the desktop default".
#: The picker is shown once on the first draft and never again after an answer; storing `mailto`
#: on load would mean it was never shown, and storing it on dismissal would mean a processor who
#: closed the dialog by accident is never offered the choice again. Until they answer, the button
#: reads "Copy & open mail app" and behaves as `MAILTO`.
DEFAULT_MAIL_CLIENT: MailClient | None = None

if TYPE_CHECKING:
    from app.models.company import Company


class UserRole(StrEnum):
    """User roles determining permissions. A user holds one or more (ADR-440).

    PROCESSOR: does loan processing work.
    ADMIN: additionally manages users and lender configuration.
    LOAN_OFFICER: originates the loan; what it may do arrives with permission keys (LP-MB-Admin-02).

    Owner is not a role: ``companies.owner_user_id`` names one admin the app refuses to deactivate
    or demote.
    """

    PROCESSOR = "processor"
    ADMIN = "admin"
    LOAN_OFFICER = "loan_officer"


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """A user of the system, belonging to one company."""

    __tablename__ = "users"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    email: Mapped[MediumStr] = mapped_column(unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[ShortStr] = mapped_column(nullable=False)
    last_name: Mapped[ShortStr] = mapped_column(nullable=False)
    # LP-12's single role. Neither read nor written since LP-MB-Admin-01: `roles` is the source.
    # Kept (nullable) for one release so the migration can roll back; a later ticket drops it.
    role: Mapped[UserRole | None] = mapped_column(str_enum(UserRole), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # The user's default verification thoroughness (LP-79's aggression dial). A
    # per-file override can dial a specific file up/down; absent an override this
    # default applies. Balanced unless the user changes it.
    default_aggression_level: Mapped[AggressionLevel] = mapped_column(
        str_enum(AggressionLevel),
        default=DEFAULT_AGGRESSION,
        server_default=DEFAULT_AGGRESSION.value,
        nullable=False,
    )
    # The user's row density (LP-UI-010). Per USER, deliberately — not per view
    # and not per screen. See RowDensity.
    density: Mapped[RowDensity] = mapped_column(
        str_enum(RowDensity),
        default=DEFAULT_DENSITY,
        server_default=DEFAULT_DENSITY.value,
        nullable=False,
    )

    # Where this user put the document reviewer's two dividers (LP-UI-030), as
    # `[list_pct, canvas_pct]`; the fields pane takes the remainder. NULL means
    # never adjusted, which is deliberately different from "adjusted back to the
    # default" — the UI shows its own default rather than writing one on load.
    reviewer_pane_split: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)

    #: Where this processor writes their email (LP-855). NULL until they answer the picker.
    #:
    #: NULLABLE ON PURPOSE — see `DEFAULT_MAIL_CLIENT`. "Nobody has asked" and "they chose the
    #: desktop default" are different facts, and a column that could not tell them apart would
    #: either show the picker forever or never show it at all.
    mail_client: Mapped[MailClient | None] = mapped_column(
        str_enum(MailClient), nullable=True, default=None
    )

    # The profile an admin edits on People (LP-MB-Admin-03).
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    #: A loan officer's licensing. Accepted for anyone; the UI shows it for loan officers.
    nmls_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: Two-letter US state codes, validated in the request schema.
    licensed_states: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default=text("'[]'"), nullable=False
    )
    #: Sees every company file when files are restricted to their team (`FileScope.for_actor`,
    #: LP-MB-Admin-06).
    sees_all_loans: Mapped[bool] = mapped_column(
        default=False, server_default=false(), nullable=False
    )
    #: Set on a successful login, not on refresh. NULL: never signed in.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    # `foreign_keys` because `companies.owner_user_id` points back here, so the two tables are joined
    # by two paths and SQLAlchemy will not pick one.
    company: Mapped["Company"] = relationship(back_populates="users", foreign_keys=[company_id])
    # Loaded with the user: the app is async, and `get_current_user` must not lazy-load.
    roles: Mapped[list["UserRoleAssignment"]] = relationship(
        back_populates="user",
        foreign_keys="UserRoleAssignment.user_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def role_set(self) -> frozenset[UserRole]:
        """The roles this user holds. The one accessor: nothing reads `roles` rows or `role`."""
        return frozenset(assignment.role for assignment in self.roles)

    @property
    def is_owner(self) -> bool:
        """Whether this user is their company's owner. Needs `company` loaded."""
        return self.company.owner_user_id == self.id

    def __repr__(self) -> str:
        return f"<User {self.email} ({', '.join(sorted(self.role_set))})>"


class UserRoleAssignment(Base, UUIDMixin):
    """One role one user holds (ADR-440).

    No soft delete and no `updated_at`: revoking a role deletes the row, and the company audit log
    keeps the history.
    """

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_roles_user_id_role"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole), nullable=False)
    #: Who granted it; NULL = the system or the migration.
    granted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="roles", foreign_keys=[user_id])
