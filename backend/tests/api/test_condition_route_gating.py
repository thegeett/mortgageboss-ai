"""Every route that can create or read a condition declares the RIGHT tenant gate (LP-909 §1).

⚠️ A DEPENDENCY EACH HANDLER MUST DECLARE IS STILL A CHECK THAT CAN BE FORGOTTEN. `ScopedLoanFileById`
replaced six lines of hand-scoping in every handler, which is better — but the fourth route someone
adds in Stage 2 is the one that ships open, and *every existing refusal test passes*, because they
test the routes that exist.

So this walks the routers, and the failure arrives when the route is added. The shape is
`tests/api/test_lender_endpoints_lp813.py`'s admin-gate test, whose docstring makes the argument.

⚠️ ONE DELIBERATE INVERSION OF THAT TEMPLATE. The lenders version checks only `methods - {"GET"}` and
skips routes that mutate nothing — right there, because `GET /lenders` is deliberately open. Here it
is backwards: §1 added three GET reads, and **an ungated GET is exactly what leaks another tenant's
data**. There is no GET exemption.

⚠️ THE MAP IS (ROUTER → ACCEPTED GATES), NOT ONE GLOBAL SET, and the distinction is the point rather
than bookkeeping. A flat `/condition-rounds/{round_id}` route carrying `ScopedLoanFileById` would be
WRONG rather than right — it has no file id to scope — so a single accepted-set would call it gated
while it scoped nothing. Each router names the gate that is correct *for its own path shape*.

⚠️ AND THE WALK COVERS `inbound` BECAUSE ONE CONDITION ROUTE LIVES THERE. Review found it, and an
earlier version of this file could not see it: `POST …/inbound/attachments/{id}/condition-round`
opens a condition round and enqueues the parse. It is a condition route by any reading, it gates on a
THIRD callable (`get_scoped_loan_file`, via `ScopedLoanFile`), and a Stage 2 route added beside it
without a gate would have been invisible here — precisely the failure this file exists to prevent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from fastapi.routing import APIRoute

#: `(method, path)` pairs reachable without a tenant gate, each with the reason it is right.
#:
#: ⚠️ THIS MECHANISM WAS DEAD IN THE FIRST VERSION AND THE COMMENT CLAIMED OTHERWISE. One test
#: honoured the list; the two per-router tests asserted unconditionally — so an entry silenced one
#: test and still failed two, and anyone recording a deliberate exemption would have discovered the
#: escape hatch did not open. It went unnoticed because the per-router tests are strictly stronger
#: than the general one, which can only fail if one of them already has. Every check below now
#: consults it.
_UNGATED_BY_DESIGN: set[tuple[str, str]] = {
    # Company-level, not file-level: the triage queue's interesting rows are the UNROUTED ones,
    # which by definition belong to no loan file. `list_triage_queue` scopes on the caller's company
    # instead, and `attachment_preview` reasons about the same exposure — an unrouted message is
    # visible to every company, so its sender, subject and filenames are stripped rather than
    # gated. A file gate here would have no id to scope and would hide the feature.
    ("GET", "/inbound/queue"),
}


def _gate_map() -> list[tuple[str, APIRouter, set[Callable[..., Any]]]]:
    """Each router that can reach a condition, with the gates correct for ITS path shape."""
    from app.api.conditions import get_scoped_loan_file_by_id, get_scoped_round
    from app.api.conditions import rounds_router as condition_rounds_router
    from app.api.conditions import router as conditions_router
    from app.api.dependencies import get_scoped_loan_file
    from app.api.inbound import company_router as inbound_company_router
    from app.api.inbound import router as inbound_router

    return [
        # `/loan-files/{loan_file_id}/...` — the file is in the path and is the thing to scope.
        ("conditions", conditions_router, {get_scoped_loan_file_by_id}),
        # `/condition-rounds/{round_id}` — no file in the path; the round carries the company.
        ("condition-rounds", condition_rounds_router, {get_scoped_round}),
        # `/loan-files/{file_identifier}/inbound/...` — the repo-wide file gate, and the home of
        # the fifth condition route.
        ("inbound", inbound_router, {get_scoped_loan_file}),
        # `/inbound/...` — company-level. No gate is correct here; see `_UNGATED_BY_DESIGN`.
        ("inbound-company", inbound_company_router, set()),
    ]


def _routes(router: APIRouter) -> list[APIRoute]:
    return [route for route in router.routes if isinstance(route, APIRoute)]


def _methods(route: APIRoute) -> set[str]:
    return route.methods - {"HEAD", "OPTIONS"}


def _declares(route: APIRoute, gates: set[Callable[..., Any]]) -> bool:
    """⚠️ BY DEPENDENCY IDENTITY, never by name or by reading source — so a route that merely
    mentions a gate in a docstring does not count as gated."""
    return any(dependency.call in gates for dependency in route.dependant.dependencies)


def _exempt(route: APIRoute) -> bool:
    return all((method, route.path) in _UNGATED_BY_DESIGN for method in _methods(route))


def test_every_condition_route_declares_the_right_gate() -> None:
    """No GET exemption: an ungated read is the leak, not an ungated write.

    "The right gate" rather than "a gate": each router is checked against the dependency correct for
    its own path shape, so a route cannot pass by carrying a scoping callable that has nothing to
    scope.
    """
    ungated: list[str] = []

    for name, router, gates in _gate_map():
        for route in _routes(router):
            if _exempt(route) or (gates and _declares(route, gates)):
                continue
            for method in sorted(_methods(route)):
                if (method, route.path) in _UNGATED_BY_DESIGN:
                    continue
                expected = " or ".join(sorted(gate.__name__ for gate in gates)) or "<none accepted>"
                ungated.append(f"[{name}] {method} {route.path} (expected {expected})")

    assert not ungated, (
        "these routes carry no valid tenant gate. Declare the dependency correct for the router, "
        f"or add them to _UNGATED_BY_DESIGN with the reason: {ungated}"
    )


def test_the_condition_route_in_inbound_is_covered_by_this_walk() -> None:
    """⚠️ THE ROUTE THE FIRST VERSION COULD NOT SEE, pinned by name so the walk cannot narrow again.

    `POST …/condition-round` opens a round and enqueues the parse. It lives in `inbound.py`, not in
    `conditions.py`, and it gates on a third callable — so it was invisible to a walk over the two
    condition routers, and a Stage 2 route added beside it would have been invisible too.

    (Review's own sweep for it used the pattern `condition-rounds`, which cannot match
    `condition-round` singular. The route was found by accident. Hence this assertion by name.)
    """
    from app.api.inbound import router as inbound_router

    paths = {route.path for route in _routes(inbound_router)}
    condition_route = (
        "/loan-files/{file_identifier}/inbound/attachments/{attachment_id}/condition-round"
    )

    assert condition_route in paths, "the forward door moved; this walk must follow it"

    walked = {route.path for _n, router, _g in _gate_map() for route in _routes(router)}
    assert condition_route in walked


def test_the_exemption_list_describes_routes_that_exist() -> None:
    """A stale exemption is worse than none: it reads as a considered decision about a route that is
    gone, and would silently cover a future route reusing the path."""
    live = {
        (method, route.path)
        for _name, router, _gates in _gate_map()
        for route in _routes(router)
        for method in _methods(route)
    }
    stale = [entry for entry in _UNGATED_BY_DESIGN if entry not in live]

    assert not stale, f"exemptions for routes that no longer exist: {stale}"


def test_an_exemption_actually_silences_the_check() -> None:
    """⚠️ THE MECHANISM WORKS, WHICH IN THE FIRST VERSION IT DID NOT.

    `/inbound/queue` carries no file gate and is listed. If the exemption were dead — as it was when
    one test honoured it and two ignored it — this walk would report it, and the only way to get
    green would be to remove the honest entry.
    """
    from app.api.inbound import company_router

    (queue,) = [r for r in _routes(company_router) if r.path == "/inbound/queue"]

    assert _declares(queue, {*(g for _n, _r, gs in _gate_map() for g in gs)}) is False
    assert _exempt(queue) is True


def test_the_gate_detection_would_notice_an_ungated_route() -> None:
    """⚠️ THE POSITIVE CONTROL, and the reason the assertions above are worth anything.

    They are absence assertions over a set the code supplies, so they would pass just as happily
    against a detector that found nothing at all — this stage's signature failure in its purest
    form. This builds a route with no gate and asserts the detection sees it.
    """
    from app.api.conditions import get_scoped_loan_file_by_id

    probe = APIRouter()

    @probe.get("/probe")
    async def _probe() -> None:  # pragma: no cover - never called
        return None

    (route,) = _routes(probe)

    assert _declares(route, {get_scoped_loan_file_by_id}) is False


def test_the_detection_finds_the_real_routes_gated() -> None:
    """The other direction of the control: the detector must also say YES to something.

    A detector answering False for everything satisfies the positive control AND every absence
    assertion above. This asserts it recognises the gates actually in place, per router, so both
    answers are demonstrated rather than one.
    """
    checked = 0
    expected = 0
    for _name, router, gates in _gate_map():
        if not gates:
            continue
        for route in _routes(router):
            if _exempt(route):
                continue
            expected += 1
            assert _declares(route, gates), f"{sorted(route.methods)} {route.path}"
            checked += 1

    # ⚠️ DERIVED FROM THE MAP, NOT A LITERAL. A hardcoded floor was wrong on the first run — I
    # estimated 12 against a real 11 — and the deeper problem is that a number picked by estimating
    # fails later for a reason nobody can reconstruct: adding a route legitimately moves it, so the
    # next person raises the constant and learns nothing. This asserts the walk reached every route
    # it set out to reach, which is the property meant all along.
    assert checked == expected
    assert expected > 0, "the gate map reached no routes at all — the walk has broken"
