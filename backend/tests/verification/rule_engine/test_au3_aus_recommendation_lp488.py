"""LP-488 — AU-3 (AUS recommendation status) and the DU/LPA vocabulary.

⚠️ EVERY VERDICT ASSERTION RUNS THROUGH A REAL RULE EVALUATION (LP-487's standing rule).

⚠️ THE `is_disputed` MISTAKE, AVOIDED ON REAL EVIDENCE. The catalog vocabulary for `aus.recommendation`
is DU's (approve_eligible / approve_ineligible / refer / out_of_scope). The ONE aus_findings document in
the 303-document corpus is an **LPA** whose recommendation reads **"ACCEPT"** — absent from that
vocabulary entirely. A rule written as `recommendation == "Approve/Eligible"` would have abstained on, or
misread, every Freddie file. ONE FIELD, TWO VENDOR ENCODINGS — CR-12's case exactly.

⚠️ THIN CORPUS: n=1, and it is the LPA. The DU cases below are RESEARCHED, not observed — no DU file
exists in our data. They abstain rather than misfire if wrong, which is the safe direction, but they are
unproven. Whether AU-3 is worth shipping on n=1 is logged for Priya.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_au3_approve_ineligible_snapshot,
    build_au3_approve_without_eligibility_snapshot,
    build_au3_du_approve_eligible_snapshot,
    build_au3_lpa_accept_snapshot,
    build_au3_refer_snapshot,
    build_au3_unknown_vendor_wording_snapshot,
)
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.derived import (
    _AUS_APPROVE_PHRASES,
    _AUS_ELIGIBLE_PHRASES,
    _AUS_INELIGIBLE_PHRASES,
    _AUS_OUT_OF_SCOPE_PHRASES,
    _AUS_REFER_PHRASES,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _one(builder) -> Verdict:
    snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=("AU-3",))
    real = [e.verdict for e in evaluations if e.verdict is not Verdict.NOT_APPLICABLE]
    assert len(real) == 1, f"expected one in-scope verdict, got {[e.verdict for e in evaluations]}"
    return real[0]


# --------------------------------------------------------------------------- #
# ⚠️ THE REAL CORPUS CASE FIRST — it is the whole argument for this rule's shape
# --------------------------------------------------------------------------- #
async def test_the_real_lpa_accept_is_satisfied() -> None:
    """The single aus_findings document in the corpus, verbatim: LPA, "ACCEPT" / "ELIGIBLE". Neither
    term is in the DU-shaped catalog vocabulary. This is the file a field-equality rule would have got
    wrong."""
    assert await _one(build_au3_lpa_accept_snapshot) is Verdict.SATISFIED


async def test_du_approve_eligible_is_satisfied() -> None:
    """DU states the eligibility INSIDE the recommendation. ⚠️ Researched, not observed."""
    assert await _one(build_au3_du_approve_eligible_snapshot) is Verdict.SATISFIED


async def test_approve_ineligible_fires() -> None:
    """Approved but not deliverable as underwritten — a real failure, not a routing note."""
    assert await _one(build_au3_approve_ineligible_snapshot) is Verdict.FIRED


async def test_a_referral_is_needs_review_not_fired() -> None:
    """A referral routes the file to manual underwriting. That is a fact about how the file must be
    documented, not a defect in it."""
    verdict = await _one(build_au3_refer_snapshot)
    assert verdict is Verdict.NEEDS_REVIEW
    assert verdict is not Verdict.FIRED


# --------------------------------------------------------------------------- #
# ⚠️ THE ABSTAINS — ADR-376's actual protection
# --------------------------------------------------------------------------- #
async def test_an_unrecognised_engine_wording_couldnt_checks() -> None:
    """A third engine's wording nobody taught the rule must NEVER read as an approval."""
    verdict = await _one(build_au3_unknown_vendor_wording_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED


async def test_an_approval_without_a_readable_eligibility_couldnt_checks() -> None:
    """⚠️ "Approve" ALONE IS NOT A CLEARANCE. Reading it as approve_eligible would turn an unread field
    into a delivery clearance — the exact silent-pass this layer exists to stop."""
    verdict = await _one(build_au3_approve_without_eligibility_snapshot)
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.SATISFIED


def test_the_catch_all_is_an_abstain_not_a_pass() -> None:
    """AU-3 ships `auto` — no human in the loop — so a `satisfied` default would turn any future
    engine's wording into a silent approval."""
    outcomes = load_rule_spec("AU-3").deterministic.outcomes
    assert [o.verdict for o in outcomes] == [
        "satisfied",
        "fired",
        "needs_review",
        "needs_review",
        "couldnt_check",
    ]
    assert outcomes[-1].default is True


# --------------------------------------------------------------------------- #
# The vocabulary, pinned to the spec
# --------------------------------------------------------------------------- #
def test_au3_vocabulary_matches_the_spec() -> None:
    """The spec's reference_values is where the DU/LPA mapping is reviewed; the recipe is what runs.
    Pinned identical so they cannot drift — the CR-12 arrangement."""
    values = load_rule_spec("AU-3").reference_values.values
    assert set(values["approve_phrases"].split("|")) == _AUS_APPROVE_PHRASES
    assert set(values["refer_phrases"].split("|")) == _AUS_REFER_PHRASES
    assert set(values["out_of_scope_phrases"].split("|")) == _AUS_OUT_OF_SCOPE_PHRASES
    assert set(values["eligible_phrases"].split("|")) == _AUS_ELIGIBLE_PHRASES
    assert set(values["ineligible_phrases"].split("|")) == _AUS_INELIGIBLE_PHRASES


def test_both_engines_wording_is_present_in_the_vocabulary() -> None:
    """⚠️ THE POINT OF THE WHOLE DESIGN. If someone later prunes the vocabulary back to one vendor's
    spelling, every file from the other silently abstains — and the corpus's only real AUS document is
    the one that would break."""
    assert "accept" in _AUS_APPROVE_PHRASES, "LPA's wording — the corpus's only real AUS document"
    assert "approve/eligible" in _AUS_APPROVE_PHRASES, "DU's wording"


def test_the_decision_and_refer_vocabularies_do_not_overlap() -> None:
    assert not (_AUS_APPROVE_PHRASES & _AUS_REFER_PHRASES)
    assert not (_AUS_APPROVE_PHRASES & _AUS_OUT_OF_SCOPE_PHRASES)
    assert not (_AUS_ELIGIBLE_PHRASES & _AUS_INELIGIBLE_PHRASES)


def test_au3_is_live_and_earned_it_through_the_gate() -> None:
    bars = load_activation_bars()
    assert "AU-3" in ACTIVE_RULE_IDS
    assert is_eligible(bars["AU-3"])
    assert bars["AU-3"].validated is False  # no-ai-dependency → validated is not read


def test_au3_reads_no_distrusted_tag() -> None:
    gated = set(load_rule_spec("AU-3").deterministic.gated_tags)
    assert not (gated & set(distrusted_tag_ids()))
