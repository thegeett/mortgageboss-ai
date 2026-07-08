"""Rule evaluators (LP-120) — run a ready-to-run rule's check → FINDING or SATISFIED.

The evaluator FRAMEWORK (the contract every rule follows) is :mod:`.contract`; dispatch is
:mod:`.registry`; the AS-5 gift-letter evaluator (:mod:`.gift_letter`) is the reference. Importing
this package registers the built-in evaluators, so the runner (LP-121) can dispatch by ``rule_id``.

Evaluators are pure readers of the frozen fact snapshot — no DB, no AI, no recompute at eval time.
They produce finding / satisfied, and MAY return couldn't-check when the data is present but
undeterminable (doesn't-apply stays LP-119's job). See :mod:`.contract`.
"""

from app.verification.evaluators.bank_statement_continuity import (
    BankStatementContinuityEvaluator,
)
from app.verification.evaluators.contract import (
    ConfidenceMode,
    EvaluationResult,
    Evaluator,
    Provenance,
    Verdict,
    computed_confidence,
    computed_result,
    deterministic_couldnt_check,
    deterministic_finding,
    deterministic_satisfied,
)
from app.verification.evaluators.employer_count import EmployerCountEvaluator
from app.verification.evaluators.gift_letter import GiftLetterEvaluator
from app.verification.evaluators.large_deposit import LargeDepositEvaluator
from app.verification.evaluators.registry import (
    ensure_registered,
    evaluate_rule,
    get_evaluator,
    register,
    registered_rule_ids,
)

# Eager, explicit registration on package import (idempotent). Consumers that reach the registry by
# another path get the same population via ``ensure_registered`` (FIX 10) — no reliance on this
# side effect alone.
ensure_registered()

__all__ = [
    "BankStatementContinuityEvaluator",
    "ConfidenceMode",
    "EmployerCountEvaluator",
    "EvaluationResult",
    "Evaluator",
    "GiftLetterEvaluator",
    "LargeDepositEvaluator",
    "Provenance",
    "Verdict",
    "computed_confidence",
    "computed_result",
    "deterministic_couldnt_check",
    "deterministic_finding",
    "deterministic_satisfied",
    "ensure_registered",
    "evaluate_rule",
    "get_evaluator",
    "register",
    "registered_rule_ids",
]
