"""LP-495a — RE-1 (undisclosed mortgage obligation) and DT-6 (stated payment vs. billed payment).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule) —
`materialize_tags()` → `evaluate_rules()`, never a recipe or the gate called directly. LP-508 shipped a
guard whose own test bypassed the wiring and it reached 1 of 5 rules.

⚠️ ONE MATCHER SERVES BOTH RULES (ADR-375). Both read tags produced by the same `_reo_match_statement`,
so RE-1 and DT-6 can never disagree about which stated liability a given statement matched. A test below
pins that they are wired to the same matcher rather than to two.

⚠️ NEITHER RULE MAY EVER PRODUCE `fired`, AND THAT IS A SPEC PROPERTY PINNED BY TEST. Both surface a
discrepancy as needs_review and hand the retention question to the processor. An unmatched statement can
be a paid-off loan, a duplicate or a co-signed debt; an understated payment can be a property under
contract.

⚠️ NEITHER READS `property.is_retained_reo` OR `property.retained_pitia` — those stay vocabulary orphans
with no producer, pinned below exactly as CO-1's test pins `property.is_warrantable_condo`.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_dt6_covered_snapshot,
    build_dt6_escrow_double_count_guard_snapshot,
    build_dt6_short_snapshot,
    build_re1_ambiguous_snapshot,
    build_re1_disclosed_snapshot,
    build_re1_no_lender_snapshot,
    build_re1_no_stated_liabilities_snapshot,
    build_re1_undisclosed_snapshot,
)
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_RETENTION_TAGS = ("property.is_retained_reo", "property.retained_pitia")


async def _one(builder, rule_id: str) -> Verdict:
    """One verdict from a real evaluation. `only_groups=frozenset()` runs NO AI group — these rules are
    deterministic and must never reach a model."""
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=(rule_id,))
    assert len(evaluations) == 1, f"{rule_id} is per-document over one statement, got {evaluations}"
    return evaluations[0].verdict


# --------------------------------------------------------------------------- #
# RE-1 — is the statement's obligation disclosed on the application?
# --------------------------------------------------------------------------- #
async def test_a_statement_matching_a_stated_liability_is_satisfied() -> None:
    """⚠️ THE NO-FALSE-FINDING DIRECTION the ticket names explicitly: a mortgage statement that DOES match
    a stated liability must not be flagged. The names differ in form ("... Servicing LLC" vs the app's
    shorter rendering) — ordinary corpus variance the token-prefix matcher absorbs."""
    assert await _one(build_re1_disclosed_snapshot, "RE-1") is Verdict.SATISFIED


async def test_an_unmatched_statement_needs_review_and_never_fires() -> None:
    assert await _one(build_re1_undisclosed_snapshot, "RE-1") is Verdict.NEEDS_REVIEW


async def test_a_statement_with_no_lender_name_couldnt_checks() -> None:
    """⚠️ THE ~24% ABSTAIN. `lender_name` fills 54/71 in the corpus. Reading an unnamed statement as an
    undisclosed debt is the fail-OPEN direction; this pins it shut."""
    assert await _one(build_re1_no_lender_snapshot, "RE-1") is Verdict.COULDNT_CHECK


async def test_no_stated_liabilities_couldnt_checks_never_undisclosed() -> None:
    """⚠️ THE MOST IMPORTANT ABSTAIN. A file whose application states no mortgage liabilities — never
    imported, or an import that carried none — must not read as a file full of undisclosed debts."""
    assert await _one(build_re1_no_stated_liabilities_snapshot, "RE-1") is Verdict.COULDNT_CHECK


async def test_two_matching_liabilities_couldnt_checks() -> None:
    """A first and a second mortgage with one servicer is ordinary; picking one would attach DT-6's
    payment comparison to a liability chosen by list order."""
    assert await _one(build_re1_ambiguous_snapshot, "RE-1") is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# DT-6 — does the stated payment cover the servicer's billed total?
# --------------------------------------------------------------------------- #
async def test_a_stated_payment_at_the_billed_total_is_satisfied() -> None:
    assert await _one(build_dt6_covered_snapshot, "DT-6") is Verdict.SATISFIED


async def test_a_short_stated_payment_needs_review_and_never_fires() -> None:
    assert await _one(build_dt6_short_snapshot, "DT-6") is Verdict.NEEDS_REVIEW


async def test_escrow_is_not_added_to_the_statements_total() -> None:
    """⚠️ THE DOUBLE-COUNT GUARD — the one test that catches the likeliest wrong build of DT-6.

    The statement bills 1450.00 TOTAL with 310.00 of it escrow; the application states 1450.00. The
    extraction prompt defines `monthly_payment` as "the total monthly payment (principal+interest+escrow)"
    and `escrow_amount` as "the escrow PORTION of the payment" — escrow is a COMPONENT, not an addend, so
    the stated figure COVERS the obligation.

    An implementation comparing against `monthly_payment + escrow_amount` (1760.00) would report this
    compliant file short, and on the corpus would do so for all 50 of the 67 statements that fill both
    fields."""
    assert await _one(build_dt6_escrow_double_count_guard_snapshot, "DT-6") is Verdict.SATISFIED


async def test_an_unmatched_statement_couldnt_checks_for_dt6() -> None:
    """DT-6 abstains on the discrepancy RE-1 already surfaced rather than reporting it twice."""
    assert await _one(build_re1_undisclosed_snapshot, "DT-6") is Verdict.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# The design properties, pinned
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rule_id", ["RE-1", "DT-6"])
def test_neither_rule_can_ever_fire(rule_id: str) -> None:
    """⚠️ A SPEC PROPERTY, NOT A HAPPENSTANCE OF THE FIXTURES. Neither rule may declare a `fired` outcome
    at all: both surface a discrepancy and hand the retention question to the processor. RE-2 stays
    dropped precisely because it asserted a CONSEQUENCE from the retention inference."""
    spec = load_rule_spec(rule_id)
    assert spec.deterministic is not None
    verdicts = {outcome.verdict for outcome in spec.deterministic.outcomes}
    assert "fired" not in verdicts, f"{rule_id} declares a fired outcome — it must only surface"
    assert verdicts == {"satisfied", "needs_review", "couldnt_check"}


@pytest.mark.parametrize("rule_id", ["RE-1", "DT-6"])
def test_retention_tags_are_not_wired_into_either_rule(rule_id: str) -> None:
    """⚠️ THE SCOPE FENCE, the CO-1 precedent applied. `property.is_retained_reo` and
    `property.retained_pitia` have NO source anywhere — "retained" is an inference no document, extractor
    field or MISMO fact states. If someone declares them against an invented source and either rule starts
    reading them, this fails: these rules SURFACE a discrepancy, they do not assert retention."""
    for tag in _RETENTION_TAGS:
        assert tag not in load_declarations(), (
            f"{tag} gained a producer — retention is still an inference"
        )
    spec = load_rule_spec(rule_id)
    assert spec.deterministic is not None
    for tag in _RETENTION_TAGS:
        assert tag not in spec.deterministic.load_bearing_tags
        assert tag not in spec.deterministic.gated_tags


def test_one_matcher_serves_both_rules() -> None:
    """⚠️ ADR-375, pinned. RE-1 and DT-6 read DIFFERENT tags, but both tags come from the SAME matcher
    function — so the two rules cannot disagree about which stated liability a statement matched. If a
    second matcher is ever introduced, the shared-source assertion below is what catches it."""
    import inspect

    from app.verification.tag_materialization import derived

    for recipe in (derived._reo_statement_disclosure, derived._reo_statement_payment_coverage):
        source = inspect.getsource(recipe)
        assert "_reo_match_statement(" in source, (
            f"{recipe.__name__} no longer calls the shared matcher — ADR-375 requires ONE matcher "
            "serving both rules"
        )
    assert tuple(load_rule_spec("RE-1").deterministic.gated_tags) == ("reo.statement_disclosure",)
    assert tuple(load_rule_spec("DT-6").deterministic.gated_tags) == (
        "reo.statement_payment_coverage",
    )


@pytest.mark.parametrize("rule_id", ["RE-1", "DT-6"])
def test_both_rules_are_active_and_eligible(rule_id: str) -> None:
    assert rule_id in ACTIVE_RULE_IDS
    bar = load_activation_bars()[rule_id]
    assert bar.status == "no-ai-dependency", (
        "deterministic — no AI tag, so no rate and no ratification"
    )
    assert bar.input_resolves is True
    assert bar.load_bearing_ai_tags == ()
    assert is_eligible(bar)


@pytest.mark.parametrize("rule_id", ["RE-1", "DT-6"])
def test_neither_rule_ratifies(rule_id: str) -> None:
    """⚠️ DETERMINISTIC RULES CARRY NO RATIFICATION. Ratification is the safety substitute for a
    self-consistency rate (ADR-378); these rules have no model in their chain, so they must not be on the
    ratify-pending status at all."""
    from app.verification.rule_engine.activation_bars import ratifies_every_finding

    assert not ratifies_every_finding(rule_id)


async def test_a_missing_mortgage_statement_is_never_satisfied() -> None:
    """⚠️ NEVER SATISFIED ON A MISSING DOCUMENT, BY CODE PATH. A file with no mortgage statement yields no
    subject in scope, so neither rule can report a pass. `applicability_expected` is false deliberately —
    most borrowers own one property, so a missing statement is not a gap."""
    snapshot = await materialize_tags(build_re1_disclosed_snapshot(), only_groups=frozenset())
    # Strip the statement: the documents section is present but carries nothing in scope.
    stripped = snapshot.model_copy(
        update={"documents": snapshot.documents.model_copy(update={"entries": []})}
    )
    for rule_id in ("RE-1", "DT-6"):
        evaluations, _tags = await evaluate_rules(stripped, rule_ids=(rule_id,))
        assert all(e.verdict is not Verdict.SATISFIED for e in evaluations), (
            f"{rule_id} reported satisfied with no mortgage statement in the file"
        )
        assert all(e.verdict is not Verdict.FIRED for e in evaluations)
    assert load_rule_spec("RE-1").deterministic.applicability_expected is False
    assert load_rule_spec("DT-6").deterministic.applicability_expected is False
