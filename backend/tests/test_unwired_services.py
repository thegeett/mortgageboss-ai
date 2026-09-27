"""A service function that nothing in production calls (LP-848 review).

WHY THIS EXISTS, AND IT IS NOT ABOUT DEAD CODE. Four times in this run of communication tickets a
feature was built correctly, tested thoroughly, and connected to nothing: LP-840's invalidation of a
query key no component read, LP-845's broadcast listener that no client registered, LP-848's staleness
heal that no read path called, and the regeneration guard whose four other entrances this review
found. Every one passed its own tests, because a test calls the function directly — which is exactly
the thing production was failing to do.

So the check is structural rather than behavioural: a function in `app/services/` whose name is never
loaded anywhere in `app/`, `alembic/` or `scripts/`. Tests calling it does not count, and that is the
entire point — "tests call it, nothing else does" IS the defect shape.

WHAT THIS CANNOT SEE, stated rather than implied. A name reached by `getattr`, by string dispatch
through a registry, or re-exported and then called through a module attribute would read as unwired
here. Two such entries are in the baseline below with that noted. The check is a ratchet, not a
proof: it cannot tell you the 27 below are wrong, only that nobody added a 28th without saying so.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _loaded_names(*roots: str) -> set[str]:
    """Every identifier loaded or attribute-accessed under these trees."""
    names: set[str] = set()
    for root in roots:
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:  # pragma: no cover - a tree we cannot parse tells us nothing
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
    return names


def _service_functions() -> list[tuple[str, int, str]]:
    """Undecorated module-level functions in `app/services/`.

    DECORATED ONES ARE SKIPPED because a decorator is itself a wiring mechanism — a route, a task, a
    validator — and its name is legitimately never called.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "app" / "services").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.decorator_list or node.name.startswith("__"):
                continue
            found.append((str(path.relative_to(ROOT)), node.lineno, node.name))
    return found


def _unwired() -> set[str]:
    production = _loaded_names("app", "alembic", "scripts")
    return {name for _f, _l, name in _service_functions() if name not in production}


# Every service function with no production caller, as of the LP-848 review. A name comes OFF this
# list when it is wired up, and goes ON it only with a reason — which is the whole mechanism.
KNOWN_UNWIRED = {
    # Phase 4, awaiting the screen that will call them. LP-831 builds the drafts list and is the
    # caller `remove_need_from_draft` was written for; its own docstring says so.
    "open_drafts",
    "remove_need_from_draft",
    "create_communication",
    # Phase 4 inbound/bounce handling: reached once SES is out of the sandbox and the webhook is
    # wired, which INFRA-2/3 gate on a human.
    "parse_ses_bounce",
    "record_delivery_failure",
    "record_auto_reply",
    "record_received",
    "record_delivery_failed",
    "is_participant",
    # Legal hold: the evidence side is built, the purge paths that must consult it are not.
    "refuse_if_held",
    "held_file_ids",
    # `register` IS the wiring mechanism — a provider calls it at import time. §5 says build the
    # interface and ship no provider, so today only tests register one. This is the one entry whose
    # emptiness is the decision rather than a gap.
    "register",
    # Rule-engine and extraction surfaces with no caller in the request path today.
    "run_cross_source",
    "ingest_suggested_need",
    "satisfy_needs_item",
    "resolve_finding",
    "persist_evaluation_findings",
    "find_field_boxes",
    "observe_unmapped",
    "top_graduation_candidates",
    "observations_for_finding",
    "pending_review_observations",
    "resolve_style",
    "set_style_profile",
    # No caller AND no test. Dead since the ticket named, left alone by this review because deleting
    # code three tickets outside the blast radius is how a review becomes a refactor.
    "_is_borrower_facing",  # LP-809
    "open_draft_preview",  # LP-811a
    "existing_identities",  # LP-93
}


def test_no_service_function_is_wired_to_nothing() -> None:
    """A new entry here means something was built and connected to nothing. Wire it, or add it to
    `KNOWN_UNWIRED` with the reason it is waiting."""
    unwired = _unwired()
    assert sorted(unwired - KNOWN_UNWIRED) == [], (
        "built but reachable from no production caller — wire it up, or record why it waits"
    )
    # THE OTHER DIRECTION, so the list cannot rot into a fiction: a name that got wired up must come
    # off, otherwise the baseline slowly stops describing anything.
    assert sorted(KNOWN_UNWIRED - unwired) == [], (
        "these are wired up now — remove them from the list"
    )


def test_the_scan_itself_works() -> None:
    """THE POSITIVE CONTROL. The assertions above are satisfied by a scan that finds nothing and by
    one that finds everything, so pin both ends: a function with obvious production callers must not
    be reported, and a function whose own docstring says it has no caller must be."""
    functions = _service_functions()
    assert len(functions) > 400, (
        "the scan found almost no functions; it is not looking where it thinks"
    )

    unwired = _unwired()
    # `send_draft` is called by the send endpoint. If this is reported, the scan is broken.
    assert "send_draft" not in unwired
    # `remove_need_from_draft` says "the function has no caller today" in its own docstring.
    assert "remove_need_from_draft" in unwired
