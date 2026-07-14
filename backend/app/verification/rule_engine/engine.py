"""The thin deterministic rule engine (LP-315) — dispatches AS-1 over the tagged snapshot.

Minimal by design: load a rule's spec + its threshold, enumerate its subjects, and for each run
the fail-closed gate then the rule, collecting an in-memory :class:`RuleEvaluation`. No AI (the
tags were produced in LP-313/314), no persistence (findings are LP-316). Today it dispatches only
AS-1 (per-deposit); the shape generalizes to more rules later.
"""

from __future__ import annotations

import re
from decimal import Decimal

from app.ai.extraction.parsing import coerce_decimal
from app.verification.rule_engine.as1 import evaluate_as1
from app.verification.rule_engine.result import RuleEvaluation
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.snapshot.traversal import all_transactions

# The confidence floor below which a load-bearing tag routes a verdict to needs_review. The AS-1
# spec carries no floor field yet, so this default applies — PRIYA-CONFIRMABLE, like the threshold.
DEFAULT_CONFIDENCE_FLOOR = 0.5

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_INCOME_KEY = "gross_monthly_income"


def _threshold_multiplier(large_deposit_threshold: str) -> Decimal | None:
    """Extract the multiplier from the spec's prose threshold (e.g. '50% of …' → 0.5).

    The AS-1 spec stores the threshold as prose (``reference_values.large_deposit_threshold``); the
    percentage is the machine part. Returns ``None`` if no percentage is present (→ couldnt_check).
    """
    match = _PERCENT.search(large_deposit_threshold or "")
    if match is None:
        return None
    return Decimal(match.group(1)) / Decimal(100)


def _qualifying_income(snapshot: Snapshot) -> Decimal | None:
    """The loan-level monthly qualifying income, from the DTI calculator (or None if unavailable)."""
    calculations = snapshot.calculations
    if calculations.absent or calculations.dti is None:
        return None
    return coerce_decimal(calculations.dti.value.get(_INCOME_KEY))


def evaluate_as1_rule(
    snapshot: Snapshot, *, confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR
) -> list[RuleEvaluation]:
    """Evaluate AS-1 over every transaction subject in a tagged snapshot (one result per subject).

    Reads AS-1's spec (``load_rule_spec`` — threshold multiplier + priya_validated), the qualifying
    income (DTI calculator), and the per-deposit tags (Stage A/B). Each subject runs the gate then
    the rule. Deterministic: same snapshot → same results.
    """
    spec = load_rule_spec("AS-1")
    multiplier = _threshold_multiplier(spec.reference_values.large_deposit_threshold)
    priya_validated = spec.reference_values.priya_validated
    income = _qualifying_income(snapshot)

    tags_absent = snapshot.tags.absent
    results: list[RuleEvaluation] = []
    for txn in all_transactions(snapshot):
        subject_tags = {} if tags_absent else snapshot.tags.by_subject.get(txn.content_id, {})
        results.append(
            evaluate_as1(
                txn.content_id,
                subject_tags,
                # A missing multiplier (no percentage in the spec prose) is passed through as
                # None; the rule returns couldnt_check rather than comparing against a fabricated
                # number — no argument-nulling trick needed.
                threshold_multiplier=multiplier,
                qualifying_income=income,
                priya_validated=priya_validated,
                confidence_floor=confidence_floor,
            )
        )
    return results
