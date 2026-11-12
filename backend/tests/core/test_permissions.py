"""The permission matrix, cell by cell (LP-MB-Admin-02, ADR-442).

`_MATRIX` is a SECOND COPY of the ticket's table, on purpose: `app/core/permissions.py` is the code's
copy, and a change to it that was not meant shows up here as a failing row. Change both together.
"""

import pytest
from app.core.permissions import Permission, resolve_permissions
from app.models.user import UserRole
from app.schemas.company import CompanySettings

A, LO, P = UserRole.ADMIN, UserRole.LOAN_OFFICER, UserRole.PROCESSOR
#: Granted only by its company setting. `loan.team.change` for a loan officer is "own files"; the
#: file check is LP-MB-Admin-05's, so at this layer the key is simply held.
SETTING = "setting"

_MATRIX: dict[str, dict[UserRole, bool | str]] = {
    "users.manage": {A: True, LO: False, P: False},
    "company.settings.manage": {A: True, LO: False, P: False},
    "audit.view": {A: True, LO: False, P: False},
    "lenders.manage": {A: True, LO: False, P: False},
    "overlays.manage": {A: True, LO: False, P: False},
    "mail.manage": {A: True, LO: False, P: False},
    "evidence.manage": {A: True, LO: False, P: False},
    "loan.create": {A: True, LO: True, P: SETTING},
    "loan.view_all": {A: True, LO: False, P: False},
    "loan.team.change": {A: True, LO: True, P: False},
    "borrower.invite": {A: True, LO: True, P: SETTING},
}

#: The company setting behind each SETTING cell.
_SETTING_FOR = {
    "loan.create": "processors_can_create_loans",
    "borrower.invite": "processors_can_invite_borrowers",
}


def test_the_matrix_names_exactly_the_eleven_keys() -> None:
    assert {p.value for p in Permission} == set(_MATRIX)
    assert len(_MATRIX) == 11


@pytest.mark.parametrize(
    ("key", "role", "expected"),
    [(key, role, cell) for key, row in _MATRIX.items() for role, cell in row.items()],
)
@pytest.mark.parametrize("setting_on", [True, False])
def test_every_cell(key: str, role: UserRole, expected: bool | str, setting_on: bool) -> None:
    """Every (role, key) cell, under both values of every setting.

    A plain cell must not move with any setting; a SETTING cell must follow its own.
    """
    settings = CompanySettings(
        processors_can_create_loans=setting_on, processors_can_invite_borrowers=setting_on
    )
    granted = Permission(key) in resolve_permissions(frozenset({role}), settings)

    assert granted is (setting_on if expected == SETTING else expected)


@pytest.mark.parametrize("key", sorted(_SETTING_FOR))
def test_a_setting_switches_only_its_own_cell(key: str) -> None:
    """Turning one setting off removes its key and leaves the other setting-driven key alone."""
    other = next(k for k in _SETTING_FOR if k != key)
    settings = CompanySettings(**{_SETTING_FOR[key]: False})

    granted = resolve_permissions(frozenset({P}), settings)

    assert Permission(key) not in granted
    assert Permission(other) in granted


def test_roles_add_up() -> None:
    """A processor who is also a loan officer holds `loan.create` even with the setting off."""
    settings = CompanySettings(processors_can_create_loans=False)

    granted = resolve_permissions(frozenset({P, LO}), settings)

    assert granted == resolve_permissions(frozenset({LO}), settings) | resolve_permissions(
        frozenset({P}), settings
    )
    assert Permission.LOAN_CREATE in granted
    assert resolve_permissions(frozenset({A, P}), settings) == frozenset(Permission)


def test_no_roles_grants_nothing() -> None:
    assert resolve_permissions(frozenset(), CompanySettings()) == frozenset()


def test_settings_default_and_keep_unknown_keys() -> None:
    """`{}` (every company today) takes the defaults; a key this model does not know survives."""
    assert CompanySettings.model_validate({}) == CompanySettings(
        processors_can_create_loans=True,
        processors_can_invite_borrowers=True,
        restrict_loans_to_team=False,
    )
    parsed = CompanySettings.model_validate({"some_future_flag": 3})
    assert parsed.model_dump()["some_future_flag"] == 3
