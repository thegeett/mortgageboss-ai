"""Applicability AUTHORING invariants (LP-119 FIX 6A; shared helper).

The canonical home for the structural invariants an applicability author must satisfy — most importantly
"a ``refinance_type`` scope can never exist without ``loan_purpose``".

SCOPE OF ENFORCEMENT (honest — round-5 FIX 5): the **seed generator** (``generate_rule_seed``) routes
EVERY emitted applicability through :func:`finalize_applicability`, so the invariant is guaranteed there.
It is NOT automatically applied to Alembic data migrations that hand-author an ``applicability`` dict — a
migration authoring a ``refinance_type`` scope MUST call :func:`enforce_refi_scope_invariant` itself (it
raises on a missing/contradictory ``loan_purpose``). No current migration authors a refi-type scope; if
one does, call the helper. (This docstring previously claimed migrations were covered automatically — they
are not.)
"""

from __future__ import annotations

from typing import Any


def enforce_refi_scope_invariant(scope: dict[str, list[str]]) -> dict[str, list[str]]:
    """A ``refinance_type`` scope can NEVER exist without its ``loan_purpose`` (round-3 FIX 6A).

    Whenever a scope constrains ``refinance_type``, ``loan_purpose:["refinance"]`` is co-emitted — so a
    refi-type-scoped rule resolves DOESN'T-APPLY on a purchase (loan_purpose mismatch) via the generic
    FALSE-precedence path, never a false couldn't-check. Enforced at CONSTRUCTION (here), not by an
    engine special-case. A contradictory explicit ``loan_purpose`` fails LOUD.
    """
    if not scope.get("refinance_type"):
        return scope
    loan_purpose = scope.get("loan_purpose")
    if loan_purpose and loan_purpose != ["refinance"]:
        raise ValueError(
            f"refinance_type scope requires loan_purpose=['refinance'], got {loan_purpose!r}"
        )
    # loan_purpose FIRST for readability; refinance_type (+ any other dims) follow.
    return {"loan_purpose": ["refinance"], **scope}


def finalize_applicability(app: dict[str, Any]) -> dict[str, Any]:
    """Apply the structural invariants every emitted applicability must satisfy (round-3 FIX 6A)."""
    scope = app.get("scope")
    if isinstance(scope, dict):
        app = {**app, "scope": enforce_refi_scope_invariant(scope)}
    return app
