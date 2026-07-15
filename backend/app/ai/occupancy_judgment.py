"""OC-2 judgment types — a thin compat shim over the GENERIC judge (LP-324).

OC-2's judgment call is now the generic :func:`app.ai.rule_judgment.reason_rule_judgment` (the prompt
lives in ``OC-2.yaml``, not here). These aliases keep the historical type names importable; the
former OC-2-specific prompt + defensive parse are deleted (they generalized).
"""

from __future__ import annotations

from app.ai.client import AIClientError
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult

# Backward-compatible aliases — the generic judgment types under their old OC-2 names.
OccupancyJudgment = RuleJudgment
OccupancyJudgmentResult = RuleJudgmentResult

# OC-2's value domain (also carried as data in OC-2.yaml's judgment.value_domain).
OCCUPANCY_REASONABLE_VALUES = ("yes", "no", "unknown")

__all__ = [
    "OCCUPANCY_REASONABLE_VALUES",
    "AIClientError",
    "OccupancyJudgment",
    "OccupancyJudgmentResult",
]
