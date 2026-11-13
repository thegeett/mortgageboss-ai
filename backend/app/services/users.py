"""People in a company: list, edit, roles, deactivate, reactivate (LP-MB-Admin-03).

Every function takes an :class:`~app.api.dependencies.Actor` and checks ``users.manage`` first. Scope
is the actor's company: a user of another company is ``None``, which the API turns into a 404, so
another tenant's ids reveal nothing.

The rules (ticket table):

- **Own roles / own access.** Nobody changes their own roles or deactivates themselves.
- **The owner** (``companies.owner_user_id``) cannot be deactivated and cannot lose ADMIN here. There is
  no separate "last admin" rule: the owner is always an active admin, so a company always has one.
- **At least one role.** A person always holds one; reactivating keeps the roles they had.

Every change writes one ``company_audit_log`` row with before and after values, never a password or a
hash. A request that changes nothing writes nothing.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NoRoles, OwnerProtected, SelfDeactivation, SelfRoleChange
from app.core.permissions import Permission
from app.models.user import User, UserRole, UserRoleAssignment
from app.services.activity_log import field_changes
from app.services.authorization import ensure
from app.services.company_audit import AuditAction, log_company_action

if TYPE_CHECKING:
    from app.api.dependencies import Actor

#: The fields `update_user_details` may change. Email is the global identity (ADR-042): never here.
DETAIL_FIELDS = (
    "first_name",
    "last_name",
    "phone",
    "title",
    "nmls_id",
    "licensed_states",
    "sees_all_loans",
)


def _scoped(actor: "Actor") -> Any:
    return select(User).where(User.company_id == actor.company_id, User.deleted_at.is_(None))


def _owner_id(actor: "Actor") -> UUID | None:
    return actor.user.company.owner_user_id


async def list_users(
    db: AsyncSession,
    actor: "Actor",
    *,
    status: str | None = None,
    role: UserRole | None = None,
) -> list[User]:
    """The company's people, active and inactive, by name. ``status`` is ``active`` or ``inactive``."""
    ensure(actor, Permission.USERS_MANAGE)
    stmt = _scoped(actor)
    if status is not None:
        stmt = stmt.where(User.is_active.is_(status == "active"))
    if role is not None:
        stmt = stmt.where(
            User.id.in_(select(UserRoleAssignment.user_id).where(UserRoleAssignment.role == role))
        )
    stmt = stmt.order_by(User.first_name, User.last_name, User.email)
    return list(await db.scalars(stmt))


async def get_user(db: AsyncSession, actor: "Actor", user_id: UUID) -> User | None:
    """One person in the actor's company, or ``None``."""
    ensure(actor, Permission.USERS_MANAGE)
    user: User | None = await db.scalar(_scoped(actor).where(User.id == user_id))
    return user


async def _audit(
    db: AsyncSession,
    actor: "Actor",
    user: User,
    action: AuditAction,
    summary: str,
    changes: list[dict[str, Any]],
) -> None:
    await log_company_action(
        db,
        company_id=actor.company_id,
        actor_user_id=actor.user.id,
        action=action,
        target_type="user",
        target_id=user.id,
        summary=summary,
        detail={"changes": changes},
    )


async def update_user_details(
    db: AsyncSession, actor: "Actor", user_id: UUID, patch: dict[str, Any]
) -> User | None:
    """Apply the fields in ``patch`` (only what was sent). Anyone's details, the actor's own and
    the owner's included."""
    user = await get_user(db, actor, user_id)
    if user is None:
        return None
    sent = {field: value for field, value in patch.items() if field in DETAIL_FIELDS}
    changes = field_changes({field: getattr(user, field) for field in sent}, sent)
    if not changes:
        return user
    for field, value in sent.items():
        setattr(user, field, value)
    await db.flush()
    fields = ", ".join(change["field"].replace("_", " ") for change in changes)
    await _audit(
        db,
        actor,
        user,
        AuditAction.USER_DETAILS_CHANGED,
        f"Changed {user.full_name}: {fields}",
        changes,
    )
    return user


async def set_user_roles(
    db: AsyncSession, actor: "Actor", user_id: UUID, roles: set[UserRole]
) -> User | None:
    """Replace the person's roles with ``roles``: removed rows deleted, added rows granted by the actor."""
    user = await get_user(db, actor, user_id)
    if user is None:
        return None
    if user.id == actor.user.id:
        raise SelfRoleChange()
    if not roles:
        raise NoRoles()
    if user.id == _owner_id(actor) and UserRole.ADMIN not in roles:
        raise OwnerProtected()
    before, after = sorted(user.role_set), sorted(roles)
    if before == after:
        return user
    for assignment in list(user.roles):
        if assignment.role not in roles:
            user.roles.remove(assignment)  # delete-orphan: the row is deleted
    for role in after:
        if role not in before:
            user.roles.append(UserRoleAssignment(role=role, granted_by_user_id=actor.user.id))
    await db.flush()
    await _audit(
        db,
        actor,
        user,
        AuditAction.USER_ROLES_CHANGED,
        f"Changed {user.full_name}'s roles",
        field_changes({"roles": before}, {"roles": after}),
    )
    return user


async def deactivate_user(db: AsyncSession, actor: "Actor", user_id: UUID) -> User | None:
    """End the person's access on their next request or refresh (both read ``is_active`` live).

    Roles, history and authorship stay. Already inactive: nothing happens.
    """
    user = await get_user(db, actor, user_id)
    if user is None:
        return None
    if user.id == actor.user.id:
        raise SelfDeactivation()
    if user.id == _owner_id(actor):
        raise OwnerProtected()
    if not user.is_active:
        return user
    user.is_active = False
    await db.flush()
    await _audit(
        db,
        actor,
        user,
        AuditAction.USER_DEACTIVATED,
        f"Deactivated {user.full_name}",
        field_changes({"status": "active"}, {"status": "inactive"}),
    )
    return user


async def reactivate_user(db: AsyncSession, actor: "Actor", user_id: UUID) -> User | None:
    """Give the person access again, with the roles they had. Already active: nothing happens."""
    user = await get_user(db, actor, user_id)
    if user is None:
        return None
    if user.is_active:
        return user
    user.is_active = True
    await db.flush()
    await _audit(
        db,
        actor,
        user,
        AuditAction.USER_REACTIVATED,
        f"Reactivated {user.full_name}",
        field_changes({"status": "inactive"}, {"status": "active"}),
    )
    return user
