"""LP-494 — CO-4 (HOA replacement reserves) and CO-5 (litigation / delinquency / concentration).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION — materialize_tags() then evaluate_rules()
— never by calling a recipe or the gate directly. That is the LP-487 standing rule, and it exists because
LP-508 shipped a guard whose own test called ``evaluate_gate`` with tag ids: the mechanism worked, the
WIRING did not, and the guard reached 1 of the 5 rules it claimed to protect. The recipe-level tests are
additions to the end-to-end ones, never substitutes.

⚠️ BOTH RULES WERE BUILT INERT; the LP-494 revision ACTIVATED them, and the tests below pin the LIVE state. `input_resolves` is false because no loan
file carries a condo questionnaire and the two in the bench corpus are a CANCELLATION NOTICE and a
genuinely UNANSWERED standard form. Every fixture here is therefore SELF-AUTHORED (ADR-332, and the LP-487
amendment): it may pin the LOGIC and the DIRECTION, never the LABEL — none of it is evidence of accuracy.

⚠️ CO-4 CARRIES THE SYSTEM'S FIRST DATE-KEYED THRESHOLD (ADR-379). The reserve floor is 10% before
2027-01-04 and 15% on or after (LL-2026-03), keyed on the LOAN APPLICATION DATE and never on today's — so
the same 12% budget is adequate for a 2026 application and short for a 2027 one, and with no application
date the rule abstains rather than picking a floor. All three cases are proven end to end below.

⚠️ CO-5 INVENTS NO LITIGATION THRESHOLD. B4-2.1-03 turns on the nature and scope of the action, so
disclosed litigation is needs_review — surfaced — and a test pins that no outcome can fire on it alone.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_co3_fidelity_amount_disagreement_snapshot,
    build_co3_fidelity_disagreement_snapshot,
    build_co3_fidelity_present_snapshot,
    build_co4_adequate_2026_snapshot,
    build_co4_blank_questionnaire_snapshot,
    build_co4_no_application_date_snapshot,
    build_co4_not_condo_snapshot,
    build_co4_reserves_from_hoa_statement_snapshot,
    build_co4_same_pct_2027_snapshot,
    build_co4_short_2026_snapshot,
    build_co5_blank_questionnaire_snapshot,
    build_co5_clear_snapshot,
    build_co5_concentration_snapshot,
    build_co5_delinquent_snapshot,
    build_co5_litigation_snapshot,
    build_co5_unrecognised_litigation_snapshot,
)
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.kinds import EvaluationPath, RuleKindName, load_rule_kinds
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import (
    _CONDO_MAX_COMMERCIAL_PCT,
    _CONDO_MAX_DELINQUENT_PCT,
    _CONDO_RESERVE_MIN_PCT_BEFORE,
    _CONDO_RESERVE_MIN_PCT_FROM,
    _CONDO_RESERVE_STEP_UP_DATE,
    _CONDO_SINGLE_ENTITY_MAX_PCT_21_PLUS,
    _CONDO_SINGLE_ENTITY_MAX_UNITS_SMALL,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _evaluations(builder, rule_id: str):
    """Run the rule END TO END: parsed + derived materialisation, then the real evaluator."""
    snapshot: Snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=(rule_id,))
    return evaluations


async def _one(builder, rule_id: str):
    """The single in-scope evaluation, dropping per-document not_applicables."""
    evaluations = await _evaluations(builder, rule_id)
    real = [e for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert len(real) == 1, (
        f"{rule_id}: expected one in-scope verdict, got {[e.verdict for e in evaluations]}"
    )
    return real[0]


async def _verdict(builder, rule_id: str) -> Verdict:
    return (await _one(builder, rule_id)).verdict


# --------------------------------------------------------------------------- #
# CO-4 — the date-keyed reserve floor, end to end
# --------------------------------------------------------------------------- #
async def test_co4_adequate_reserves_on_a_2026_application_is_satisfied() -> None:
    assert await _verdict(build_co4_adequate_2026_snapshot, "CO-4") is Verdict.SATISFIED


async def test_co4_short_reserves_fires() -> None:
    assert await _verdict(build_co4_short_2026_snapshot, "CO-4") is Verdict.FIRED


async def test_co4_the_same_percentage_fires_on_a_2027_application() -> None:
    """⚠️ THE WHOLE POINT OF THE DATE KEY, proven by holding everything else constant.

    12% satisfies a 2026-06-08 application (10% floor) and FIRES on a 2027-01-04 one (15% floor,
    LL-2026-03). If the rule ever keys on today's date instead of the application's, this pair breaks.
    """
    assert await _verdict(build_co4_adequate_2026_snapshot, "CO-4") is Verdict.SATISFIED
    assert await _verdict(build_co4_same_pct_2027_snapshot, "CO-4") is Verdict.FIRED


async def test_co4_without_an_application_date_abstains() -> None:
    """⚠️ THE DATE SELECTS THE COMPARISON, so its absence cannot be defaulted. Defaulting to today would
    apply next year's floor to this year's application and fire on a compliant project.

    ⚠️ The gate substitutes its own reasoning for an "unknown" tag, so WHY it abstained is asserted on the
    LOAD-BEARING TAG the finding carries — which is where a processor reads it too."""
    evaluation = await _one(build_co4_no_application_date_snapshot, "CO-4")
    assert evaluation.verdict is Verdict.COULDNT_CHECK
    reasons = " ".join(tag.reasoning or "" for tag in evaluation.load_bearing_tags).lower()
    assert "application date" in reasons, reasons


async def test_co4_never_satisfied_on_an_unanswered_questionnaire() -> None:
    """⚠️ THE FALSE ALL-CLEAR THIS RULE MUST NEVER GIVE — and the shape the real corpus is actually in."""
    assert await _verdict(build_co4_blank_questionnaire_snapshot, "CO-4") is Verdict.COULDNT_CHECK


async def test_co4_is_not_applicable_on_a_non_condo() -> None:
    """⚠️ ONLY a DEFINITELY-non-condo property is out of scope. A file that does not state its property
    type couldnt_checks instead (the applicability-predicate discipline, IH-7/LP-487) — see the blank and
    dateless cases above, both of which reach the rule rather than being skipped."""
    evaluations = await _evaluations(build_co4_not_condo_snapshot, "CO-4")
    assert [e.verdict for e in evaluations] == [Verdict.NOT_APPLICABLE]


# --------------------------------------------------------------------------- #
# CO-5 — the four legs, end to end
# --------------------------------------------------------------------------- #
async def test_co5_a_clean_project_is_satisfied() -> None:
    assert await _verdict(build_co5_clear_snapshot, "CO-5") is Verdict.SATISFIED


async def test_co5_delinquency_above_the_limit_fires() -> None:
    """22 of 60 units 60+ days past due = 36.7%, above B4-2.2-02's 15%. ⚠️ The COUNT drives it, not a
    generic delinquency percentage — the cap is stated on units 60 or more days past due."""
    evaluation = await _one(build_co5_delinquent_snapshot, "CO-5")
    assert evaluation.verdict is Verdict.FIRED


async def test_co5_single_entity_concentration_above_the_tier_fires() -> None:
    """18 of 60 units = 30%, above B4-2.1-03's 20% for a project of 21+ units. ⚠️ The ticket's two sources
    said >20% and 10%; the primary says neither in isolation — it is TIERED, and this pins the tier."""
    assert await _verdict(build_co5_concentration_snapshot, "CO-5") is Verdict.FIRED


async def test_co5_litigation_is_needs_review_never_fired() -> None:
    """⚠️ THE DELIBERATE REFUSAL. Fannie assesses litigation on nature and scope; a slip-and-fall covered
    by insurance does not make a project ineligible. Firing would call a correct file defective, and
    inventing a threshold to decide it would be worse."""
    assert await _verdict(build_co5_litigation_snapshot, "CO-5") is Verdict.NEEDS_REVIEW


async def test_co5_never_satisfied_on_an_unanswered_questionnaire() -> None:
    """⚠️ "clear" REQUIRES THE LEGS TO HAVE BEEN READ. Reporting a project eligible because nobody answered
    the questions is the exact false all-clear this lane exists to prevent — and the corpus's two
    questionnaires are both unanswered, so this is the branch that runs on real data."""
    assert await _verdict(build_co5_blank_questionnaire_snapshot, "CO-5") is Verdict.COULDNT_CHECK


async def test_co5_an_unrecognised_litigation_answer_abstains() -> None:
    """ADR-376's direction, on the answer where it matters most: an unrecognised value is never read as
    "no litigation"."""
    assert (
        await _verdict(build_co5_unrecognised_litigation_snapshot, "CO-5") is Verdict.COULDNT_CHECK
    )


# --------------------------------------------------------------------------- #
# The scope fences, the thresholds, and the inert state
# --------------------------------------------------------------------------- #
def test_co3_and_co4_are_live_and_co5_is_held() -> None:
    """⚠️ THE SPLIT, AND WHY IT IS NOT ARBITRARY.

    CO-3 and CO-4 activate because their inputs RESOLVE ON REAL STORED DATA — LP-485's development-mode
    bar. CO-3's fidelity pair fills 8/8 on the bench's master policies; CO-4's reserve percentage reads
    from the HOA STATEMENT type, which is where HOA BUDGETS classify.

    ⚠️ CO-5 IS HELD, and it is the one blocker research could not remove: NOT ONE of its five inputs
    resolves on any document of any type. `hoa_certification` declares every one of them and ZERO such
    documents exist — ADR-354 exactly. Activating it would couldnt_check on 100% of files forever with
    every test green (ADR-286/289)."""
    bars = load_activation_bars()
    for rule_id in ("CO-3", "CO-4"):
        assert bars[rule_id].input_resolves is True, rule_id
        assert is_eligible(bars[rule_id]) is True, rule_id
        assert rule_id in ACTIVE_RULE_IDS, rule_id
    assert bars["CO-5"].input_resolves is False
    assert is_eligible(bars["CO-5"]) is False
    assert "CO-5" not in ACTIVE_RULE_IDS
    for rule_id in ("CO-3", "CO-4", "CO-5"):
        # ⚠️ AND NEITHER MAY EVER CARRY A SELF-CONSISTENCY RATE. There are ZERO cases to derive over, and
        # both rules are deterministic — a rate here could only ever be an artifact (the CR-8 / LP-491
        # shape), which is why no model call was made for this ticket.
        assert bars[rule_id].self_consistency_rate is None, rule_id
        assert bars[rule_id].measured_accuracy is None, rule_id


def test_neither_rule_reads_the_sourceless_warrantability_tag() -> None:
    """⚠️ THE SCOPE FENCE, extended from CO-1's. `property.is_warrantable_condo` is a project-review
    CONCLUSION with no source field in any of the 121 schema specs; the catalog maps CO-3 and CO-5 to it,
    and nothing here is wired to it. CO-5 reads typed questionnaire fields instead."""
    assert "property.is_warrantable_condo" not in load_declarations()
    for rule_id in ("CO-4", "CO-5"):
        spec = load_rule_spec(rule_id)
        assert spec.deterministic is not None
        tags = set(spec.deterministic.load_bearing_tags) | set(spec.deterministic.gated_tags)
        assert "property.is_warrantable_condo" not in tags, rule_id


def test_co3_checks_fidelity_only_and_never_duplicates_ih7() -> None:
    """⚠️ THE UN-DROP, PINNED IN BOTH DIRECTIONS. CO-3 was dropped earlier in this ticket as an IH-7
    duplicate; that was wrong. IH-7 reads ins.condo_master_policy (presence, replacement-cost basis,
    liability limit); CO-3 reads ins.condo_fidelity_coverage — the leg IH-7's OWN header excludes."""
    co3 = load_rule_spec("CO-3").deterministic
    ih7 = load_rule_spec("IH-7").deterministic
    assert co3 is not None and ih7 is not None
    assert set(co3.gated_tags) == {"ins.condo_fidelity_coverage"}
    assert set(ih7.gated_tags) == {"ins.condo_master_policy"}
    assert not (set(co3.gated_tags) & set(ih7.gated_tags))


def test_co3_absent_fidelity_is_needs_review_never_fired() -> None:
    """⚠️ A project of 20 units or fewer is EXEMPT (B7-4-02) and no document states the unit count, so
    firing would call a correct file defective. Pinned as a spec property."""
    spec = load_rule_spec("CO-3")
    assert spec.deterministic is not None
    for outcome in spec.deterministic.outcomes:
        assert outcome.verdict != Verdict.FIRED.value, outcome.verdict


def test_the_catalog_edits_are_recorded_and_the_row_count_is_unchanged() -> None:
    """Both edits answer LP-487's question — has typed extraction already spent the perception step? — and
    both are visible in the csv rationale rather than being silent."""
    kinds = load_rule_kinds()
    assert (
        len(kinds) == 137
    )  # LP-519 +AS-13 (repeated same-amount deposits — INERT, bar held on measurement)  # LP-509-D1 +IH-9 (hazard policy expired)
    co4, co5 = kinds["CO-4"], kinds["CO-5"]
    # CO-4 stays calculative (its threshold needs sign-off) but loses the AI half of the bookend.
    assert co4.kind is RuleKindName.CALCULATIVE
    assert co4.evaluation_path is EvaluationPath.DETERMINISTIC_BOOKEND
    assert co4.threshold_needs_signoff is True
    # CO-5 was judgmental against a sourceless tag; its real inputs are typed fields.
    assert co5.kind is RuleKindName.STRUCTURAL
    assert co5.evaluation_path is EvaluationPath.DETERMINISTIC_ONLY
    for rule_id in ("CO-4", "CO-5"):
        assert "LP-494" in kinds[rule_id].rationale or "typed" in kinds[rule_id].rationale.lower()


def test_no_outcome_can_fire_on_litigation_alone() -> None:
    """⚠️ Pinned as a SPEC PROPERTY, not just a fixture result: the only outcome keyed on
    "litigation_disclosed" is needs_review. A future edit that promotes it to fired breaks this."""
    spec = load_rule_spec("CO-5")
    assert spec.deterministic is not None
    for outcome in spec.deterministic.outcomes:
        for condition in outcome.when_tags:
            if condition.value == "litigation_disclosed":
                assert outcome.verdict == Verdict.NEEDS_REVIEW.value


def test_thresholds_match_their_declared_reference_values() -> None:
    """⚠️ THE DRIFT GUARD THAT MAKES "declared as data" REAL. Every constant the recipes compare against is
    pinned to the spec's cited reference_values, so the code and the citation cannot part company — the
    thing ADR-361 is actually protecting."""
    co4 = load_rule_spec("CO-4").reference_values.values
    assert Decimal(co4["min_reserve_pct_before_step_up"]) == _CONDO_RESERVE_MIN_PCT_BEFORE
    assert Decimal(co4["min_reserve_pct_from_step_up"]) == _CONDO_RESERVE_MIN_PCT_FROM
    assert (
        date.fromisoformat(co4["reserve_step_up_application_date"]) == _CONDO_RESERVE_STEP_UP_DATE
    )

    co5 = load_rule_spec("CO-5").reference_values.values
    assert Decimal(co5["max_delinquent_units_pct"]) == _CONDO_MAX_DELINQUENT_PCT
    assert Decimal(co5["max_commercial_space_pct"]) == _CONDO_MAX_COMMERCIAL_PCT
    assert (
        Decimal(co5["max_single_entity_pct_21_plus_units"]) == _CONDO_SINGLE_ENTITY_MAX_PCT_21_PLUS
    )
    assert (
        Decimal(co5["max_single_entity_units_5_to_20_units"])
        == _CONDO_SINGLE_ENTITY_MAX_UNITS_SMALL
    )


def test_no_distrust_overlap() -> None:
    """LP-508 — including derived tags, which field-name resolution does not reach."""
    distrusted = distrusted_tag_ids()
    for rule_id in ("CO-4", "CO-5"):
        spec = load_rule_spec(rule_id)
        assert spec.deterministic is not None
        assert not (set(spec.deterministic.gated_tags) & set(distrusted)), rule_id


def test_every_parsed_condo_tag_is_document_type_scoped() -> None:
    """⚠️ LP-487's discipline. `total_units` in particular is a plausible field name on other forms; an
    unscoped read would let an unrelated document decide a project's concentration tier."""
    declarations = load_declarations()
    for tag_id in (
        "condo.commercial_space_pct",
        "condo.total_units",
        "condo.single_entity_owned_units",
        "condo.litigation_disclosed",
    ):
        declaration = declarations[tag_id]
        assert declaration.document_type == "condo_questionnaire", tag_id


# --------------------------------------------------------------------------- #
# LP-494 review — the load-bearing paths of both LIVE rules, which nothing exercised
# --------------------------------------------------------------------------- #
async def test_co4_resolves_from_an_hoa_statement_not_only_a_questionnaire() -> None:
    """⚠️ THE PATH THE ACTIVATION RESTS ON (reported finding). `input_resolves: true` is justified by the
    reserve percentage resolving from an HOA STATEMENT — HOA budgets classify as `hoa_statement`, not
    `condo_questionnaire` — yet every CO-4 fixture fed the questionnaire field, so the wiring the
    activation depends on was never run. This is the file's own cited LP-508 lesson: the mechanism
    worked, the WIRING did not."""
    assert (
        await _verdict(build_co4_reserves_from_hoa_statement_snapshot, "CO-4") is Verdict.SATISFIED
    )


async def test_co3_reads_a_master_policy_that_evidences_fidelity_cover() -> None:
    """⚠️ CO-3 had NO snapshot fixture at all — its tests asserted spec shape only, so the recipe deciding
    a LIVE rule's verdict was never executed."""
    assert await _verdict(build_co3_fidelity_present_snapshot, "CO-3") is Verdict.SATISFIED


async def test_co3_abstains_when_two_master_policies_disagree() -> None:
    """⚠️ A contradiction BETWEEN documents used to fall to the unrecognised-value branch and report
    "the indicator reads 'no', which is not a recognised yes/no answer" — where 'no' plainly IS
    recognised. Right verdict, false reason, and it hid the disagreement."""
    result = await _one(build_co3_fidelity_disagreement_snapshot, "CO-3")
    assert result.verdict is Verdict.COULDNT_CHECK
    assert "not a recognised yes/no answer" not in (result.reasoning or "")


async def test_co3_amount_disagreement_does_not_veto_evidenced_coverage() -> None:
    """⚠️ The AMOUNT is evidence this rule never judges (B7-4-02's required figure needs a unit count and
    an assessment base that resolve nowhere here), so two policies stating $50,000 and $75,000 — a
    prior-year certificate beside the current renewal — must not flip a clearly evidenced `present` to
    couldnt_check."""
    assert (
        await _verdict(build_co3_fidelity_amount_disagreement_snapshot, "CO-3") is Verdict.SATISFIED
    )
