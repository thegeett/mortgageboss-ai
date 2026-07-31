"""LP-431 — IH-1 (insurance adequacy) is BLOCKED on an extractor extension; it was deliberately NOT built.

Priya's ruling replaced the planned coverage-vs-loan arithmetic with a loss-settlement-BASIS check
(replacement_cost_basis: true → adequate / false → inadequate / missing → manual review), retiring the
80%-of-replacement-cost comparison effective 2026-03-18 (ADR-340 — her domain ruling, on record for re-check).
But the `homeowners_insurance` extractor carries NO loss-settlement-basis field in its typed core, and the
prompt does not solicit it — so per LP-405 (no rule may depend on the free-form catch-all) IH-1 cannot be built
yet. LP-431 STOPs at that extractor-extension boundary.

These guards pin the STOP so it cannot silently rot: the field is genuinely absent (the reason IH-1 is blocked),
and IH-1 is not written / not active. When a future ticket ADDS the typed-core `loss_settlement_basis` field,
these tests turn red — the intended tripwire that says "now IH-1 can be written (LP-431 / ADR-340)".
"""

from __future__ import annotations

from pathlib import Path

from app.ai.extraction.homeowners_insurance import HomeownersInsuranceExtraction
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS

_SPECS = Path(__file__).resolve().parents[3] / "app" / "verification" / "rules" / "specs"


# ======================================================================= #
# THE STOP (D1) — the loss-settlement-basis field is not extracted (the reason IH-1 is blocked)
# ======================================================================= #
def test_homeowners_insurance_has_no_loss_settlement_basis_field() -> None:
    # The typed core is carrier / policy / address / coverage_amount / premium / dates only. A loss-settlement
    # basis (replacement cost vs actual cash value) — the ONLY input Priya's IH-1 needs — is not among them, and
    # is not solicited by the prompt, so it is not reliably in the catch-all either (LP-405: a rule may not read
    # the free-form additional_sections). This absence is exactly why LP-431 STOPs.
    fields = set(HomeownersInsuranceExtraction.model_fields)
    assert (
        "coverage_amount" in fields and "effective_date" in fields
    )  # the fields that DO exist (IH-3/DT)
    for basis_field in (
        "loss_settlement_basis",
        "replacement_cost_basis",
        "settlement_basis",
        "actual_cash_value",
        "roof_settlement_basis",  # the per-item ACV-roof nuance also has no home
    ):
        assert basis_field not in fields, (
            f"{basis_field} now exists — the LP-431 STOP is resolved; IH-1 can be written (ADR-340)"
        )


# ======================================================================= #
# IH-1 was deliberately NOT built (no spec, not active) — the honest STOP outcome
# ======================================================================= #
def test_ih1_is_not_written_or_active() -> None:
    assert not (_SPECS / "IH-1.yaml").is_file()  # no rule spec — blocked on the extractor extension
    assert "IH-1" not in ACTIVE_RULE_IDS  # and therefore not live
    # IH-3 (the live insurance sibling on the same binder, LP-417) IS written — the shape IH-1 will mirror once
    # its field exists. Its presence is the contrast that makes the IH-1 gap a field gap, not a rule-design one.
    assert (_SPECS / "IH-3.yaml").is_file()
