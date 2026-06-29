"""FHA income/asset/credit-DTI/MIP rules (LP-84) — grounded starters.

Covers: the uniform structure + HUD citation + starter markers; the TIERED MDCS
(580/500/<500 to down-payment — NOT a flat min); the manual-underwriting trigger;
the MITIGABLE compensating-factors DTI model (baseline YELLOW + uplifted-ceiling RED,
NOT a silent hard cutoff) consuming LP-76's front-/back-end; the MIP rules (UFMIP
1.75%, the LTV-90% duration reading LP-77's LTV, the missing-MIP finding);
program-gating (FHA-only, both ways); overlay-overrideability; and evaluation against
a constructed FHA fixture + a test-file-shaped FHA record (LP-82 promotion reuse).
"""

from datetime import date
from decimal import Decimal

from app.models import (
    Borrower,
    Company,
    LoanProgram,
    StatedAsset,
    StatedIncomeItem,
    StatedLiability,
)
from app.models.finding import FindingCategory
from app.services.loan_files import create_loan_file
from app.services.verification_engine import build_file_facts
from app.verification.engine import EngineFinding, evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.overlays.schema import LenderOverlay, ThresholdOverride
from app.verification.registry import apply_overlay, default_registry
from app.verification.rules.fha import (
    FHA_ASSET_RULES,
    FHA_CREDIT_RULES,
    FHA_DTI_RULES,
    FHA_INCOME_RULES,
    FHA_MIP_RULES,
    FHA_RULES,
)
from app.verification.rules.fha.credit_dti import (
    FHA_CREDIT_DEROG_BANKRUPTCY_CH7,
    FHA_CREDIT_DEROG_CH13,
    FHA_CREDIT_DEROG_FORECLOSURE,
    FHA_CREDIT_MANUAL_UW_SCORE_TRIGGER,
    FHA_CREDIT_MDCS_3_5_TIER,
    FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR,
    FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT,
    FHA_DTI_BACK_END_BASELINE,
    FHA_DTI_BACK_END_MAX,
    FHA_DTI_COMPENSATING_FACTORS_REQUIRED,
    FHA_DTI_FRONT_END_BASELINE,
    FHA_DTI_FRONT_END_MAX,
)
from app.verification.rules.fha.income_assets import FHA_ASSETS_GIFT_DOCUMENTATION
from app.verification.rules.fha.mip import (
    FHA_MIP_DURATION_HIGH_LTV_LIFE,
    FHA_MIP_DURATION_LOW_LTV_11YR,
    FHA_MIP_UFMIP_PRESENT,
    FHA_MIP_UFMIP_RATE,
)
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleLayer,
    RuleSeverity,
    VerificationRule,
)
from sqlalchemy.ext.asyncio import AsyncSession

FHA = LoanProgram.FHA


def _result(findings: list[EngineFinding], rule_id: str) -> EngineFinding:
    return next(f for f in findings if f.rule.rule_id == rule_id)


def _by_id(rules: list[VerificationRule], rule_id: str) -> VerificationRule:
    return next(r for r in rules if r.rule_id == rule_id)


# --- Structure (~31) + markers -----------------------------------------------


def test_thirty_one_rules_across_the_categories() -> None:
    assert len(FHA_CREDIT_RULES) == 8
    assert len(FHA_DTI_RULES) == 6
    assert len(FHA_INCOME_RULES) == 6
    assert len(FHA_ASSET_RULES) == 5
    assert len(FHA_MIP_RULES) == 6
    # The LP-84 contribution is 31; FHA_RULES also carries the LP-85 property/doc rules (18).
    lp84 = (
        len(FHA_CREDIT_RULES)
        + len(FHA_DTI_RULES)
        + len(FHA_INCOME_RULES)
        + len(FHA_ASSET_RULES)
        + len(FHA_MIP_RULES)
    )
    assert lp84 == 31
    assert len(FHA_RULES) == 49  # 31 (LP-84) + 18 (LP-85)


def test_each_rule_has_the_uniform_structure_and_hud_markers() -> None:
    for rule in FHA_RULES:
        assert rule.layer is RuleLayer.INVESTOR
        assert rule.applicability.program is FHA
        assert rule.reads
        assert isinstance(rule.condition, Condition)  # threshold/rate-as-data
        assert rule.starter is True
        assert rule.notes
        assert rule.source.type == "hud_handbook_4000_1"  # HUD, not Fannie
        assert rule.source.section
        assert rule.source.retrieved == "2026-06"


def test_rule_ids_are_namespaced_and_unique() -> None:
    ids = [r.rule_id for r in FHA_RULES]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("fha.") for i in ids)


# --- The tiered MDCS (NOT a flat min) ----------------------------------------


def test_mdcs_is_tiered_to_down_payment_not_a_flat_min() -> None:
    # Floor: below 500 is ineligible (RED).
    assert FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR.condition == Condition(
        op=Operator.GE, value=Decimal("500"), unit="score"
    )
    assert FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR.severity is RuleSeverity.RED
    # 580+ → the 3.5%-down tier (YELLOW flag for 500-579).
    assert FHA_CREDIT_MDCS_3_5_TIER.condition.value == Decimal("580")
    # The low tier is GATED to a 500-579 score and requires 10% down.
    assert FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT.gate is not None
    assert FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT.gate.reads == "credit.mdcs"
    assert FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT.condition.value == Decimal("10")


def test_a_540_score_with_5pct_down_fires_the_low_tier_10pct_requirement() -> None:
    facts = FileFacts(
        values={
            "credit.mdcs": Fact(value=Decimal("540")),
            "down_payment.pct": Fact(value=Decimal("5")),
        }
    )
    # Eligible (>=500) but in the 500-579 band → the gated 10%-down rule applies + fails.
    assert (
        _result(
            evaluate(facts, [FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR]),
            "fha.credit.mdcs_eligibility_floor",
        ).passed
        is True
    )
    low = _result(
        evaluate(facts, [FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT]),
        "fha.credit.mdcs_low_tier_down_payment",
    )
    assert low.evaluated is True and low.passed is False  # 5% < 10% required for the low tier


def test_a_620_score_closes_the_low_tier_gate() -> None:
    facts = FileFacts(
        values={
            "credit.mdcs": Fact(value=Decimal("620")),
            "down_payment.pct": Fact(value=Decimal("5")),
        }
    )
    # 620 >= 580 → the low-tier gate is closed (the standard 3.5% applies); not evaluated.
    assert evaluate(facts, [FHA_CREDIT_MDCS_LOW_TIER_DOWN_PAYMENT])[0].evaluated is False


def test_below_500_is_ineligible() -> None:
    facts = FileFacts(values={"credit.mdcs": Fact(value=Decimal("480"))})
    floor = evaluate(facts, [FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR])[0]
    assert floor.evaluated is True and floor.passed is False
    assert FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR.severity is RuleSeverity.RED


def test_manual_underwriting_score_trigger_below_620() -> None:
    facts = FileFacts(values={"credit.mdcs": Fact(value=Decimal("600"))})
    trig = evaluate(facts, [FHA_CREDIT_MANUAL_UW_SCORE_TRIGGER])[0]
    assert trig.evaluated is True and trig.passed is False  # < 620 → routed to manual UW
    assert FHA_CREDIT_MANUAL_UW_SCORE_TRIGGER.severity is RuleSeverity.YELLOW  # a flag, not a block


def test_derogatory_periods_are_flagged_to_verify() -> None:
    for rule in (
        FHA_CREDIT_DEROG_BANKRUPTCY_CH7,
        FHA_CREDIT_DEROG_FORECLOSURE,
        FHA_CREDIT_DEROG_CH13,
    ):
        assert rule.source.to_verify is True


# --- The mitigable compensating-factors DTI model (NOT a hard cutoff) ---------


def test_dti_is_the_mitigable_baseline_plus_uplifted_ceiling_model() -> None:
    # Baseline (mitigable) → YELLOW; uplifted ceiling (hard) → RED.
    assert FHA_DTI_FRONT_END_BASELINE.condition.value == Decimal("31")
    assert FHA_DTI_FRONT_END_BASELINE.severity is RuleSeverity.YELLOW
    assert FHA_DTI_FRONT_END_MAX.condition.value == Decimal("40")
    assert FHA_DTI_FRONT_END_MAX.severity is RuleSeverity.RED
    assert FHA_DTI_BACK_END_BASELINE.condition.value == Decimal("43")
    assert FHA_DTI_BACK_END_BASELINE.severity is RuleSeverity.YELLOW
    assert FHA_DTI_BACK_END_MAX.condition.value == Decimal("50")
    assert FHA_DTI_BACK_END_MAX.severity is RuleSeverity.RED


def test_a_47pct_back_end_is_a_mitigable_yellow_not_a_red_block() -> None:
    """47% > the 43% baseline (YELLOW, mitigable) but <= the 50% hard ceiling (passes RED)."""
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("47"))})
    baseline = _result(evaluate(facts, [FHA_DTI_BACK_END_BASELINE]), "fha.dti.back_end_baseline")
    ceiling = _result(evaluate(facts, [FHA_DTI_BACK_END_MAX]), "fha.dti.back_end_max_with_factors")
    assert baseline.evaluated is True and baseline.passed is False  # flagged...
    assert (
        baseline.rule.severity is RuleSeverity.YELLOW
    )  # ...mitigable (document a compensating factor)
    assert ceiling.passed is True  # ...still within the uplifted ceiling — NOT a hard block


def test_a_55pct_back_end_breaches_the_hard_ceiling() -> None:
    facts = FileFacts(values={"dti.back_end_pct": Fact(value=Decimal("55"))})
    ceiling = _result(evaluate(facts, [FHA_DTI_BACK_END_MAX]), "fha.dti.back_end_max_with_factors")
    assert ceiling.passed is False and ceiling.rule.severity is RuleSeverity.RED


def test_compensating_factor_is_required_only_over_the_baseline() -> None:
    rule = FHA_DTI_COMPENSATING_FACTORS_REQUIRED
    assert rule.gate is not None and rule.gate.reads == "dti.back_end_pct"
    # At 40% (under baseline) → the gate is closed → not applicable.
    under = FileFacts(
        values={
            "dti.back_end_pct": Fact(value=Decimal("40")),
            "dti.compensating_factor_count": Fact(value=Decimal("0")),
        }
    )
    assert evaluate(under, [rule])[0].evaluated is False
    # At 47% with zero documented factors → applies + fails (a factor is required).
    over = FileFacts(
        values={
            "dti.back_end_pct": Fact(value=Decimal("47")),
            "dti.compensating_factor_count": Fact(value=Decimal("0")),
        }
    )
    res = evaluate(over, [rule])[0]
    assert res.evaluated is True and res.passed is False
    # With one documented factor → satisfied.
    ok = FileFacts(
        values={
            "dti.back_end_pct": Fact(value=Decimal("47")),
            "dti.compensating_factor_count": Fact(value=Decimal("1")),
        }
    )
    assert evaluate(ok, [rule])[0].passed is True


def test_dti_rules_consume_the_computed_front_and_back_end() -> None:
    """The DTI rules READ LP-76's computed ratios (they do not recompute)."""
    assert FHA_DTI_FRONT_END_BASELINE.reads == ("dti.front_end_pct",)
    assert FHA_DTI_FRONT_END_MAX.reads == ("dti.front_end_pct",)
    assert FHA_DTI_BACK_END_BASELINE.reads == ("dti.back_end_pct",)
    assert FHA_DTI_BACK_END_MAX.reads == ("dti.back_end_pct",)


# --- MIP (no Conventional analog) --------------------------------------------


def test_ufmip_is_1_75_pct_and_present_check_is_red() -> None:
    # 175 bps = 1.75%.
    assert FHA_MIP_UFMIP_RATE.condition == Condition(
        op=Operator.EQ, value=Decimal("175"), unit="bps"
    )
    # A missing UFMIP is a RED finding (every FHA loan must carry MIP).
    assert FHA_MIP_UFMIP_PRESENT.severity is RuleSeverity.RED
    missing = FileFacts(values={"mip.ufmip_present": Fact(value=Decimal("0"))})
    res = evaluate(missing, [FHA_MIP_UFMIP_PRESENT])[0]
    assert res.evaluated is True and res.passed is False


def test_mip_duration_reads_ltv_and_gates_on_90() -> None:
    """LTV > 90% → life of loan; LTV <= 90% → 11 years (132 months). Both read LP-77's LTV."""
    assert FHA_MIP_DURATION_HIGH_LTV_LIFE.gate is not None
    assert FHA_MIP_DURATION_HIGH_LTV_LIFE.gate.reads == "ltv.ltv_pct"
    assert FHA_MIP_DURATION_LOW_LTV_11YR.gate is not None
    assert FHA_MIP_DURATION_LOW_LTV_11YR.gate.reads == "ltv.ltv_pct"

    # A 96.5% LTV (3.5% down) → the life-of-loan rule applies; the 11-year rule does not.
    high = FileFacts(
        values={
            "ltv.ltv_pct": Fact(value=Decimal("96.5")),
            "mip.duration_is_life": Fact(value=Decimal("1")),
            "mip.duration_months": Fact(value=Decimal("360")),
        }
    )
    assert evaluate(high, [FHA_MIP_DURATION_HIGH_LTV_LIFE])[0].evaluated is True
    assert evaluate(high, [FHA_MIP_DURATION_LOW_LTV_11YR])[0].evaluated is False

    # An 85% LTV (15% down) → the 11-year rule applies; the life rule does not.
    low = FileFacts(
        values={
            "ltv.ltv_pct": Fact(value=Decimal("85")),
            "mip.duration_months": Fact(value=Decimal("132")),
        }
    )
    assert evaluate(low, [FHA_MIP_DURATION_LOW_LTV_11YR])[0].evaluated is True
    assert evaluate(low, [FHA_MIP_DURATION_HIGH_LTV_LIFE])[0].evaluated is False


def test_mip_rules_use_documentation_category_no_migration() -> None:
    # No dedicated MORTGAGE_INSURANCE category (would need a migration) → DOCUMENTATION.
    for rule in FHA_MIP_RULES:
        assert rule.category is FindingCategory.DOCUMENTATION


# --- Program-gating (FHA-only, both ways) ------------------------------------


def test_program_gating_resolves_fha_rules_only_for_fha_files() -> None:
    reg = default_registry()
    fha_ids = {r.rule_id for r in reg.resolve(program=LoanProgram.FHA, lender_slug=None)}
    conv_ids = {r.rule_id for r in reg.resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)}
    # The FHA grounded rules resolve for an FHA file...
    assert {"fha.credit.mdcs_eligibility_floor", "fha.mip.ufmip_present"} <= fha_ids
    # ...and never for a Conventional file (and Conventional rules never for FHA).
    assert not any(i.startswith("fha.") for i in conv_ids)
    assert not any(i.startswith("conv.") for i in fha_ids)


# --- Overlay-overrideability (FHA overlays are common) -----------------------


def test_fha_minimum_and_mip_rate_are_overlay_overrideable() -> None:
    overlay = LenderOverlay(
        lender_slug="sun-west",
        overrides=(
            # A common FHA overlay: raise the MDCS floor from 500 to 620.
            ThresholdOverride(
                rule_id="fha.credit.mdcs_eligibility_floor",
                condition=Condition(op=Operator.GE, value=Decimal("620"), unit="score"),
            ),
            # The MIP rate is data too — overrideable by rule_id.
            ThresholdOverride(
                rule_id="fha.mip.ufmip_rate",
                condition=Condition(op=Operator.EQ, value=Decimal("180"), unit="bps"),
            ),
        ),
    )
    patched = apply_overlay([FHA_CREDIT_MDCS_ELIGIBILITY_FLOOR, FHA_MIP_UFMIP_RATE], overlay)
    assert _by_id(patched, "fha.credit.mdcs_eligibility_floor").condition.value == Decimal("620")
    assert _by_id(patched, "fha.mip.ufmip_rate").condition.value == Decimal("180")
    assert _by_id(patched, "fha.credit.mdcs_eligibility_floor").overlay_applied == "sun-west"


# --- Evaluation against a constructed FHA fixture ----------------------------


def test_evaluation_against_a_constructed_fha_fixture() -> None:
    """A representative manual FHA file: 540 score / 5% down, 47% DTI, 96.5% LTV, no MIP."""
    facts = FileFacts(
        values={
            "credit.mdcs": Fact(value=Decimal("540")),
            "down_payment.pct": Fact(value=Decimal("5")),
            "dti.front_end_pct": Fact(value=Decimal("34")),
            "dti.back_end_pct": Fact(value=Decimal("47")),
            "dti.compensating_factor_count": Fact(value=Decimal("0")),
            "ltv.ltv_pct": Fact(value=Decimal("96.5")),
            "mip.ufmip_present": Fact(value=Decimal("0")),
            "mip.duration_is_life": Fact(value=Decimal("0")),
        }
    )
    results = evaluate(facts, list(FHA_RULES))
    fired = {f.rule.rule_id for f in results if f.evaluated and not f.passed}
    # Tiered MDCS low-tier down payment, the manual-UW flag, the mitigable DTI baselines,
    # the over-baseline compensating-factor requirement, and the missing UFMIP all fire.
    assert "fha.credit.mdcs_low_tier_down_payment" in fired
    assert "fha.credit.manual_underwriting_score_trigger" in fired
    assert "fha.dti.front_end_baseline" in fired
    assert "fha.dti.back_end_baseline" in fired
    assert "fha.dti.compensating_factors_required" in fired
    assert "fha.mip.ufmip_present" in fired
    # The high-LTV (96.5%) → life-of-loan duration rule is the applicable tier;
    # duration_is_life=0 means it has not been set to life → fires.
    assert "fha.mip.duration_high_ltv_life" in fired
    # The hard 50% ceiling is NOT breached at 47% (mitigable, not hard).
    assert "fha.dti.back_end_max_with_factors" not in fired


# --- Test-file-shaped FHA record: program-gating + LP-82 promotion reuse ------


async def test_fha_file_reuses_lp82_promotions_and_program_gates(
    db_session: AsyncSession,
) -> None:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.FHA
    )
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Test", last_name="B", is_primary=True
    )
    db_session.add(borrower)
    await db_session.flush()
    # DTI inputs (→ dti.back_end_pct promoted) + a gift asset (→ assets.gift.total_amount).
    db_session.add(StatedIncomeItem(borrower_id=borrower.id, monthly_amount=Decimal("8000")))
    db_session.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Auto", monthly_payment=Decimal("4000")
        )
    )
    db_session.add(
        StatedAsset(loan_file_id=loan_file.id, asset_type="Gift Funds", value=Decimal("12000"))
    )
    await db_session.flush()

    facts = await build_file_facts(db_session, loan_file=loan_file, as_of=date(2026, 6, 1))

    # The LP-82 promotions feed the FHA variants (same field paths) → evaluable on an FHA file.
    assert facts.read(("assets.gift.total_amount",)) is not None
    gift = _result(
        evaluate(facts, [FHA_ASSETS_GIFT_DOCUMENTATION]), "fha.assets.gift_letter_and_transfer"
    )
    assert gift.evaluated is True  # gift present → documentation requirement evaluated
    assert facts.read(("dti.back_end_pct",)) is not None
    assert evaluate(facts, [FHA_DTI_BACK_END_BASELINE])[0].evaluated is True

    # Program-gating against this FHA file: the registry resolves FHA rules for it,
    # and the Conventional rules are absent.
    reg = default_registry()
    resolved = {r.rule_id for r in reg.resolve(program=loan_file.loan_program, lender_slug=None)}
    assert "fha.assets.gift_letter_and_transfer" in resolved
    assert not any(i.startswith("conv.") for i in resolved)
