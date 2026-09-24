"""Every condition route declares a tenant gate (LP-909 §1, review).

⚠️ A DEPENDENCY EACH HANDLER MUST DECLARE IS STILL A CHECK THAT CAN BE FORGOTTEN. `ScopedLoanFileById`
replaced the same six lines of hand-scoping in every handler, which is better — but the fourth read
endpoint someone adds in Stage 2 is the one that ships without it, and *every existing refusal test
passes*, because they test the routes that exist.

So this walks the routers instead, and the failure arrives when the route is added rather than when
someone notices. The shape is `tests/api/test_lender_endpoints_lp813.py`'s admin-gate test, whose
docstring states the argument better than this one could.

⚠️ ONE DELIBERATE DIFFERENCE FROM THAT TEMPLATE, AND COPYING IT UNCHANGED WOULD HAVE GATED NOTHING.
The lenders version checks only `methods - {"GET"}` and `continue`s when a route mutates nothing —
correct there, because `GET /lenders` is deliberately open to every processor. Here it is exactly
backwards: §1 adds three GET reads, and **a GET is precisely what leaks another tenant's data when
ungated**. There is no GET exemption below.

⚠️ AND TWO ACCEPTED DEPENDENCIES, NOT ONE. `/loan-files/{loan_file_id}/...` routes gate on the file;
the flat `/condition-rounds/{round_id}` routes have no loan file in the path and gate on the round.
A flat route carrying `ScopedLoanFileById` would be wrong rather than right — it would have no id to
scope — which `tests/models/test_condition_tenancy.py` reasons about directly.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.routing import APIRoute

#: `(method, path)` pairs deliberately reachable without a tenant gate, each with its reason.
#: Empty, and that is the honest state: every condition route today is scoped. An entry here is a
#: recorded decision, never an omission — which is the whole point of having the list at all.
_UNGATED_BY_DESIGN: set[tuple[str, str]] = set()


def _condition_routes() -> list[APIRoute]:
    """Both routers, walked together — the file-scoped one and the flat one."""
    from app.api.conditions import rounds_router, router

    return [
        route for route in [*router.routes, *rounds_router.routes] if isinstance(route, APIRoute)
    ]


def _gates() -> tuple[object, object]:
    from app.api.conditions import get_scoped_loan_file_by_id, get_scoped_round

    return get_scoped_loan_file_by_id, get_scoped_round


def _is_gated(route: APIRoute) -> bool:
    """⚠️ BY DEPENDENCY IDENTITY, never by name or by reading source — so a route that merely
    mentions the gate in a docstring does not count as gated."""
    by_file, by_round = _gates()
    return any(
        dependency.call is by_file or dependency.call is by_round
        for dependency in route.dependant.dependencies
    )


def test_every_condition_route_declares_a_tenant_gate() -> None:
    """No GET exemption: an ungated read is the leak, not an ungated write."""
    ungated: list[str] = []

    for route in _condition_routes():
        if _is_gated(route):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) in _UNGATED_BY_DESIGN:
                continue
            ungated.append(f"{method} {route.path}")

    assert not ungated, (
        "these condition routes carry no tenant gate. Declare `ScopedLoanFileById` (file-scoped "
        "paths) or `ScopedRound` (flat paths), or add them to _UNGATED_BY_DESIGN with the reason: "
        f"{ungated}"
    )


def test_the_flat_routes_gate_on_the_round_not_the_file() -> None:
    """⚠️ THE RIGHT GATE, NOT MERELY A GATE. `/condition-rounds/{round_id}` carries no loan file, so
    `ScopedLoanFileById` has nothing to scope there — it would need an id the path does not have.
    The two routers therefore accept different dependencies, and this pins which."""
    from app.api.conditions import get_scoped_round, rounds_router

    for route in rounds_router.routes:
        if not isinstance(route, APIRoute):
            continue
        assert any(
            dependency.call is get_scoped_round for dependency in route.dependant.dependencies
        ), f"{sorted(route.methods)} {route.path} must gate on the round"


def test_the_file_scoped_routes_gate_on_the_file() -> None:
    """The other half, so neither router can drift onto the wrong dependency."""
    from app.api.conditions import get_scoped_loan_file_by_id, router

    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        assert any(
            dependency.call is get_scoped_loan_file_by_id
            for dependency in route.dependant.dependencies
        ), f"{sorted(route.methods)} {route.path} must gate on the loan file"


def test_the_exemption_list_describes_routes_that_exist() -> None:
    """A stale exemption is worse than none: it reads as a considered decision about a route that is
    gone, and would silently cover a future route reusing the path."""
    live = {
        (method, route.path)
        for route in _condition_routes()
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    stale = [entry for entry in _UNGATED_BY_DESIGN if entry not in live]

    assert not stale, f"exemptions for routes that no longer exist: {stale}"


def test_the_gate_detection_would_notice_an_ungated_route() -> None:
    """⚠️ THE POSITIVE CONTROL, AND THE REASON THE THREE ABOVE ARE WORTH ANYTHING.

    All three are absence assertions over a set the code supplies, so they would pass just as
    happily against a detector that found nothing at all — which is this stage's signature failure
    in its purest form. This builds a route with no gate and asserts the detection sees it.
    """
    probe = APIRouter()

    @probe.get("/probe")
    async def _probe() -> None:  # pragma: no cover - never called
        return None

    (route,) = [r for r in probe.routes if isinstance(r, APIRoute)]

    assert _is_gated(route) is False


def test_the_detection_finds_the_real_routes_gated() -> None:
    """The other direction of the control: the detector must also say YES to something.

    A detector that answered False for everything would satisfy the positive control above and the
    absence assertions too. This asserts it actually recognises the gates in place — so both
    answers are demonstrated rather than one.
    """
    routes = _condition_routes()

    assert routes, "expected condition routes to exist"
    assert all(_is_gated(route) for route in routes)
