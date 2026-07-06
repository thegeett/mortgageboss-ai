"""The three-layer composition (LP-74) — base + overlay-diff → effective set.

Covers: program-selection (Conventional gets Conventional investor rules, never
FHA); overlay override-by-id (the DTI threshold becomes 45, not 50); custom-rule
add; investor-default fall-through (un-overridden rules keep their default); and
no-overlay → all investor defaults.
"""

from decimal import Decimal

from app.models.lender import LoanProgram
from app.verification.overlays.samples import SAMPLE_OVERLAY_LENDER_SLUG, SAMPLE_OVERLAYS
from app.verification.registry import RuleRegistry, default_registry
from app.verification.rules.samples import SAMPLE_RULES
from app.verification.rules.schema import RuleLayer


def _registry() -> RuleRegistry:
    return default_registry()


def test_base_is_regulatory_plus_investor_for_program() -> None:
    """Conventional file → regulatory + Conventional investor rules, no FHA."""
    rules = _registry().resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)
    ids = {rule.rule_id for rule in rules}

    assert "reg.aml.large_deposit_review" in ids  # regulatory (all loans)
    assert "doc.income.paystub_recency" in ids  # documentation (all loans)
    assert "conv.dti.back_end_max" in ids  # Conventional investor
    assert "fha.dti.back_end_max" not in ids  # NOT the FHA rule


def test_program_selection_picks_fha_for_fha_files() -> None:
    """FHA file → the FHA investor rule, never the Conventional one."""
    rules = _registry().resolve(program=LoanProgram.FHA, lender_slug=None)
    ids = {rule.rule_id for rule in rules}

    assert "fha.dti.back_end_max" in ids
    assert "conv.dti.back_end_max" not in ids


def test_no_program_yields_only_regulatory() -> None:
    """A file with no program gets only the regulatory/all-loans rules."""
    rules = _registry().resolve(program=None, lender_slug=None)
    assert all(rule.layer is RuleLayer.REGULATORY for rule in rules)


def test_no_overlay_means_all_investor_defaults() -> None:
    """No lender overlay → every rule is its investor/regulatory default."""
    rules = _registry().resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)
    conv = next(r for r in rules if r.rule_id == "conv.dti.back_end_max")

    assert conv.condition.value == Decimal("50")  # investor default
    assert conv.overlay_applied is None
    assert all(rule.overlay_applied is None for rule in rules)


def test_overlay_overrides_threshold_by_rule_id() -> None:
    """The sample overlay patches the DTI threshold to 45 (not 50), by id."""
    rules = _registry().resolve(
        program=LoanProgram.CONVENTIONAL, lender_slug=SAMPLE_OVERLAY_LENDER_SLUG
    )
    conv = next(r for r in rules if r.rule_id == "conv.dti.back_end_max")

    assert conv.condition.value == Decimal("45")  # overlay value wins
    assert conv.overlay_applied == SAMPLE_OVERLAY_LENDER_SLUG
    # Identity + logic preserved — only the threshold changed.
    assert conv.reads == ("dti.back_end_pct",)
    assert conv.layer is RuleLayer.INVESTOR


def test_overlay_adds_custom_rule() -> None:
    """The sample overlay adds its reserves custom rule (add-custom)."""
    rules = _registry().resolve(
        program=LoanProgram.CONVENTIONAL, lender_slug=SAMPLE_OVERLAY_LENDER_SLUG
    )
    ids = {rule.rule_id for rule in rules}

    assert f"{SAMPLE_OVERLAY_LENDER_SLUG}.reserves.min_months" in ids


def test_un_overridden_rules_fall_through_to_investor_default() -> None:
    """A rule the overlay does not mention keeps its investor default verbatim."""
    base = _registry().resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)
    patched = _registry().resolve(
        program=LoanProgram.CONVENTIONAL, lender_slug=SAMPLE_OVERLAY_LENDER_SLUG
    )

    base_aml = next(r for r in base if r.rule_id == "reg.aml.large_deposit_review")
    patched_aml = next(r for r in patched if r.rule_id == "reg.aml.large_deposit_review")

    # The AML rule is not in the overlay → identical (fall-through).
    assert patched_aml.condition == base_aml.condition
    assert patched_aml.overlay_applied is None


def test_overlay_is_a_diff_not_a_full_copy() -> None:
    """The overlay stores only deviations (one override + one custom rule)."""
    overlay = SAMPLE_OVERLAYS[SAMPLE_OVERLAY_LENDER_SLUG]

    assert len(overlay.overrides) == 1
    assert len(overlay.custom_rules) == 1
    # Far fewer entries than the full rule catalog — a diff, not a copy.
    assert len(overlay.overrides) + len(overlay.custom_rules) < len(SAMPLE_RULES)
