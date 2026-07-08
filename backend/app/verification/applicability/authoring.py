"""Applicability AUTHORING invariants (LP-119 FIX 6A, shared — review FIX 7).

The single canonical home for the structural invariants EVERY applicability author must satisfy —
whether the author is the seed generator (``generate_rule_seed``) OR an Alembic data migration that
writes an ``applicability`` dict directly. Previously the refi-scope invariant lived only in the seed
generator, so the "a refi scope can't exist without loan_purpose" guarantee was false for the migration
path. Import + call these wherever applicability JSON is authored so the guarantee holds everywhere.
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
