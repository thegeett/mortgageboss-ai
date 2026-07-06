"""Conventional credit/DTI + property + documentation rules (LP-83) — grounded starters.

Covers: the uniform structure + starter/citation markers; the LAYERED credit-score
state (NOT a flat min-620) marked recently-changed; deterministic evaluation; the
max-DTI rule consuming LP-76's computed DTI; applicability-gating (manual-only,
condo-only); overlay-overrideability; and evaluation against a test-file-shaped record.
"""

from datetime import date
from decimal import Decimal

from app.models import Borrower, Company, LoanProgram, StatedIncomeItem, StatedLiability
from app.models.finding import FindingCategory
from app.models.property import Property, PropertyType
from app.services.loan_files import create_loan_file
from app.services.verification_engine import build_file_facts
from app.verification.engine import EngineFinding, evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.overlays.schema import LenderOverlay, ThresholdOverride
from app.verification.registry import apply_overlay
from app.verification.rules.conventional.credit_property_docs import (
    CONV_CREDIT_MIN_SCORE_DELIVERY_FLOOR,
    CONV_CREDIT_MIN_SCORE_MANUAL,
    CONV_DOCS_CONDO_PROJECT_REVIEW,
    CONV_DTI_MAX_MANUAL,
    CONV_PROPERTY_APPRAISAL_AGE,
    CONV_PROPERTY_SUBJECT_PRESENT,
    CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES,
    CONVENTIONAL_CREDIT_RULES,
    CONVENTIONAL_DOC_RULES,
    CONVENTIONAL_DTI_RULES,
    CONVENTIONAL_PROPERTY_RULES,
)
from app.verification.rules.schema import Condition, Operator, RuleLayer, VerificationRule
from sqlalchemy.ext.asyncio import AsyncSession

CONV = LoanProgram.CONVENTIONAL


def _result(findings: list[EngineFinding], rule_id: str) -> EngineFinding:
    return next(f for f in findings if f.rule.rule_id == rule_id)


def _by_id(rules: list[VerificationRule], rule_id: str) -> VerificationRule:
    return next(r for r in rules if r.rule_id == rule_id)


# --- Structure (~30) + markers -----------------------------------------------


def test_thirty_rules_across_the_four_categories() -> None:
    assert len(CONVENTIONAL_CREDIT_RULES) == 8
    assert len(CONVENTIONAL_DTI_RULES) == 5
    assert len(CONVENTIONAL_PROPERTY_RULES) == 9
    assert len(CONVENTIONAL_DOC_RULES) == 8
    assert len(CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES) == 30


def test_each_rule_has_the_uniform_structure_and_markers() -> None:
    for rule in CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES:
        assert rule.layer is RuleLayer.INVESTOR
        assert rule.applicability.program is CONV
        assert rule.reads
        assert isinstance(rule.condition, Condition)  # threshold-as-data
        assert rule.starter is True
        assert rule.notes
        assert rule.source.type == "fannie_selling_guide"
        assert rule.source.section
        assert rule.source.retrieved == "2026-06"


def test_rule_ids_are_namespaced_and_unique() -> None:
    ids = [r.rule_id for r in CONVENTIONAL_CREDIT_PROPERTY_DOC_RULES]
    assert len(ids) == len(set(ids))
    assert {r.rule_id for r in CONVENTIONAL_CREDIT_RULES} <= {
        i for i in ids if i.startswith("conv.credit.")
    }


# --- The headline correction: layered, NOT flat min-620 ----------------------


def test_min_score_is_layered_not_a_flat_620() -> None:
    """Manual-620 (gated) + delivery-floor-620 (ungated); DU applies no minimum."""
    # The manual rule is gated to manual underwriting.
    assert CONV_CREDIT_MIN_SCORE_MANUAL.gate is not None
    assert CONV_CREDIT_MIN_SCORE_MANUAL.gate.reads == "underwriting.is_manual"
    # The delivery floor is ungated (always applies).
    assert CONV_CREDIT_MIN_SCORE_DELIVERY_FLOOR.gate is None
    # Both reference B3-5.1-01 and are marked recently-changed / layered.
    assert CONV_CREDIT_MIN_SCORE_MANUAL.source.section == "B3-5.1-01"
    notes = CONV_CREDIT_MIN_SCORE_MANUAL.notes or ""
    assert "RECENTLY CHANGED" in notes and "LAYERED" in notes
    assert "DU" in notes  # DU 12.0 applies no minimum


def test_derogatory_periods_are_flagged_to_verify_not_asserted() -> None:
    for rid in (
        "conv.credit.derogatory_foreclosure_waiting",
        "conv.credit.derogatory_bankruptcy_waiting",
        "conv.credit.derogatory_short_sale_waiting",
    ):
        assert _by_id(list(CONVENTIONAL_CREDIT_RULES), rid).source.to_verify is True


# --- Deterministic evaluation + the DTI cross-link ---------------------------


def test_manual_min_score_fires_below_620_for_a_manual_file() -> None:
    facts = FileFacts(
        values={
            "underwriting.is_manual": Fact(value=Decimal(1)),
            "credit.representative_score": Fact(value=Decimal(610)),
        }
    )
    result = _result(
        evaluate(facts, [CONV_CREDIT_MIN_SCORE_MANUAL]), "conv.credit.min_score_manual"
    )
    assert result.evaluated is True and result.passed is False
    assert CONV_CREDIT_MIN_SCORE_MANUAL.category is FindingCategory.CREDIT


def test_max_dti_manual_consumes_the_computed_dti() -> None:
    """The manual DTI rule reads LP-76's computed dti.back_end_pct (does not recompute)."""
    assert CONV_DTI_MAX_MANUAL.reads == ("dti.back_end_pct",)
    facts = FileFacts(
        values={
            "underwriting.is_manual": Fact(value=Decimal(1)),
            "dti.back_end_pct": Fact(value=Decimal("48")),
        }
    )
    # 48% > the 45% manual ceiling → fires.
    assert (
        _result(evaluate(facts, [CONV_DTI_MAX_MANUAL]), "conv.dti.back_end_max_manual").passed
        is False
    )


def test_appraisal_age_over_four_months_fires() -> None:
    facts = FileFacts(values={"property.appraisal_age_months": Fact(value=Decimal("5"))})
    assert evaluate(facts, [CONV_PROPERTY_APPRAISAL_AGE])[0].passed is False


# --- Applicability gating -----------------------------------------------------


def test_manual_only_rule_does_not_fire_for_a_du_file() -> None:
    """A DU file (is_manual=0) → the manual min-score rule is not applicable."""
    facts = FileFacts(
        values={
            "underwriting.is_manual": Fact(value=Decimal(0)),
            "credit.representative_score": Fact(value=Decimal(610)),
        }
    )
    result = _result(
        evaluate(facts, [CONV_CREDIT_MIN_SCORE_MANUAL]), "conv.credit.min_score_manual"
    )
    assert result.evaluated is False  # gated out → no finding


def test_manual_gate_absent_is_not_applicable() -> None:
    """Unknown underwriting method → the manual rule is conservatively skipped."""
    facts = FileFacts(values={"credit.representative_score": Fact(value=Decimal(610))})
    assert evaluate(facts, [CONV_CREDIT_MIN_SCORE_MANUAL])[0].evaluated is False


def test_condo_only_rule_does_not_fire_for_a_single_family() -> None:
    single_family = FileFacts(
        values={
            "property.is_condo": Fact(value=Decimal(0)),
            "documents.condo.project_review_present": Fact(value=Decimal(0)),
        }
    )
    condo = FileFacts(
        values={
            "property.is_condo": Fact(value=Decimal(1)),
            "documents.condo.project_review_present": Fact(value=Decimal(0)),
        }
    )
    # Single-family → gated out (not applicable); condo → gated in + fires (review missing).
    assert evaluate(single_family, [CONV_DOCS_CONDO_PROJECT_REVIEW])[0].evaluated is False
    condo_result = evaluate(condo, [CONV_DOCS_CONDO_PROJECT_REVIEW])[0]
    assert condo_result.evaluated is True and condo_result.passed is False


# --- Overlay-overrideability --------------------------------------------------


def test_credit_and_property_thresholds_are_overlay_overrideable() -> None:
    overlay = LenderOverlay(
        lender_slug="strict-bank",
        overrides=(
            ThresholdOverride(
                rule_id="conv.credit.min_score_delivery_floor",
                condition=Condition(op=Operator.GE, value=Decimal("640"), unit="score"),
            ),
            ThresholdOverride(
                rule_id="conv.property.appraisal_age",
                condition=Condition(op=Operator.LE, value=Decimal("3"), unit="months"),
            ),
        ),
    )
    patched = apply_overlay(
        [CONV_CREDIT_MIN_SCORE_DELIVERY_FLOOR, CONV_PROPERTY_APPRAISAL_AGE], overlay
    )
    assert _by_id(patched, "conv.credit.min_score_delivery_floor").condition.value == Decimal("640")
    assert _by_id(patched, "conv.property.appraisal_age").condition.value == Decimal("3")


# --- Test-file-shaped evaluation: property promotions + gating ----------------


async def test_property_promotions_and_evaluation_against_a_file(
    db_session: AsyncSession,
) -> None:
    company = Company(name="Acme", slug="acme")
    db_session.add(company)
    await db_session.flush()
    loan_file = await create_loan_file(
        db_session, company_id=company.id, loan_program=LoanProgram.CONVENTIONAL
    )
    borrower = Borrower(
        loan_file_id=loan_file.id, first_name="Mahesh", last_name="C", is_primary=True
    )
    db_session.add(borrower)
    await db_session.flush()
    # DTI inputs so the calc fact exists; a single-family subject property.
    db_session.add(StatedIncomeItem(borrower_id=borrower.id, monthly_amount=Decimal("12000")))
    db_session.add(
        StatedLiability(
            loan_file_id=loan_file.id, liability_type="Mortgage", monthly_payment=Decimal("3000")
        )
    )
    db_session.add(
        Property(
            loan_file_id=loan_file.id,
            property_type=PropertyType.SINGLE_FAMILY,
            address_line="1 Main",
        )
    )
    await db_session.flush()

    facts = await build_file_facts(db_session, loan_file=loan_file, as_of=date(2026, 6, 1))

    # The property promotions appear; is_condo == 0 for a single-family.
    assert facts.read(("property.present",)) is not None
    assert evaluate(facts, [CONV_PROPERTY_SUBJECT_PRESENT])[0].passed is True
    # The DTI calc fact is available for the (DU) ceiling to consume.
    assert facts.read(("dti.back_end_pct",)) is not None
    # The condo-only review rule is not applicable to this single-family file.
    assert evaluate(facts, [CONV_DOCS_CONDO_PROJECT_REVIEW])[0].evaluated is False
