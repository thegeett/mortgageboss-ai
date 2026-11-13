"""Two guards for LP-MB-Admin-02's seams: one effective company, one 403.

1. `get_current_company_id` is the only place that decides which company a request acts in (ADR-443).
   The ~100 existing `current_user.company_id` uses are out of scope to move, so they are frozen
   here by FILE: a file not on the allowlist that starts using it fails. New code uses
   `CurrentCompanyId` or `actor.company_id`.
2. A service's `ensure` refusal reaches the client as the same 403 a route gate gives.
"""

import re
from pathlib import Path
from uuid import uuid4

import pytest
from app.api.dependencies import Actor
from app.core.errors import register_exception_handlers
from app.core.permissions import Permission, PermissionDeniedError
from app.models.company import Company
from app.models.user import User, UserRole
from app.services.authorization import ensure
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_API = Path(__file__).resolve().parents[2] / "app" / "api"
_USE = re.compile(r"\bcurrent_user\.company_id\b")

#: The files that used `current_user.company_id` when LP-MB-Admin-02 landed. LP-MB-Admin-05's
#: follow-up moves them onto `CurrentCompanyId` and EMPTIES this set; nothing is ever added to it.
#: LP-MB-Admin-06 took eight off: their file gates now take `CurrentScope` (ADR-446).
#: `dependencies.py` is here because `get_current_actor` is where the effective company is decided.
_ALLOWED = frozenset(
    {
        "capabilities.py",
        "dependencies.py",
        "documents.py",
        "inbound.py",
        "lenders.py",
        "loan_files.py",
        "mailbox_connections.py",
        "overlay_admin.py",
        "saved_views.py",
        "validation_aid.py",
    }
)


def _users() -> set[str]:
    return {p.name for p in _API.glob("*.py") if _USE.search(p.read_text(encoding="utf-8"))}


def test_no_new_file_reads_current_user_company_id() -> None:
    new = sorted(_users() - _ALLOWED)
    assert not new, (
        f"{new} read `current_user.company_id`. Use `CurrentCompanyId` or `actor.company_id`: "
        "`get_current_company_id` is the one place that decides the effective company (ADR-443)."
    )


def test_the_allowlist_holds_only_files_that_still_need_it() -> None:
    """A file that stopped using it comes off the list, so the list only shrinks."""
    assert len(_ALLOWED) == 10
    stale = sorted(_ALLOWED - _users())
    assert not stale, f"no longer read `current_user.company_id`; remove from _ALLOWED: {stale}"


def _actor(*permissions: Permission) -> Actor:
    return Actor(
        # A company with default settings: building an Actor decides its file scope (ADR-446).
        user=User(company=Company(settings={})),
        company_id=uuid4(),
        roles=frozenset({UserRole.PROCESSOR}),
        permissions=frozenset(permissions),
        is_owner=False,
    )


def test_ensure_passes_a_held_permission_and_refuses_another() -> None:
    ensure(_actor(Permission.LOAN_CREATE), Permission.LOAN_CREATE)
    with pytest.raises(PermissionDeniedError) as excinfo:
        ensure(_actor(Permission.LOAN_CREATE), Permission.USERS_MANAGE)
    assert excinfo.value.permission is Permission.USERS_MANAGE


async def test_a_refusal_from_a_service_is_the_same_403_as_a_route_gate() -> None:
    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/probe")
    async def _probe() -> None:
        ensure(_actor(), Permission.USERS_MANAGE)

    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test") as client:
        resp = await client.get("/probe")

    assert resp.status_code == 403
    assert resp.json() == {"error": {"type": "forbidden", "message": "Insufficient permissions"}}
