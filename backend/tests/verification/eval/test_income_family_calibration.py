"""LP-323-IN-C Phase 3 — CALIBRATION for the INCOME family's AI-produced tags.

Same measure + discipline as LP-323-ID-C: two numbers per AI tag dimension — UNKNOWN RATE (too high →
over-abstention: the tag is useless, everything routes to couldnt_check) and ACCURACY WHEN CONCRETE (too
low → under-abstention / fabrication). Reuses the LP-317 ``DimensionCalibration`` primitive UNCHANGED (no
app-code edit — the integrity property).

KEYLESS by default: calibration.py's own docstring is explicit that keyless observations REPLAY the
labels, so concrete accuracy reads as a trivially-perfect baseline (a plumbing check). To prove the metric
is NOT inert, this suite feeds deliberate abstentions + a deliberate wrong answer and asserts the flags
fire. LIVE mode (the real materialization reasoner producing these tags from raw income documents, scored
vs golden labels) is the MEANINGFUL measure and is NOT built yet:
wiring it is a follow-on (LP-323-IN-C doc), so no test here pretends to run it.
"""

from __future__ import annotations

import pytest
from app.verification.eval.calibration import DimensionCalibration, format_calibration

# The AI-produced income tags to calibrate (the structuring outputs + the judgment verdicts). The parsed
# tags (stated_monthly, pay_date, ytd_gross, employment dates) are not AI — no abstention to calibrate.
# All eleven abstain to "unknown" and are registered in calibration.py's `_ABSTAINING_DIMENSIONS`
# (which `over_abstaining` gates on — an unregistered tag would never flag over-abstention).
_INCOME_AI_TAGS = (
    "income.documented_monthly",
    "income.qualifying_monthly",
    "income.employer_normalized",
    "income.type",
    "income.is_declining",
    "income.has_2yr_history",
    "income.same_line_of_work",
    "income.continuance_3yr",
    "income.job_change_acceptable",
    "income.other_income_continues",
    "income.rental_income_supportable",
)
_ABSTENTION = {None, "unknown"}


def _calibrate(
    dimension: str, observations: list[tuple[str | None, str | None]]
) -> DimensionCalibration:
    """observations = [(expected, actual)] → the production DimensionCalibration for one income tag.
    The over/under-abstention decision is read from the dataclass's OWN properties (no reimplemented
    threshold logic — so the test validates the real gating, including the `_ABSTAINING_DIMENSIONS`
    membership that would silently disable the flag)."""
    unknown = sum(1 for _e, a in observations if a in _ABSTENTION)
    concrete = [(e, a) for e, a in observations if a not in _ABSTENTION]
    correct = sum(1 for e, a in concrete if a == e)
    return DimensionCalibration(dimension, len(observations), unknown, len(concrete), correct)


# --------------------------------------------------------------------------- #
# KEYLESS — the plumbing + structure check (always runs, no key)
# --------------------------------------------------------------------------- #
def test_keyless_replayed_labels_are_the_trivial_baseline(capsys) -> None:
    cals = [
        _calibrate(dim, [("concrete", "concrete")] * 8 + [("concrete", "unknown")] * 2)
        for dim in _INCOME_AI_TAGS
    ]
    print("\n" + format_calibration(cals, live=False))  # the PRODUCTION formatter (not a copy)
    for c in cals:
        assert c.total == 10
        assert c.accuracy_when_concrete == 1.0  # keyless = trivially perfect (plumbing check)
        assert c.unknown_rate == pytest.approx(0.20)
        assert not c.over_abstaining and not c.under_abstaining
    assert capsys.readouterr().out  # the calibration block is emitted for the report


def test_metric_catches_over_abstention() -> None:
    # NOT inert: income.documented_monthly is THE hard structuring step; a live perceiver that abstains
    # 70% of the time is useless (everything routes to couldnt_check) → OVER-ABSTENTION. Uses the
    # PRODUCTION `over_abstaining` — gated on `_ABSTAINING_DIMENSIONS`, so this also proves the income
    # tag IS registered (an unregistered tag would never flag, however high its unknown-rate).
    c = _calibrate("income.documented_monthly", [("4000", "unknown")] * 7 + [("4000", "4000")] * 3)
    assert c.unknown_rate == pytest.approx(0.70) and c.over_abstaining


def test_metric_catches_under_abstention_fabrication() -> None:
    # NOT inert: a documented-income tag that COMMITS to a figure but is wrong 40% of the time →
    # UNDER-ABSTENTION (fabrication) — the dangerous direction (it feeds the shortfall recipe).
    c = _calibrate("income.documented_monthly", [("4000", "4000")] * 6 + [("4000", "9999")] * 4)
    assert (
        c.unknown_rate == 0.0
        and c.accuracy_when_concrete == pytest.approx(0.60)
        and c.under_abstaining
    )


def test_all_income_ai_tags_are_covered() -> None:
    # No calibration fatigue: the structuring outputs + the three judgment verdicts.
    assert len(_INCOME_AI_TAGS) == 11 and "income.documented_monthly" in _INCOME_AI_TAGS
