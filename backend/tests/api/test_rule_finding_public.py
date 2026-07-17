"""RuleFindingPublic's derivations (LP-376-B) — the ratification badge + the category, from the gate of
record, NOT the misleading legacy fields.

Three correctness bugs the first human view of the tabs exposed:
* the ratification badge was `not priya_validated` (true for nearly every rule) — it must be ONLY an AI
  judgment verdict a human must ratify (a judgment rule that reached a verdict);
* the category was the legacy `FindingCategory` enum (no Identity/Occupancy → ID-8 read "Assets") — it must
  be the rule's OWN family from its spec.
These are pure read-path derivations, asserted here directly on ``RuleFindingPublic.from_model``.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingResolutionStatus,
    FindingStatus,
)
from app.schemas.verification import RuleFindingPublic


def _finding(
    rule_id: str, outcome: EvaluationOutcome, *, status: FindingStatus = FindingStatus.YELLOW
) -> Finding:
    """A governed finding whose PERSISTED category (assets) + gated_pending_signoff (true) are the WRONG
    legacy values — so the assertions prove the derivations override them from the spec, not echo them."""
    return Finding(
        id=uuid4(),
        loan_file_id=uuid4(),
        rule_id=rule_id,
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=status,
        category=FindingCategory.ASSETS,  # the wrong legacy value — must be overridden by the spec
        message="a message",
        evaluation_outcome=outcome,
        subject_key="s",
        load_bearing_tags=[],
        details={"gated_pending_signoff": True},  # = not priya_validated — must NOT drive the badge
        resolution_status=FindingResolutionStatus.OPEN,
        confidence=1.0,
    )


# --------------------------------------------------------------------------- #
# BUG 1 — the ratification badge (both directions: always-on and always-off are equally useless)
# --------------------------------------------------------------------------- #
def test_judgment_verdict_is_ratification_pending() -> None:
    # OC-2 + ID-8 are JUDGMENT rules that reached a verdict → an AI judged → a human must ratify.
    for rule_id in ("OC-2", "ID-8"):
        pub = RuleFindingPublic.from_model(_finding(rule_id, EvaluationOutcome.NEEDS_REVIEW))
        assert pub.ratification_pending is True, rule_id


def test_deterministic_and_consistency_are_not_ratification_pending() -> None:
    # NOT judgment rules → no AI verdict → NO badge, even though gated_pending_signoff is true.
    assert (
        RuleFindingPublic.from_model(
            _finding("ID-3", EvaluationOutcome.COULDNT_CHECK)
        ).ratification_pending
        is False
    )
    assert (
        RuleFindingPublic.from_model(
            _finding("ID-2", EvaluationOutcome.COULDNT_CHECK)
        ).ratification_pending
        is False
    )
    assert (
        RuleFindingPublic.from_model(
            _finding("ID-4", EvaluationOutcome.COULDNT_CHECK)
        ).ratification_pending
        is False
    )
    assert (
        RuleFindingPublic.from_model(
            _finding("AS-1", EvaluationOutcome.SATISFIED)
        ).ratification_pending
        is False
    )
    assert (
        RuleFindingPublic.from_model(_finding("IN-2", EvaluationOutcome.OPEN)).ratification_pending
        is False
    )


def test_judgment_rule_that_never_judged_is_not_ratification_pending() -> None:
    # ID-9 is a judgment rule, but a couldnt_check means the gate/applicability terminated BEFORE the AI —
    # no verdict was made, so nothing awaits ratification. (The always-on badge painted this too.)
    pub = RuleFindingPublic.from_model(_finding("ID-9", EvaluationOutcome.COULDNT_CHECK))
    assert pub.ratification_pending is False


def test_persisted_engine_signal_is_authoritative_including_fuzzy_consistency() -> None:
    # LP-376-B review: the engine's OWN per-finding ratification_pending (persisted in details) drives the
    # badge — so a FUZZY-consistency AI verdict (ID-4 fired via the AI residue judge) is marked, which the
    # judgment-only fallback would miss, and a deterministic bookend can be cleared.
    fuzzy_ai = _finding("ID-4", EvaluationOutcome.OPEN)
    fuzzy_ai.details = {"gated_pending_signoff": True, "ratification_pending": True}
    assert RuleFindingPublic.from_model(fuzzy_ai).ratification_pending is True

    exact_bookend = _finding("ID-4", EvaluationOutcome.OPEN)
    exact_bookend.details = {"gated_pending_signoff": True, "ratification_pending": False}
    assert RuleFindingPublic.from_model(exact_bookend).ratification_pending is False


# --------------------------------------------------------------------------- #
# BUG 3 — the category is the rule's OWN family (from the spec), not the legacy enum
# --------------------------------------------------------------------------- #
def test_category_comes_from_the_rule_spec_not_the_legacy_enum() -> None:
    cases = {
        "ID-8": "Identity",  # was "Assets"
        "IN-2": "Income",  # was "Assets"
        "OC-2": "Occupancy",  # was "Property"
        "ID-4": "Identity",
        "AS-1": "Assets",
    }
    for rule_id, expected in cases.items():
        pub = RuleFindingPublic.from_model(_finding(rule_id, EvaluationOutcome.NEEDS_REVIEW))
        assert pub.category == expected, f"{rule_id} → {pub.category!r}, expected {expected!r}"
