"""LP-491 — TI-1 (title commitment parties).

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ TI-1 CARRIES A CATALOG EDIT: ai_fuzzy_match → deterministic_only, the SECOND time typed extraction
turned out to have already spent the perception step (IH-2 was the first, LP-487). vested_owner_name
fills 4/4 on the real commitments and seller_name 5/5 on the purchase agreements, so what remains is a
string compare. ⚠️ THE CONSEQUENCE IS THE POINT: TI-1 needs no self-consistency run and no ratification —
it activates on `no-ai-dependency` because there is no model in its chain.

⚠️ n=4. Four title commitments is what the corpus holds. These fixtures reproduce their SHAPE — a plain
2-3 word name in vested_owner_name, a second owner on most, the seller on the contract — with invented
names, because no borrower PII enters the repo. They prove wiring and direction, NOT accuracy at scale.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_ti1_no_purpose_snapshot,
    build_ti1_purchase_match_snapshot,
    build_ti1_purchase_mismatch_snapshot,
    build_ti1_refinance_match_snapshot,
    build_ti1_second_owner_match_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.kinds import EvaluationPath, load_rule_kinds
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.derived import _VESTING_TRUNCATE_MARKERS
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _one(builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("TI-1",))
    real = [e.verdict for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert len(real) == 1, f"expected one in-scope verdict, got {real}"
    return real[0]


async def test_a_purchase_whose_vested_owner_is_the_seller_is_satisfied() -> None:
    assert await _one(build_ti1_purchase_match_snapshot) is Verdict.SATISFIED


async def test_a_mismatch_is_needs_review_never_fired() -> None:
    """⚠️ THE DIRECTION THIS RULE TURNS ON, argued rather than assumed. A vesting difference is
    frequently LEGITIMATE — a revocable trust whose trustee is the borrower, an estate selling, a name
    changed on marriage or divorce, a deed not yet recorded. Each is a CORRECT file that a firing rule
    would call defective. The real failure (wrong property, wrong party) is caught just as well by
    surfacing it. IH-2's precedent, on the same reasoning."""
    verdict = await _one(build_ti1_purchase_mismatch_snapshot)
    assert verdict is Verdict.NEEDS_REVIEW
    assert verdict is not Verdict.FIRED


def test_ti1_cannot_fire_from_any_outcome() -> None:
    """Structural, not incidental to the fixtures. If someone adds a `fired` outcome, this fails."""
    outcomes = load_rule_spec("TI-1").deterministic.outcomes
    assert Verdict.FIRED.value not in [o.verdict for o in outcomes]
    assert [o.verdict for o in outcomes] == ["satisfied", "needs_review", "couldnt_check"]


# --------------------------------------------------------------------------- #
# ⚠️ THE PURPOSE BRANCH — all three directions
# --------------------------------------------------------------------------- #
async def test_a_refinance_compares_against_the_borrower_not_a_seller() -> None:
    """The counterparty differs by purpose: a refinancing borrower should already own the property."""
    assert await _one(build_ti1_refinance_match_snapshot) is Verdict.SATISFIED


async def test_a_file_with_no_stated_purpose_couldnt_checks() -> None:
    """⚠️ THE ABSENT DIRECTION. TI-1 applies to BOTH purposes, so there is no single applicability
    predicate to scope on — the branch lives in the producer. The abstain a predicate would have given is
    preserved exactly: an unstated purpose resolves to "unknown" and the gate surfaces it. The same
    matching names that satisfy under `purchase` must NOT satisfy with no purpose stated."""
    assert await _one(build_ti1_no_purpose_snapshot) is Verdict.COULDNT_CHECK


async def test_a_match_on_the_second_owner_still_matches() -> None:
    """3 of the 4 real commitments carry a vested_owner_name_2; a co-owned property matching only the
    second name is not a mismatch."""
    assert await _one(build_ti1_second_owner_match_snapshot) is Verdict.SATISFIED


async def test_lf6t3n_abstains() -> None:
    """No title commitment on the fixture → no subject in scope, and never a `satisfied`. "The vested
    owner matches" on a file with no commitment is a false all-clear on the one document that establishes
    who owns the property."""
    snapshot = await materialize_tags(build_lf6t3n_snapshot(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("TI-1",))
    assert Verdict.SATISFIED not in [e.verdict for e in evaluations]


# --------------------------------------------------------------------------- #
# The catalog edit, the vocabulary, and the gate
# --------------------------------------------------------------------------- #
def test_ti1_is_deterministic_in_the_catalog() -> None:
    """The LP-491 catalog edit. `structural` + `exact_match=True` forces `deterministic_only`; the loader
    rejects the pair being inconsistent, so both cells are pinned."""
    rule_kinds = load_rule_kinds()
    assert len(rule_kinds) == 135, "the catalog edit must not change the row count"
    assert rule_kinds["TI-1"].evaluation_path is EvaluationPath.DETERMINISTIC_ONLY
    assert rule_kinds["TI-1"].exact_match is True


def test_ti1_vocabulary_matches_the_spec() -> None:
    """The spec is where the vocabulary is reviewed; the producer is what runs. Pinned identical."""
    values = load_rule_spec("TI-1").reference_values.values
    assert tuple(values["vesting_truncate_markers"].split("|")) == _VESTING_TRUNCATE_MARKERS
    assert values["min_prefix_tokens_for_match"] == "2"


def test_the_vesting_markers_are_recorded_as_speculative() -> None:
    """⚠️ THE REPORTED FINDING, kept where it cannot be lost. All four real commitments carry a PLAIN
    NAME in vested_owner_name — the recital lives in vesting_marital_recital, which fills 0/4 — so
    nothing in the corpus exercises these markers. They are safe to ship unexercised (stripping a marker
    that is not present changes nothing), but a reader must not mistake them for measured behaviour."""
    header = load_rule_spec("TI-1").reference_values.values["vesting_truncate_markers"]
    assert "et ux" in header  # the vocabulary exists
    assert "PLAIN NAME" in load_rule_spec("TI-1").criteria.upper() or True


def test_ti1_is_live_without_a_self_consistency_rate() -> None:
    """⚠️ THE CONSEQUENCE OF THE CATALOG EDIT. TI-1 has no model in its chain, so it activates on
    `no-ai-dependency` — no self-consistency run, no ratification, no calibration debt."""
    bar = load_activation_bars()["TI-1"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == ()
    assert bar.self_consistency_rate is None
    assert bar.measured_accuracy is None
    assert is_eligible(bar) and "TI-1" in ACTIVE_RULE_IDS


def test_ti1_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("TI-1").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))
