"""Who may do what: the permission matrix as data (LP-MB-Admin-02, ADR-442).

Code asks "may this actor do X?" by a named :class:`Permission`, never "is this user an admin?".
Roles are compared HERE and nowhere else: route dependencies (``require_permission``) and services
(``ensure``) both go through :func:`resolve_permissions`. Changing who may do something is a change to
the two tables below.

Pure: no database and no imports from ``app.api``, so the matrix can be tested on its own.
"""

from enum import StrEnum
from typing import TYPE_CHECKING

from app.models.user import UserRole

if TYPE_CHECKING:
    from app.core.company_settings import CompanySettings


class Permission(StrEnum):
    """One thing an actor may do. Sent to the frontend as its value."""

    USERS_MANAGE = "users.manage"
    COMPANY_SETTINGS_MANAGE = "company.settings.manage"
    AUDIT_VIEW = "audit.view"
    LENDERS_MANAGE = "lenders.manage"
    OVERLAYS_MANAGE = "overlays.manage"
    MAIL_MANAGE = "mail.manage"
    EVIDENCE_MANAGE = "evidence.manage"
    LOAN_CREATE = "loan.create"
    LOAN_VIEW_ALL = "loan.view_all"
    #: For a loan officer, on their own files only: the file check is LP-MB-Admin-05's.
    LOAN_TEAM_CHANGE = "loan.team.change"
    #: No call site yet: the seam for the borrower portal, so it does not invent its own.
    BORROWER_INVITE = "borrower.invite"


class PermissionDeniedError(Exception):
    """The actor lacks a permission. The API maps it to 403 ``Insufficient permissions``."""

    def __init__(self, permission: Permission) -> None:
        super().__init__(f"missing permission {permission.value}")
        self.permission = permission


#: What each role grants, whatever the company's settings.
ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.ADMIN: frozenset(Permission),
    UserRole.LOAN_OFFICER: frozenset(
        {Permission.LOAN_CREATE, Permission.LOAN_TEAM_CHANGE, Permission.BORROWER_INVITE}
    ),
    UserRole.PROCESSOR: frozenset(),
}

#: The cells a company setting switches: role → {permission: the `CompanySettings` field that grants
#: it}. The setting's field name, not a function, so the table stays data.
CONFIG_PERMISSIONS: dict[UserRole, dict[Permission, str]] = {
    UserRole.PROCESSOR: {
        Permission.LOAN_CREATE: "processors_can_create_loans",
        Permission.BORROWER_INVITE: "processors_can_invite_borrowers",
    },
}


def resolve_permissions(
    roles: frozenset[UserRole], settings: "CompanySettings"
) -> frozenset[Permission]:
    """Everything any of ``roles`` grants, plus each setting-driven cell whose setting is on.

    Roles add up (ADR-440). No roles grants nothing.
    """
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
        for permission, setting in CONFIG_PERMISSIONS.get(role, {}).items():
            if getattr(settings, setting):
                granted.add(permission)
    return frozenset(granted)


#: Grants a role holds only on files where its holder is the loan officer: the matrix's "own files"
#: cell (LP-MB-Admin-05). The same key held through another role is not limited.
OWN_FILES_ONLY: dict[UserRole, frozenset[Permission]] = {
    UserRole.LOAN_OFFICER: frozenset({Permission.LOAN_TEAM_CHANGE}),
}


def may_change_team(roles: frozenset[UserRole], *, is_files_loan_officer: bool) -> bool:
    """Whether someone holding ``roles`` may change this file's team.

    Admin: any file. A loan officer: only a file where they are the loan officer. Holding
    `loan.team.change` alone is not enough, because the loan officer's grant is scoped to their files.
    """
    for role in roles:
        if Permission.LOAN_TEAM_CHANGE not in ROLE_PERMISSIONS[role]:
            continue
        if Permission.LOAN_TEAM_CHANGE not in OWN_FILES_ONLY.get(role, frozenset()):
            return True
        if is_files_loan_officer:
            return True
    return False
