"""LP-393-4 — the clear-cut/ambiguous split of a scenario tag's scored labels (keyless; the live accuracy
numbers are non-deterministic and reported in docs/tickets/LP-393-4.md, not asserted here).

These pin the MECHANISM: the join is by (tag_id, subject_id) — an unjoinable label is reported upstream, never
guessed (LP-390-5's score_snapshot_against_golden); clear-cut cells (a (scenario, tag) with a known expected
answer) are kept SEPARATE from ambiguous ones (Priya's label IS the definition — a disagreement is a finding,
not a failure); and Priya's `unknown` is a VALID label (both-unknown counts as agreement), not a skip.
"""

from __future__ import annotations

from app.verification.eval.income_scenario_scoring import (
    scenario_of,
    split_scored,
)
from app.verification.eval.live_calibration import ScoredTag

_B3 = "93000000-0000-4000-8000-000000000003"
_B9 = "93000000-0000-4000-8000-000000000009"
_ASSET = "inc-asset-4"
_CLEARCUT = {3: {"income.is_declining": "yes"}, 4: {"income.is_declining": "no"}}


def _s(doc: str, tag: str, golden: str, predicted: str, reasoning: str = "r") -> ScoredTag:
    return ScoredTag(doc, tag, golden, predicted, 0.9, reasoning)


def test_scenario_of_parses_borrower_ids_and_none_for_assets() -> None:
    assert scenario_of(_B3) == 3 and scenario_of(_B9) == 9
    assert scenario_of(_ASSET) is None  # an asset document is not a borrower scenario
    assert scenario_of("11111111-1111-4111-8111-111111111111") is None  # a non-scenario id


def test_clearcut_and_ambiguous_are_split_and_scored_separately() -> None:
    scored = [
        _s(_B3, "income.is_declining", "yes", "yes"),  # clear-cut, agrees
        _s(_B9, "income.is_declining", "no", "yes"),  # ambiguous, DISAGREES (a finding)
    ]
    (ts,) = split_scored(scored, _CLEARCUT).values()
    assert len(ts.clearcut) == 1 and len(ts.ambiguous) == 1  # kept apart
    (cc,) = ts.clearcut
    assert cc.scenario == 3 and cc.expected == "yes" and cc.is_clearcut and cc.ai_agrees_priya
    (amb,) = ts.ambiguous
    assert amb.scenario == 9 and amb.expected is None and not amb.is_clearcut
    assert not amb.ai_agrees_priya  # AI=yes vs Priya=no — the divergence IS the measurement
    assert ts.disagreements() == (amb,)


def test_priya_unknown_is_a_valid_label_not_a_skip() -> None:
    scored = [
        _s(_B9, "income.is_declining", "unknown", "unknown"),  # both abstain → AGREE (a valid read)
        _s(
            _B3, "income.is_declining", "unknown", "yes"
        ),  # Priya unknown, AI concrete → disagree, but COUNTED
    ]
    (ts,) = split_scored(scored, _CLEARCUT).values()
    assert ts.n == 2  # her `unknown` cells are counted, not dropped
    both_unknown = next(
        c for c in ts.cells if c.priya_value == "unknown" and c.ai_value == "unknown"
    )
    assert both_unknown.priya_unknown and both_unknown.ai_agrees_priya  # both-unknown is agreement
    assert ts.agreement_rate(ts.cells) == 0.5


def test_asset_cells_are_ambiguous_no_scenario() -> None:
    scored = [_s(_ASSET, "asset.liquidation_terms", "fully_liquid", "vested_usable")]
    (ts,) = split_scored(scored, _CLEARCUT).values()
    (cell,) = ts.cells
    assert cell.scenario is None and not cell.is_clearcut  # an asset has no clear-cut expectation
    assert not cell.ai_agrees_priya  # the retirement-discount divergence (a finding)
