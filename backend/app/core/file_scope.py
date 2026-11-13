"""Which loan files a caller may see (LP-MB-Admin-06, ADR-446).

Visibility is a TYPE, not a flag. Every loan-file gate takes a :class:`FileScope` where it used to
take a bare ``company_id``, so a caller cannot have the company without the visibility decision: a
gate called with a UUID is a mypy error. :func:`app.models.helpers.scope_files` is the one place the
predicate is written.

The decision is made once per request, in :meth:`FileScope.for_actor`, when the request's ``Actor``
is built (``get_current_actor``): before anything in the request changes a user, so an admin who
turns the setting on sees the effect on their next request.

Background jobs do not go through these gates: each reads its file by id (``db.get(LoanFile, ...)``)
and shows nothing to a person, except the processor's copy, which applies the team rule itself
(``services/processor_copy``). :meth:`FileScope.system` is for a caller with no actor that does call
a gate; ``grep '.system('`` lists those unrestricted gate calls, and there are none in ``app``
today.

Pure: no database.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self
from uuid import UUID

from app.core.permissions import Permission, resolve_permissions

if TYPE_CHECKING:
    from app.models.user import User


class _Subject(Protocol):
    """What the decision reads: ``Actor`` satisfies it (read-only, as a frozen dataclass's fields
    are)."""

    @property
    def user(self) -> "User": ...
    @property
    def company_id(self) -> UUID: ...
    @property
    def permissions(self) -> frozenset[Permission]: ...


@dataclass(frozen=True)
class FileScope:
    """A company, and whose files in it.

    ``restricted_to_user_id`` None: every live file of the company. Otherwise only the files where
    that user holds a live ``loan_teams`` row.
    """

    company_id: UUID
    restricted_to_user_id: UUID | None

    @property
    def restricted(self) -> bool:
        return self.restricted_to_user_id is not None

    @classmethod
    def system(cls, company_id: UUID) -> Self:
        """Unrestricted, for a gate called with no person behind it (a job, a script, a test)."""
        return cls(company_id=company_id, restricted_to_user_id=None)

    @classmethod
    def for_actor(cls, actor: _Subject) -> Self:
        """Restricted to the actor's own files when the company restricts files to their team,
        unless the actor holds ``loan.view_all`` (admins) or was marked ``sees_all_loans``.

        A user with no roles holds no permission, so is restricted, and on no team sees nothing.
        ``actor.user.company`` must be loaded (``get_current_user`` loads it).
        """
        unrestricted = (
            not actor.user.company.settings_model.restrict_loans_to_team
            or Permission.LOAN_VIEW_ALL in actor.permissions
            or bool(actor.user.sees_all_loans)
        )
        return cls(
            company_id=actor.company_id,
            restricted_to_user_id=None if unrestricted else actor.user.id,
        )

    @classmethod
    def for_user(cls, user: "User") -> Self:
        """The scope ``user`` would get on a request, for the signed-in user's own view
        (``UserPublic.restricted``). The same decision as :meth:`for_actor`."""
        return cls.for_actor(
            _UserSubject(
                user=user,
                company_id=user.company_id,
                permissions=resolve_permissions(user.role_set, user.company.settings_model),
            )
        )


@dataclass(frozen=True)
class _UserSubject:
    user: "User"
    company_id: UUID
    permissions: frozenset[Permission]
