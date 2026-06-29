"""The deterministic evaluation loop (LP-74) — read → compare → emit.

For each rule in the resolved effective set: read the file's typed field, compare
it to the rule's (possibly overlay-patched) threshold with the fixed
:func:`~app.verification.rules.schema.satisfies` logic, and emit a pass/fail
result. This is the *"deterministic code judges"* half of the locked Phase-3
principle — the AI's role is upstream (extracting the values); the judgment here
is pure, auditable, and correct by construction.

This module is pure: it takes a :class:`~app.verification.facts.FileFacts`
snapshot and a sequence of rules and returns :class:`EngineFinding` results. It
does **not** touch the DB or the ORM — the service layer
(:mod:`app.services.verification_engine`) builds the facts, resolves the rules,
calls :func:`evaluate`, and maps the results onto the shared Finding model.

A rule whose datum is absent is returned with ``evaluated=False`` (no value to
judge) — the engine never invents a pass/fail; the caller decides what to do
with un-evaluated rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.verification.facts import FileFacts
from app.verification.rules.schema import VerificationRule, satisfies


@dataclass(frozen=True)
class EngineFinding:
    """The result of evaluating one rule against one file's facts.

    ``evaluated`` is ``False`` when the file carried no value for the rule to
    read (so ``passed`` is meaningless and ``observed`` is ``None``). When
    ``evaluated`` is ``True``, ``passed`` is the deterministic verdict and
    ``observed`` is the typed value that was compared. ``source_location`` is the
    fact's audit anchor, carried through to the finding.
    """

    rule: VerificationRule
    evaluated: bool
    passed: bool
    observed: Decimal | int | None
    source_location: dict[str, object] | None


def _to_decimal(value: Decimal | int) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(value)


def evaluate(facts: FileFacts, rules: Sequence[VerificationRule]) -> list[EngineFinding]:
    """Evaluate every rule against the file's typed facts. Pure, no AI.

    Reads each rule's typed field from ``facts``, compares it to the rule's
    (possibly overlay-patched) threshold, and returns one
    :class:`EngineFinding` per rule. Rules whose datum is absent come back
    ``evaluated=False``.
    """
    results: list[EngineFinding] = []
    for rule in rules:
        # Applicability gate (LP-83): a manual-only / condo-only rule applies only when
        # its gate fact holds. Not applicable (or unknown) → not-evaluated, never a finding.
        if rule.gate is not None and not _gate_open(facts, rule):
            results.append(
                EngineFinding(
                    rule=rule, evaluated=False, passed=False, observed=None, source_location=None
                )
            )
            continue
        fact = facts.read(rule.reads)
        if fact is None or fact.value is None:
            results.append(
                EngineFinding(
                    rule=rule,
                    evaluated=False,
                    passed=False,
                    observed=None,
                    source_location=None,
                )
            )
            continue
        passed = satisfies(rule.condition, _to_decimal(fact.value))
        results.append(
            EngineFinding(
                rule=rule,
                evaluated=True,
                passed=passed,
                observed=fact.value,
                source_location=fact.source,
            )
        )
    return results


def _gate_open(facts: FileFacts, rule: VerificationRule) -> bool:
    """True when the rule's applicability gate holds (so the rule should be evaluated)."""
    gate = rule.gate
    if gate is None:
        return True
    gate_fact = facts.read((gate.reads,))
    if gate_fact is None or gate_fact.value is None:
        return False  # gate fact unknown → not applicable (conservative)
    return satisfies(gate.condition, _to_decimal(gate_fact.value))
