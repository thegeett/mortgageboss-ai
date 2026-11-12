"""The service-side permission check (LP-MB-Admin-02, ADR-442).

Routes gate with ``require_permission``; a service that takes an :class:`~app.api.dependencies.Actor`
checks with :func:`ensure`. Both read the same resolved set, so the matrix in
:mod:`app.core.permissions` is the only answer. The refusal is a domain error;
``app.core.errors`` turns it into the same 403 a route dependency gives.
"""

from typing import TYPE_CHECKING

from app.core.permissions import Permission, PermissionDeniedError

if TYPE_CHECKING:
    # Type-only: a service must not import the API layer at runtime.
    from app.api.dependencies import Actor


def ensure(actor: "Actor", permission: Permission) -> None:
    """Raise :class:`PermissionDeniedError` unless ``actor`` holds ``permission``."""
    if permission not in actor.permissions:
        raise PermissionDeniedError(permission)
