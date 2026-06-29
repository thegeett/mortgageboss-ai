"""Starter lender overlays (LP-80) — UWM + Sun-West, and the enforcement proof.

The MECHANISM is LP-74's (override-by-id + add-custom + investor-default); LP-80
supplies the CONTENT (starter placeholder values) and proves enforcement: the SAME
file produces DIFFERENT findings under UWM vs. Sun-West. These are pure tests over
the registry + engine (no DB). The VALUES are starter placeholders (validate with
Priya); the tests assert the MECHANISM, not authoritative thresholds.
"""

from decimal import Decimal

from app.models.lender import LoanProgram
from app.verification.engine import evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.overlays.starter import (
    STARTER_OVERLAYS,
    SUNWEST_SLUG,
    UWM_SLUG,
)
from app.verification.registry import default_registry
from app.verification.rules.samples import SAMPLE_RULES

CONV = LoanProgram.CONVENTIONAL


def _registry():
    return default_registry()


def _rule(rules, rule_id):
    return next(r for r in rules if r.rule_id == rule_id)


def _result(findings, rule_id):
    return next(f for f in findings if f.rule.rule_id == rule_id)


# --- The starter overlays load + are diffs -----------------------------------


def test_starter_overlays_load_and_are_diffs() -> None:
    """UWM + Sun-West parse and are small diffs (a handful), not full copies."""
    assert set(STARTER_OVERLAYS) == {UWM_SLUG, SUNWEST_SLUG}
    for overlay in STARTER_OVERLAYS.values():
        # A diff: far fewer entries than the full rule catalog.
        assert len(overlay.overrides) + len(overlay.custom_rules) < len(SAMPLE_RULES)


def test_overrides_carry_a_reason_marked_placeholder() -> None:
    """Each starter override has a reason, clearly marked a starter placeholder."""
    for overlay in STARTER_OVERLAYS.values():
        for override in overlay.overrides:
            assert override.reason is not None
            # Honest scoping: the value is a starter placeholder, not authoritative.
            assert "placeholder" in override.reason.lower()


# --- Override-by-id + add-custom (UWM) ---------------------------------------


def test_uwm_overrides_dti_by_id() -> None:
    """UWM tightens the Conventional back-end DTI cap to 45 (by rule_id)."""
    rules = _registry().resolve(program=CONV, lender_slug=UWM_SLUG)
    dti = _rule(rules, "conv.dti.back_end_max")

    assert dti.condition.value == Decimal("45")  # overlay value wins (vs 50)
    assert dti.overlay_applied == UWM_SLUG
    # Identity + logic preserved — only the threshold changed.
    assert dti.reads == ("dti.back_end_pct",)


def test_uwm_adds_a_custom_rule() -> None:
    """UWM adds a lender-scoped custom rule the investor default does not have."""
    rules = _registry().resolve(program=CONV, lender_slug=UWM_SLUG)
    ids = {r.rule_id for r in rules}
    assert f"{UWM_SLUG}.reserves.min_months" in ids


# --- Investor-default fall-through (Sun-West) --------------------------------


def test_sunwest_does_not_override_dti_falls_through_to_investor_default() -> None:
    """Sun-West leaves Conventional DTI at the investor default (50) — fall-through."""
    rules = _registry().resolve(program=CONV, lender_slug=SUNWEST_SLUG)
    dti = _rule(rules, "conv.dti.back_end_max")

    assert dti.condition.value == Decimal("50")  # the investor default
    assert dti.overlay_applied is None  # Sun-West did not touch DTI


def test_sunwest_overrides_ltv_so_it_is_still_a_real_diff() -> None:
    """Sun-West differs on LTV (95 vs 97) — a genuine, distinct diff from UWM."""
    rules = _registry().resolve(program=CONV, lender_slug=SUNWEST_SLUG)
    ltv = _rule(rules, "conv.ltv.purchase_max")

    assert ltv.condition.value == Decimal("95")
    assert ltv.overlay_applied == SUNWEST_SLUG


def test_no_lender_gets_all_investor_defaults() -> None:
    """No lender → every rule is the investor default (no overlay applied)."""
    rules = _registry().resolve(program=CONV, lender_slug=None)
    assert _rule(rules, "conv.dti.back_end_max").condition.value == Decimal("50")
    assert _rule(rules, "conv.ltv.purchase_max").condition.value == Decimal("97")
    assert all(r.overlay_applied is None for r in rules)


# --- THE ENFORCEMENT PROOF: same file → different findings -------------------


def test_enforcement_proof_same_file_flags_for_uwm_not_sunwest() -> None:
    """The HEADLINE: the SAME 48% file flags for UWM (45) but not Sun-West (50).

    Same observed value, same rule logic — only the lender (and thus the composed
    threshold) differs. UWM's overlay catches a DTI that Sun-West's default allows.
    """
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("48"))})
    reg = _registry()

    uwm = evaluate(facts, reg.resolve(program=CONV, lender_slug=UWM_SLUG))
    sunwest = evaluate(facts, reg.resolve(program=CONV, lender_slug=SUNWEST_SLUG))

    uwm_dti = _result(uwm, "conv.dti.back_end_max")
    sunwest_dti = _result(sunwest, "conv.dti.back_end_max")

    assert uwm_dti.evaluated is True and uwm_dti.passed is False  # 48 > 45 → flags
    assert sunwest_dti.evaluated is True and sunwest_dti.passed is True  # 48 <= 50 → clear


def test_a_low_dti_file_clears_for_both() -> None:
    """Control: a 40% file is under both caps — no DTI flag for either lender."""
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("40"))})
    reg = _registry()

    for slug in (UWM_SLUG, SUNWEST_SLUG):
        results = evaluate(facts, reg.resolve(program=CONV, lender_slug=slug))
        assert _result(results, "conv.dti.back_end_max").passed is True
