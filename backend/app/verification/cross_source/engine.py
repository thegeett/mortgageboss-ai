"""The deterministic cross-source evaluation loop (LP-86) — read across sources → diff → emit.

The cross-source counterpart to :func:`app.verification.engine.evaluate`. For each
:class:`~app.verification.cross_source.rules.CrossSourceRule` applicable to the file's
program, run its pure ``check`` against the :class:`~app.verification.cross_source.facts.CrossSourceFacts`
snapshot and turn each :class:`~app.verification.cross_source.rules.CrossSourceMatch` into a
:class:`CrossSourceFinding` with TEMPLATED wording (the rule's fixed template filled with
the match's fields — identical every run, the consistency win).

This module is pure (no DB, no AI): given the same facts it returns the same findings in
the same order, every time — the deterministic graduation. The service layer
(:mod:`app.services.cross_source_deterministic`) builds the facts from the assembled
stated-vs-verified context and maps these results onto the shared Finding model with
``origin=deterministic_rule``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.lender import LoanProgram
from app.verification.cross_source.facts import CrossSourceFacts
from app.verification.cross_source.rules import CROSS_SOURCE_RULES, CrossSourceRule


@dataclass(frozen=True)
class CrossSourceFinding:
    """One deterministic cross-source discrepancy — a fired rule + its templated message.

    ``message`` is the rule's template filled with the match's fields (fixed wording).
    ``subject_key`` distinguishes multiple findings from one rule (stable identity).
    ``stated_value`` / ``document_value`` carry onto the finding details (and feed the
    APPLY→recompute spec for the undisclosed-debt rule).
    """

    rule: CrossSourceRule
    subject_key: str
    message: str
    stated_value: str | None
    document_value: str | None


def _applies_to(rule: CrossSourceRule, program: LoanProgram | None) -> bool:
    """A program-agnostic rule (``program is None``) applies to any file; else it must match."""
    return rule.program is None or rule.program is program


def evaluate_cross_source(
    facts: CrossSourceFacts,
    *,
    program: LoanProgram | None = None,
    rules: Sequence[CrossSourceRule] = CROSS_SOURCE_RULES,
) -> list[CrossSourceFinding]:
    """Evaluate every applicable cross-source rule against the facts. Pure, no AI.

    Runs each rule's ``check`` (skipping rules gated to a different program), fills the
    rule's template with each match's fields, and returns one :class:`CrossSourceFinding`
    per match. A rule whose inputs are absent simply yields no matches (graceful absence —
    the engine never invents a discrepancy). Deterministic: same facts → same findings.
    """
    results: list[CrossSourceFinding] = []
    for rule in rules:
        if not _applies_to(rule, program):
            continue
        for match in rule.check(facts, rule.threshold):
            results.append(
                CrossSourceFinding(
                    rule=rule,
                    subject_key=match.subject_key,
                    message=rule.template.format(**match.fields),
                    stated_value=match.stated_value,
                    document_value=match.document_value,
                )
            )
    return results
