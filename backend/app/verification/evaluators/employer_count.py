"""Employer-count-matches-income-items evaluator (LP-124R) — REPRODUCES a LIVE rule.

``xsrc.income.employer_count_matches_items`` is one of the 5 live, firing cross-source rules
(``docs/audits/live-rule-inventory-corrected.md``). This reproduces it in the new engine, so the LIVE
rule is the parity anchor — the verdict must MATCH ``_check_employer_count``
(``app/verification/cross_source/rules.py``), not merely seem reasonable.

STEP 0 — the reproduced spec (read from the live rule + its fact-builder,
``services/cross_source_deterministic.py:225-258``):

* **Comparison (FILE-LEVEL, across all borrowers):** the number of stated EMPLOYERS that have a name
  (``len(employers[].name truthy)``) vs the number of employment INCOME ITEMS
  (``income_items[] where employment_income is truthy``). The live rule flattens both across every
  borrower — it is NOT per-borrower — so this reproduction is file-level too (matching, not "improving").
* **Pass/fail:** both counts non-zero AND EQUAL → no finding; both non-zero and UNEQUAL → FINDING. Exact
  integer equality — NO tolerance/threshold.
* **Zero case — INTENTIONAL stricter-than-live divergence (round-5 FIX 9, Geet's decision):** the live
  rule is SILENT when either count is 0. The new engine treats a ZERO-ON-ONE-SIDE (employers but no
  employment income, or vice versa) as a FINDING — a loan file always has MISMO/initial income detail, so
  a missing side is a real discrepancy. Both sides zero (a genuinely no-employment file) → satisfied. This
  divergence is deliberate — do NOT revert it to match live.

Deterministic (exact count) → full confidence. Reads the frozen snapshot (stated borrower facts). Counts
only — no employer NAMES flow into the outcome (ADR-150).
"""

from __future__ import annotations

from typing import Any

from app.verification.evaluators.contract import (
    ConfidenceMode,
    EvaluationResult,
    Provenance,
    deterministic_finding,
    deterministic_satisfied,
)
from app.verification.fact_namespace.snapshot import FactNamespace

RULE_ID = "xsrc.income.employer_count_matches_items"


class EmployerCountEvaluator:
    """Employer count vs employment income-item count, file-level (LP-124R — reproduces the live rule)."""

    rule_id = RULE_ID
    confidence_mode = (
        ConfidenceMode.DETERMINISTIC
    )  # exact count — the seed's source of truth (FIX 7)

    def evaluate(self, snapshot: FactNamespace, params: dict[str, Any]) -> EvaluationResult:
        # FILE-LEVEL counts, mirroring the live fact-builder: employers WITH a name; income items whose
        # employment_income is truthy (None/False are not employment — same as the live `if` truthiness).
        employer_count = sum(
            1 for borrower in snapshot.borrowers for employer in borrower.employers if employer.name
        )
        income_item_count = sum(
            1
            for borrower in snapshot.borrowers
            for item in borrower.income_items
            if item.employment_income
        )
        provenance = [
            Provenance(
                path="borrowers[].employers[].name",
                observed=f"{employer_count} named employer(s)",
            ),
            Provenance(
                path="borrowers[].income_items[].employment_income",
                observed=f"{income_item_count} employment income item(s)",
            ),
        ]

        # INTENTIONAL divergence from the live rule (round-5 FIX 9, Geet's product decision): the live
        # rule is SILENT when either count is 0 (its None-guard). But a loan file is always created with
        # MISMO / initial income detail, so a ZERO-ON-ONE-SIDE (employers but no employment income, or
        # employment income but no employers) is a real DISCREPANCY → FINDING, not couldn't-check and not
        # silence. The new engine is deliberately STRICTER here; do NOT revert this to match live. (Both
        # sides zero = a genuinely no-employment file → not a discrepancy → satisfied via the equal path.)
        if (employer_count == 0) != (income_item_count == 0):
            return deterministic_finding(
                self.rule_id,
                f"{employer_count} named employer(s) but {income_item_count} employment income item(s) "
                "— one side is absent, which is a discrepancy to reconcile.",
                provenance=provenance,
            )
        if employer_count == income_item_count:
            return deterministic_satisfied(
                self.rule_id,
                f"Employer count ({employer_count}) reconciles with the employment income-item count "
                f"({income_item_count}).",
                provenance=provenance,
            )
        return deterministic_finding(
            self.rule_id,
            f"Stated employer count ({employer_count}) does not match the employment income-item count "
            f"({income_item_count}).",
            provenance=provenance,
        )
