"""FHA property (MPR) + documentation rules (LP-85) — grounded starters.

Covers: the uniform structure + HUD citation + starter markers; the three-S's /
deficiency checklist encoded as the CONDITIONAL "subject-to-repair" mitigable model
(YELLOW correctable; no-egress / defective-conditions RED uncorrectable); the TIER-2
honesty (appraisal-presence + subject-to-status + MPR checklist surfaced, not faked
deficiency detection); program-gating (FHA-only); applicability-gating (condo,
well/septic, construction status, pre-1978); overlay-overrideability; and evaluation
against an extended FHA fixture + a DB-backed FHA file (property.unit_count promotion).
"""

from datetime import date
from decimal import Decimal

from app.models import Borrower, Company, LoanProgram
from app.models.finding import FindingCategory
from app.models.property import Property, PropertyType
from app.services.loan_files import create_loan_file
from app.services.verification_engine import build_file_facts
from app.verification.engine import EngineFinding, evaluate
from app.verification.facts import Fact, FileFacts
from app.verification.overlays.schema import LenderOverlay, ThresholdOverride
from app.verification.registry import apply_overlay, default_registry
from app.verification.rules.fha import (
    FHA_DOC_RULES,
    FHA_PROPERTY_DOC_RULES,
    FHA_PROPERTY_ELIGIBILITY_RULES,
    FHA_PROPERTY_MPR_RULES,
)
from app.verification.rules.fha.property_docs import (
    FHA_DOC_FHA_APPRAISAL_PRESENT,
    FHA_DOC_SUBJECT_TO_REPAIR_COMPLETION,
    FHA_PROPERTY_APPRAISAL_VALIDITY,
    FHA_PROPERTY_CONDO_APPROVAL,
    FHA_PROPERTY_DEFECTIVE_CONDITIONS,
    FHA_PROPERTY_EGRESS,
    FHA_PROPERTY_LEAD_PAINT,
    FHA_PROPERTY_ROOF,
    FHA_PROPERTY_THREE_S_UMBRELLA,
    FHA_PROPERTY_UNITS,
    FHA_PROPERTY_WELL_SEPTIC,
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


# --- Structure (~18) + markers -----------------------------------------------


def test_eighteen_rules_across_the_categories() -> None:
    assert len(FHA_PROPERTY_MPR_RULES) == 10
    assert len(FHA_PROPERTY_ELIGIBILITY_RULES) == 3
    assert len(FHA_DOC_RULES) == 5
    assert len(FHA_PROPERTY_DOC_RULES) == 18


def test_each_rule_has_the_uniform_structure_and_hud_markers() -> None:
    for rule in FHA_PROPERTY_DOC_RULES:
        assert rule.layer is RuleLayer.INVESTOR
        assert rule.applicability.program is FHA
        assert rule.reads
        assert isinstance(rule.condition, Condition)  # condition-as-data
        assert rule.starter is True
        assert rule.notes
        assert rule.source.type == "hud_handbook_4000_1"  # HUD, not Fannie
        assert rule.source.section
        assert rule.source.retrieved == "2026-06"


def test_rule_ids_are_namespaced_and_unique() -> None:
    ids = [r.rule_id for r in FHA_PROPERTY_DOC_RULES]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("fha.property.") or i.startswith("fha.doc.") for i in ids)


def test_mpr_in_flux_note_is_present() -> None:
    # The three-S's umbrella carries the "pending MPR modernization" (2026 RFI) caveat.
    assert "MPR modernization" in (FHA_PROPERTY_THREE_S_UMBRELLA.notes or "")


# --- The subject-to-repair conditional model (correctable vs uncorrectable) ---


def test_correctable_mpr_findings_are_yellow_uncorrectable_are_red() -> None:
    # Correctable (subject-to-repair) → YELLOW, mitigable via LP-75.
    assert FHA_PROPERTY_ROOF.severity is RuleSeverity.YELLOW
    assert FHA_PROPERTY_LEAD_PAINT.severity is RuleSeverity.YELLOW
    assert FHA_PROPERTY_THREE_S_UMBRELLA.severity is RuleSeverity.YELLOW
    # Un-correctable → RED (a harder block).
    assert FHA_PROPERTY_EGRESS.severity is RuleSeverity.RED
    assert FHA_PROPERTY_DEFECTIVE_CONDITIONS.severity is RuleSeverity.RED
    # The missing FHA appraisal (the Tier-2 anchor) is RED.
    assert FHA_DOC_FHA_APPRAISAL_PRESENT.severity is RuleSeverity.RED


def test_a_roof_deficiency_is_a_mitigable_yellow_subject_to_repair() -> None:
    facts = FileFacts(values={"property.mpr.roof_deficiency": Fact(value=Decimal("1"))})
    res = _result(evaluate(facts, [FHA_PROPERTY_ROOF]), "fha.property.mpr_roof")
    assert res.evaluated is True and res.passed is False  # a subject-to-repair finding...
    assert res.rule.severity is RuleSeverity.YELLOW  # ...correctable (resolvable via LP-75)


def test_a_no_egress_bedroom_is_a_red_block() -> None:
    facts = FileFacts(values={"property.mpr.bedroom_egress_deficiency": Fact(value=Decimal("1"))})
    res = evaluate(facts, [FHA_PROPERTY_EGRESS])[0]
    assert res.evaluated is True and res.passed is False and res.rule.severity is RuleSeverity.RED


def test_a_clean_property_passes_the_three_s_umbrella() -> None:
    facts = FileFacts(values={"property.appraisal.subject_to_repair": Fact(value=Decimal("0"))})
    assert evaluate(facts, [FHA_PROPERTY_THREE_S_UMBRELLA])[0].passed is True


# --- Tier-2 honesty: not-evaluated until the appraiser datum is captured ------


def test_tier2_deficiency_rules_are_not_evaluated_without_the_appraisal_datum() -> None:
    """The MPR rules surface a checklist — they do NOT fabricate deficiency detection.

    With no appraiser-provided fact present, each deficiency rule is recorded
    not-evaluated (graceful), never invents a pass/fail.
    """
    empty = FileFacts(values={})
    for rule in FHA_PROPERTY_MPR_RULES:
        results = evaluate(empty, [rule])
        assert results[0].evaluated is False, rule.rule_id


# --- Applicability-gating ----------------------------------------------------


def test_lead_paint_gates_on_pre_1978() -> None:
    pre = FileFacts(
        values={
            "property.year_built": Fact(value=Decimal("1965")),
            "property.mpr.lead_paint_deficiency": Fact(value=Decimal("1")),
        }
    )
    post = FileFacts(
        values={
            "property.year_built": Fact(value=Decimal("1995")),
            "property.mpr.lead_paint_deficiency": Fact(value=Decimal("1")),
        }
    )
    assert (
        evaluate(pre, [FHA_PROPERTY_LEAD_PAINT])[0].evaluated is True
    )  # pre-1978 → applies + fires
    assert (
        evaluate(post, [FHA_PROPERTY_LEAD_PAINT])[0].evaluated is False
    )  # post-1978 → not applicable


def test_well_septic_gates_on_presence() -> None:
    no_well = FileFacts(values={"property.mpr.well_septic_deficiency": Fact(value=Decimal("1"))})
    # No well/septic-present fact → the gate is closed → not applicable.
    assert evaluate(no_well, [FHA_PROPERTY_WELL_SEPTIC])[0].evaluated is False
    with_well = FileFacts(
        values={
            "property.well_septic_present": Fact(value=Decimal("1")),
            "property.mpr.well_septic_deficiency": Fact(value=Decimal("1")),
        }
    )
    assert evaluate(with_well, [FHA_PROPERTY_WELL_SEPTIC])[0].evaluated is True


def test_condo_approval_gates_on_condo() -> None:
    single_family = FileFacts(
        values={
            "property.is_condo": Fact(value=Decimal("0")),
            "property.condo.fha_project_approved": Fact(value=Decimal("0")),
        }
    )
    condo = FileFacts(
        values={
            "property.is_condo": Fact(value=Decimal("1")),
            "property.condo.fha_project_approved": Fact(value=Decimal("0")),
        }
    )
    assert evaluate(single_family, [FHA_PROPERTY_CONDO_APPROVAL])[0].evaluated is False
    res = evaluate(condo, [FHA_PROPERTY_CONDO_APPROVAL])[0]
    assert res.evaluated is True and res.passed is False  # condo without project approval → fires


def test_subject_to_repair_completion_gates_on_subject_to_status() -> None:
    rule = FHA_DOC_SUBJECT_TO_REPAIR_COMPLETION
    # Not subject-to-repair → the completion-doc requirement is not applicable.
    clean = FileFacts(values={"property.appraisal.subject_to_repair": Fact(value=Decimal("0"))})
    assert evaluate(clean, [rule])[0].evaluated is False
    # Subject-to-repair but no completion doc → fires.
    pending = FileFacts(
        values={
            "property.appraisal.subject_to_repair": Fact(value=Decimal("1")),
            "documents.repair_completion_present": Fact(value=Decimal("0")),
        }
    )
    res = evaluate(pending, [rule])[0]
    assert res.evaluated is True and res.passed is False


# --- Program-gating (FHA-only) -----------------------------------------------


def test_program_gating_resolves_fha_property_rules_only_for_fha_files() -> None:
    reg = default_registry()
    fha_ids = {r.rule_id for r in reg.resolve(program=LoanProgram.FHA, lender_slug=None)}
    conv_ids = {r.rule_id for r in reg.resolve(program=LoanProgram.CONVENTIONAL, lender_slug=None)}
    assert {"fha.property.mpr_three_s_umbrella", "fha.doc.fha_appraisal_present"} <= fha_ids
    assert not any(i.startswith("fha.property.") or i.startswith("fha.doc.") for i in conv_ids)


# --- Overlay-overrideability -------------------------------------------------


def test_a_property_requirement_is_overlay_overrideable() -> None:
    overlay = LenderOverlay(
        lender_slug="sun-west",
        overrides=(
            # An FHA overlay tightening the appraisal validity window (180 → 120 days).
            ThresholdOverride(
                rule_id="fha.property.appraisal_validity_period",
                condition=Condition(op=Operator.LE, value=Decimal("120"), unit="days"),
            ),
        ),
    )
    patched = apply_overlay([FHA_PROPERTY_APPRAISAL_VALIDITY], overlay)
    assert _by_id(patched, "fha.property.appraisal_validity_period").condition.value == Decimal(
        "120"
    )
    assert _by_id(patched, "fha.property.appraisal_validity_period").overlay_applied == "sun-west"


# --- Evaluation against an extended FHA fixture ------------------------------


def test_evaluation_against_an_extended_fha_fixture() -> None:
    """A subject-to-repair FHA file: roof + handrail deficiencies, no FHA appraisal."""
    facts = FileFacts(
        values={
            "property.appraisal.subject_to_repair": Fact(value=Decimal("1")),
            "property.mpr.roof_deficiency": Fact(value=Decimal("1")),
            "property.mpr.handrail_deficiency": Fact(value=Decimal("1")),
            "property.mpr.bedroom_egress_deficiency": Fact(value=Decimal("0")),
            "documents.fha_appraisal_present": Fact(value=Decimal("0")),
            "documents.repair_completion_present": Fact(value=Decimal("0")),
        }
    )
    results = evaluate(facts, list(FHA_PROPERTY_DOC_RULES))
    fired = {f.rule.rule_id for f in results if f.evaluated and not f.passed}
    # The three-S's umbrella (subject-to), the roof + handrail subject-to-repairs, the
    # missing FHA appraisal, and the missing repair-completion doc all fire.
    assert "fha.property.mpr_three_s_umbrella" in fired
    assert "fha.property.mpr_roof" in fired
    assert "fha.property.mpr_safe_access_handrails" in fired
    assert "fha.doc.fha_appraisal_present" in fired
    assert "fha.doc.subject_to_repair_completion" in fired
    # Egress is clean (0) → does NOT fire (the uncorrectable RED block is absent).
    assert "fha.property.mpr_bedroom_egress" not in fired
    # The egress rule WAS evaluated (datum present), it just passed.
    assert _result(results, "fha.property.mpr_bedroom_egress").passed is True


# --- DB-backed FHA file: the unit-count promotion + program-gating -----------


async def test_fha_file_promotes_unit_count_and_program_gates(db_session: AsyncSession) -> None:
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
    db_session.add(
        Property(
            loan_file_id=loan_file.id,
            property_type=PropertyType.SINGLE_FAMILY,
            address_line="1 Main",
            financed_unit_count=2,
        )
    )
    await db_session.flush()

    facts = await build_file_facts(db_session, loan_file=loan_file, as_of=date(2026, 6, 1))

    # property.unit_count is promoted from the financed unit count → the 1-4 unit rule evaluates.
    assert facts.read(("property.unit_count",)) is not None
    units = _result(evaluate(facts, [FHA_PROPERTY_UNITS]), "fha.property.units_eligibility")
    assert units.evaluated is True and units.passed is True  # 2 units <= 4
    # A single-family file → the condo-approval rule is not applicable (gate closed).
    assert evaluate(facts, [FHA_PROPERTY_CONDO_APPROVAL])[0].evaluated is False

    # Program-gating: FHA property rules resolve for this FHA file; no conv rules.
    reg = default_registry()
    resolved = {r.rule_id for r in reg.resolve(program=loan_file.loan_program, lender_slug=None)}
    assert "fha.property.units_eligibility" in resolved
    assert not any(i.startswith("conv.") for i in resolved)


def test_mpr_findings_use_property_or_documentation_categories() -> None:
    for rule in FHA_PROPERTY_MPR_RULES + FHA_PROPERTY_ELIGIBILITY_RULES:
        assert rule.category is FindingCategory.PROPERTY
    for rule in FHA_DOC_RULES:
        assert rule.category is FindingCategory.DOCUMENTATION
