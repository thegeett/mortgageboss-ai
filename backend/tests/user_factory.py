"""The one way a test builds a `User` (LP-MB-Admin-01).

A user's roles are rows in `user_roles` (ADR-440), not a column, so a test that wrote `role=...`
now names the set. This only builds: the caller adds and flushes as before, and the role rows go
with the user through the relationship's cascade.
"""

from collections.abc import Iterable
from typing import Any

from app.models.user import User, UserRole, UserRoleAssignment


def make_user(*, roles: Iterable[UserRole], **fields: Any) -> User:
    """A `User` holding `roles`; every other keyword goes to the model unchanged."""
    return User(**fields, roles=[UserRoleAssignment(role=role) for role in roles])
