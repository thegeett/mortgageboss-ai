"""Evaluator contract (LP-120) — the shared shape EVERY rule evaluator follows.

Where LP-119 answers "should this rule run?" (doesn't-apply / couldn't-check / ready-to-run), the
EVALUATOR answers "what's the verdict?" — for a READY-TO-RUN rule only, it produces **FINDING** or
**SATISFIED**. This module is the contract the ~125 rule evaluators inherit; getting it right here
means rules #2..N just fill in the check.

The invariants (read these before writing an evaluator):

* **Pure reader of the FROZEN snapshot.** An evaluator takes the LP-118.6 fact snapshot (values
  already computed, canonicalized, and frozen) + the rule's ``params`` (thresholds from the table),
  and returns a result. It MUST NOT recompute LTV/DTI, re-canonicalize, hit the DB, or call AI at
  evaluation time — that would break determinism + auditability. A value that isn't in the snapshot
  is an applicability/couldn't-check concern (LP-119), not the evaluator's.
* **Confidence modes.** A **deterministic** check (letter present? DTI over limit?) →
  :data:`DETERMINISTIC_CONFIDENCE` (1.0). A **computed** check (fuzzy name/employer match,
  canonicalization-fed) → a computed confidence **strictly below 1.0** — clean match high,
  ambiguous lower ("possible variation — verify"); **never a false 100%**. AS-5 is deterministic,
  but the computed path exists here for IN-5 / blocker-fed rules.
* **Provenance.** Every result records WHICH snapshot facts it read + what it observed, so the trust
  surface (LP-140) can show why the verdict was reached.

This produces finding/satisfied ONLY — never couldn't-check/doesn't-apply (those are LP-119). It
does not persist anything or build a ``Finding`` model (the runner, LP-121, maps the result +
the rule row's severity/category onto a finding).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.verification.confidence import DETERMINISTIC_CONFIDENCE
from app.verification.fact_namespace.snapshot import FactNamespace

# The ceiling for a COMPUTED (fuzzy) confidence — a fuzzy match must never assert a false 100%.
COMPUTED_CONFIDENCE_CEILING = 0.99
# Below this, a computed match is advisory ("possible variation — verify"), not a hard finding.
COMPUTED_VERIFY_THRESHOLD = 0.70


class Verdict(StrEnum):
    """An evaluator's outcome for a ready-to-run rule."""

    FINDING = "finding"  # a problem was found (e.g. gift funds present but no gift letter)
    SATISFIED = "satisfied"  # checked, all good


class ConfidenceMode(StrEnum):
    """How the confidence was arrived at — deterministic (exact) vs computed (fuzzy/match-quality)."""

    DETERMINISTIC = "deterministic"
    COMPUTED = "computed"


class Provenance(BaseModel):
    """One fact the evaluator read + what it observed — the audit trail for the verdict."""

    model_config = ConfigDict(frozen=True)
    path: str  # the snapshot path examined, e.g. "assets[].is_gift"
    observed: str  # what was found (human-readable)


class EvaluationResult(BaseModel):
    """The structured output of one evaluator — verdict + message + confidence + provenance."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    verdict: Verdict
    message: str
    confidence: float
    confidence_mode: ConfidenceMode
    provenance: list[Provenance]
    # Optional APPLY→recompute spec (the LP-76/83 interlock — e.g. undisclosed-debt adds a
    # liability). None for a plain surfaced finding like AS-5. Present here so the contract supports
    # it without every evaluator needing it.
    apply_spec: dict[str, Any] | None = None


@runtime_checkable
class Evaluator(Protocol):
    """The interface every rule evaluator implements (dispatched by ``rule_id``, LP-120 registry).

    ``evaluate`` is a PURE, synchronous reader of the frozen snapshot — no DB, no AI, no recompute.
    """

    rule_id: str

    def evaluate(self, snapshot: FactNamespace, params: dict[str, Any]) -> EvaluationResult: ...


# --------------------------------------------------------------------------- #
# Result builders (keep evaluators terse + consistent)
# --------------------------------------------------------------------------- #


def deterministic_finding(
    rule_id: str,
    message: str,
    *,
    provenance: list[Provenance],
    apply_spec: dict[str, Any] | None = None,
) -> EvaluationResult:
    """A FINDING from a deterministic (exact) check — full confidence."""
    return EvaluationResult(
        rule_id=rule_id,
        verdict=Verdict.FINDING,
        message=message,
        confidence=DETERMINISTIC_CONFIDENCE,
        confidence_mode=ConfidenceMode.DETERMINISTIC,
        provenance=provenance,
        apply_spec=apply_spec,
    )


def deterministic_satisfied(
    rule_id: str, message: str, *, provenance: list[Provenance]
) -> EvaluationResult:
    """A SATISFIED verdict from a deterministic (exact) check — full confidence."""
    return EvaluationResult(
        rule_id=rule_id,
        verdict=Verdict.SATISFIED,
        message=message,
        confidence=DETERMINISTIC_CONFIDENCE,
        confidence_mode=ConfidenceMode.DETERMINISTIC,
        provenance=provenance,
    )


def computed_confidence(quality: float) -> float:
    """Clamp a fuzzy match-quality to a COMPUTED confidence — capped below 1.0 (never a false 100%).

    The computed path for IN-5 (employer match) / blocker-fed rules: a clean match → high (but < 1.0);
    an ambiguous one → lower; below :data:`COMPUTED_VERIFY_THRESHOLD` it is advisory.
    """
    return max(0.0, min(quality, COMPUTED_CONFIDENCE_CEILING))


def computed_result(
    rule_id: str,
    verdict: Verdict,
    message: str,
    *,
    quality: float,
    provenance: list[Provenance],
) -> EvaluationResult:
    """A result from a COMPUTED (fuzzy) check — confidence derived from match quality (< 1.0)."""
    return EvaluationResult(
        rule_id=rule_id,
        verdict=verdict,
        message=message,
        confidence=computed_confidence(quality),
        confidence_mode=ConfidenceMode.COMPUTED,
        provenance=provenance,
    )
