"""Conventional income/asset rules (LP-82) — grounded starters into the engine.

Covers: the uniform structure (id/layer/program/reads/threshold-as-data/severity/
structured citation/starter marker); the grounded values + markers (4-month doc age,
recently-changed base-income, DU-driven large-deposit/reserves); deterministic
evaluation of the evaluable rules; overlay-overrideability (threshold-as-data); and
evaluation against a test-file-shaped record (self-employment + gift + retirement).
"""

from datetime import date
from decimal import Decimal

from app.models import Borrower, Company, LoanProgram, StatedAsset, StatedIncomeItem
from app.models.finding import FindingCategory
from app.services.loan_files import create_loan_file
from app.services.verification_engine import build_file_facts
from app.verification.engine import EngineFinding, evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.overlays.schema import LenderOverlay, ThresholdOverride
from app.verification.registry import apply_overlay, default_registry
from app.verification.rules.conventional import (
    CONV_ASSETS_GIFT_DOC,
    CONV_ASSETS_LARGE_DEPOSIT,
    CONV_ASSETS_RESERVES,
    CONV_ASSETS_RETIREMENT_WITHDRAWAL,
    CONV_INCOME_BASE_DOC,
    CONV_INCOME_SELF_EMPLOYMENT_HISTORY,
    CONV_INCOME_SELF_EMPLOYMENT_PRESENT,
    CONVENTIONAL_ASSET_RULES,
    CONVENTIONAL_INCOME_ASSET_RULES,
    CONVENTIONAL_INCOME_RULES,
)
from app.verification.rules.schema import (
    Condition,
    Operator,
    RuleLayer,
    VerificationRule,
)
from sqlalchemy.ext.asyncio import AsyncSession

CONV = LoanProgram.CONVENTIONAL


def _result(findings: list[EngineFinding], rule_id: str) -> EngineFinding:
    return next(f for f in findings if f.rule.rule_id == rule_id)


# --- Structure + the two linchpins + the starter/citation markers ------------


def test_twenty_conventional_income_and_asset_rules() -> None:
    assert len(CONVENTIONAL_INCOME_RULES) == 10
    assert len(CONVENTIONAL_ASSET_RULES) == 10
    assert len(CONVENTIONAL_INCOME_ASSET_RULES) == 20


def test_each_rule_has_the_uniform_structure_and_markers() -> None:
    for rule in CONVENTIONAL_INCOME_ASSET_RULES:
        assert rule.layer is RuleLayer.INVESTOR
        assert rule.applicability.program is CONV
        assert rule.reads  # reads a typed field path, never prose
        assert isinstance(rule.condition, Condition)  # threshold-as-data
        # A grounded STARTER with a structured, durable citation.
        assert rule.starter is True
        assert rule.notes  # the validate-with-Priya / promotion note
        assert rule.source.type == "fannie_selling_guide"
        assert rule.source.section  # a durable section reference, not a deep URL
        assert rule.source.retrieved == "2026-06"


def test_rule_ids_are_stable_namespaced_and_unique() -> None:
    ids = [r.rule_id for r in CONVENTIONAL_INCOME_ASSET_RULES]
    assert len(ids) == len(set(ids))  # unique
    assert all(r.rule_id.startswith("conv.income.") for r in CONVENTIONAL_INCOME_RULES)
    assert all(r.rule_id.startswith("conv.assets.") for r in CONVENTIONAL_ASSET_RULES)


def test_grounded_values_correct_folk_knowledge() -> None:
    """4-month doc age (B1-1-03), not 30 days; 2-year self-employment (B3-3.5-01)."""
    doc_age = next(
        r for r in CONVENTIONAL_INCOME_ASSET_RULES if r.rule_id == "conv.income.credit_doc_age"
    )
    assert doc_age.condition.value == Decimal("4")
    assert doc_age.condition.unit == "months"
    assert doc_age.source.section == "B1-1-03"
    assert CONV_INCOME_SELF_EMPLOYMENT_HISTORY.condition.value == Decimal("24")
    assert CONV_INCOME_SELF_EMPLOYMENT_HISTORY.source.section == "B3-3.5-01"


def test_recently_changed_base_income_rule_is_marked() -> None:
    """The base-income doc rule changed 03/2026 (W-2+paystub, not 2-yr W-2s) — marked."""
    assert "RECENTLY CHANGED" in (CONV_INCOME_BASE_DOC.notes or "")
    assert "03/2026" in (CONV_INCOME_BASE_DOC.notes or "")
    assert "W-2 + pay stub" in CONV_INCOME_BASE_DOC.description


def test_large_deposit_threshold_is_marked_du_driven_starter() -> None:
    """The large-deposit % is a STARTER placeholder, not a Selling-Guide constant."""
    assert CONV_ASSETS_LARGE_DEPOSIT.starter is True
    assert "DU-MESSAGE-DRIVEN" in (CONV_ASSETS_LARGE_DEPOSIT.notes or "")
    assert "NOT a" in (CONV_ASSETS_LARGE_DEPOSIT.notes or "")  # not a fixed constant
    # Reserves likewise DU/program-driven.
    assert "DU/program/property-driven" in (CONV_ASSETS_RESERVES.notes or "")


def test_uncertain_sections_are_flagged_to_verify_not_fabricated() -> None:
    """Rules whose subsection is uncertain carry to_verify=True (never invented)."""
    ownership = next(
        r
        for r in CONVENTIONAL_INCOME_ASSET_RULES
        if r.rule_id == "conv.income.ownership_interest_se_treatment"
    )
    assert ownership.source.to_verify is True


# --- Deterministic evaluation (read typed field → compare → emit) ------------


def test_gift_present_fires_a_documentation_finding() -> None:
    facts = FileFacts(values={"assets.gift.total_amount": Fact(value=Decimal("56000"))})
    result = evaluate(facts, [CONV_ASSETS_GIFT_DOC])[0]
    assert result.evaluated is True and result.passed is False  # gift → docs required
    assert CONV_ASSETS_GIFT_DOC.category is FindingCategory.ASSETS


def test_retirement_present_fires() -> None:
    facts = FileFacts(values={"assets.retirement.total_amount": Fact(value=Decimal("243000"))})
    assert evaluate(facts, [CONV_ASSETS_RETIREMENT_WITHDRAWAL])[0].passed is False


def test_self_employment_present_fires() -> None:
    facts = FileFacts(values={"income.self_employment.monthly_amount": Fact(value=Decimal("8000"))})
    assert evaluate(facts, [CONV_INCOME_SELF_EMPLOYMENT_PRESENT])[0].passed is False


def test_large_deposit_passes_under_and_fires_over_the_threshold() -> None:
    under = FileFacts(values={"assets.largest_deposit_amount": Fact(value=Decimal("8000"))})
    over = FileFacts(values={"assets.largest_deposit_amount": Fact(value=Decimal("25000"))})
    assert evaluate(under, [CONV_ASSETS_LARGE_DEPOSIT])[0].passed is True
    assert evaluate(over, [CONV_ASSETS_LARGE_DEPOSIT])[0].passed is False


def test_reserves_fires_below_the_starter_floor() -> None:
    low = FileFacts(values={"reserves.months": Fact(value=Decimal("0.5"))})
    ok = FileFacts(values={"reserves.months": Fact(value=Decimal("6"))})
    assert evaluate(low, [CONV_ASSETS_RESERVES])[0].passed is False
    assert evaluate(ok, [CONV_ASSETS_RESERVES])[0].passed is True


def test_a_rule_whose_fact_is_absent_is_not_evaluated_not_a_crash() -> None:
    """Promotion-pending rules read a fact that isn't produced yet → not-evaluated."""
    result = evaluate(FileFacts(values={}), [CONV_INCOME_SELF_EMPLOYMENT_HISTORY])[0]
    assert result.evaluated is False and result.passed is False


# --- Overlay-overrideability (threshold-as-data, LP-80) ----------------------


def test_asset_rule_threshold_is_overlay_overrideable_and_reaches_evaluation() -> None:
    overlay = LenderOverlay(
        lender_slug="tighter-bank",
        overrides=(
            ThresholdOverride(
                rule_id="conv.assets.large_deposit_source",
                condition=Condition(op=Operator.LE, value=Decimal("5000"), unit="usd"),
            ),
        ),
    )
    patched = apply_overlay([CONV_ASSETS_LARGE_DEPOSIT], overlay)
    ld = _by_id(patched, "conv.assets.large_deposit_source")
    assert ld.condition.value == Decimal("5000")
    assert ld.overlay_applied == "tighter-bank"

    facts = FileFacts(values={"assets.largest_deposit_amount": Fact(value=Decimal("7000"))})
    assert evaluate(facts, [CONV_ASSETS_LARGE_DEPOSIT])[0].passed is True  # default 10k
    assert evaluate(facts, [ld])[0].passed is False  # overlay 5k → fires


def test_income_rule_threshold_is_overlay_overrideable() -> None:
    overlay = LenderOverlay(
        lender_slug="x",
        overrides=(
            ThresholdOverride(
                rule_id="conv.income.self_employment_history",
                condition=Condition(op=Operator.GE, value=Decimal("12"), unit="months"),
            ),
        ),
    )
    patched = apply_overlay([CONV_INCOME_SELF_EMPLOYMENT_HISTORY], overlay)
    assert _by_id(patched, "conv.income.self_employment_history").condition.value == Decimal("12")


def _by_id(rules: list[VerificationRule], rule_id: str) -> VerificationRule:
    return next(r for r in rules if r.rule_id == rule_id)


# --- The rules are registered (resolve through the engine) -------------------


def test_conventional_rules_are_in_the_default_registry() -> None:
    conv = default_registry().resolve(program=CONV, lender_slug=None)
    ids = {r.rule_id for r in conv}
    assert "conv.income.self_employment_present" in ids
    assert "conv.assets.gift_documentation" in ids
    # FHA files do not get the Conventional rules.
    fha = default_registry().resolve(program=LoanProgram.FHA, lender_slug=None)
    assert "conv.income.self_employment_present" not in {r.rule_id for r in fha}


# --- Test-file-shaped evaluation: typed-core promotions + the rules fire ------


async def test_promotions_and_evaluation_against_a_mahesh_shaped_file(
    db_session: AsyncSession,
) -> None:
    """A self-employed-with-gift-and-retirement file: the promoted facts fire the rules.

    Mirrors the test borrower (Mahesh Chhotala) — self-employment income across LLCs, a
    $56k gift, a $243k retirement fund — exercising the evaluable LP-82 rules end to end.
    """
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Mahesh", last_name="Chhotala", is_primary=True
    )
    db_session.add(borrower)
    await db_session.flush()
    db_session.add(
        StatedIncomeItem(
            borrower_id=borrower.id,
            monthly_amount=Decimal("12000"),
            income_type="SelfEmployment",
            employment_income=True,
        )
    )
    db_session.add(
        StatedAsset(loan_file_id=loan_file.id, asset_type="GiftOfCash", value=Decimal("56000"))
    )
    db_session.add(
        StatedAsset(loan_file_id=loan_file.id, asset_type="RetirementFund", value=Decimal("243000"))
    )
    await db_session.flush()

    facts = await build_file_facts(db_session, loan_file=loan_file, as_of=date(2026, 6, 1))

    # The typed-core promotions produced the facts from the stated data.
    assert facts.read(("income.self_employment.monthly_amount",)) is not None
    assert facts.read(("assets.gift.total_amount",)) is not None
    assert facts.read(("assets.retirement.total_amount",)) is not None

    results = evaluate(facts, list(CONVENTIONAL_INCOME_ASSET_RULES))
    # The self-employment / gift / retirement rules fire on this borrower's data.
    assert _result(results, "conv.income.self_employment_present").passed is False
    assert _result(results, "conv.assets.gift_documentation").passed is False
    assert _result(results, "conv.assets.retirement_withdrawal_permitted").passed is False
