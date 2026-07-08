"""Evaluator registry (LP-120) — dispatch ``rule_id`` → its evaluator.

Adding a rule = register its evaluator here; the framework does not change. The runner (LP-121)
looks up a ready-to-run rule's evaluator by ``rule_id`` and calls it. An unregistered ``rule_id``
returns ``None`` (graceful — it simply isn't evaluated), never a crash.
"""

from __future__ import annotations

from typing import Any

from app.verification.evaluators.contract import EvaluationResult, Evaluator
from app.verification.fact_namespace.snapshot import FactNamespace

_REGISTRY: dict[str, Evaluator] = {}
_bootstrapped = False


def register(evaluator: Evaluator) -> None:
    """Register an evaluator under its ``rule_id`` (last registration wins)."""
    _REGISTRY[evaluator.rule_id] = evaluator


def ensure_registered() -> None:
    """Populate the registry with the built-in evaluators — explicit + idempotent (FIX 10).

    Every registry read goes through this, so the registry is reliably populated regardless of
    import path (a consumer importing ``registry`` directly, or calling ``evaluate_rule`` before
    the package ``__init__`` side-effect ran, still finds AS-5 registered). The evaluators are
    imported lazily here to avoid an import cycle (evaluator modules import the contract, not the
    registry).
    """
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    from app.verification.evaluators.bank_statement_continuity import (
        BankStatementContinuityEvaluator,
    )
    from app.verification.evaluators.gift_letter import GiftLetterEvaluator

    register(GiftLetterEvaluator())
    register(BankStatementContinuityEvaluator())  # AS-8 (LP-123R)


def get_evaluator(rule_id: str) -> Evaluator | None:
    """The evaluator for ``rule_id``, or ``None`` if none is registered."""
    ensure_registered()
    return _REGISTRY.get(rule_id)


def registered_rule_ids() -> frozenset[str]:
    """The rule_ids that currently have an evaluator."""
    ensure_registered()
    return frozenset(_REGISTRY)


def evaluate_rule(
    rule_id: str, snapshot: FactNamespace, params: dict[str, Any] | None = None
) -> EvaluationResult | None:
    """Evaluate a ready-to-run rule by ``rule_id``; ``None`` if it has no registered evaluator.

    Reads the frozen snapshot only — no DB, no AI. The caller (LP-121) supplies the rule's
    ``params`` from ``verification_rules`` (thresholds); ``None`` → ``{}``.
    """
    ensure_registered()
    evaluator = _REGISTRY.get(rule_id)
    if evaluator is None:
        return None
    return evaluator.evaluate(snapshot, params or {})
