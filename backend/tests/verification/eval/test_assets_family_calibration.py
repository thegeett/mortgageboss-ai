"""LP-323-AS-C Phase 3 — CALIBRATION for the ASSETS family's AI-produced tags.

Same measure + discipline as ID-C / IN-C: two numbers per AI tag dimension — UNKNOWN RATE (too high →
over-abstention: everything routes to couldnt_check) and ACCURACY WHEN CONCRETE (too low → under-
abstention / fabrication). Reuses the LP-317 ``DimensionCalibration`` primitive UNCHANGED.

**FINDING-2 (from LP-334) is LOAD-BEARING here.** The assets structuring produces a FREE-TEXT tag,
`txn.counterparty` (e.g. "Chase Wire Dept" vs "chase wire"), which string equality cannot score — it is
DEFERRED from calibration (a fuzzy-match scorer is a follow-on), NOT scored and silently mismarked. The
ENUM/number AI tags below ARE string-scorable and are calibrated. `txn.apparent_category` is excluded
deliberately (calibration.py: its "unknown" is a legitimate value, not a fraud-relevant abstention).

KEYLESS by default (labels replayed → trivially-perfect baseline, a plumbing check). To prove the metric
is NOT inert, deliberate abstentions + a deliberate wrong answer make the flags fire — and, since
``over_abstaining`` gates on ``_ABSTAINING_DIMENSIONS`` membership, that also proves each AS tag IS
registered. LIVE mode (the real materialization reasoner over raw statements/gift-letters/retirement docs,
scored vs golden) is the meaningful measure and is SKIPPED without a key (never fabricated).
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import pytest
from app.verification.eval.calibration import DimensionCalibration, format_calibration

# The string-SCORABLE AI-produced assets tags (the structuring enums/number + the judgment verdict). All
# abstain to "unknown" and are registered in calibration.py's `_ABSTAINING_DIMENSIONS`.
_ASSETS_AI_TAGS = (
    "stmt.owner_matches_borrower",
    "stmt.is_reserve_eligible",
    "asset.liquidation_terms",
    "asset.usable_value",
    "as.borrowed_funds",
)
# DEFERRED — free-text, not string-scorable (FINDING-2). Named to make the deferral explicit, not silent.
_DEFERRED_FREE_TEXT_TAGS = ("txn.counterparty",)
_ABSTENTION = {None, "unknown"}


def _calibrate(
    dimension: str, observations: Sequence[tuple[str | None, str | None]]
) -> DimensionCalibration:
    """observations = [(expected, actual)] → the production DimensionCalibration for one assets tag. The
    over/under-abstention decision is read from the dataclass's OWN properties (no reimplemented threshold
    logic — so the test validates the real gating, including `_ABSTAINING_DIMENSIONS` membership)."""
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
        for dim in _ASSETS_AI_TAGS
    ]
    print("\n" + format_calibration(cals, live=False))  # the PRODUCTION formatter (not a copy)
    for c in cals:
        assert c.total == 10
        assert c.accuracy_when_concrete == 1.0  # keyless = trivially perfect (plumbing check)
        assert c.unknown_rate == pytest.approx(0.20)
        assert not c.over_abstaining and not c.under_abstaining
    assert capsys.readouterr().out  # the calibration block is emitted for the report


def test_metric_catches_over_abstention_and_proves_registration() -> None:
    # NOT inert: stmt.owner_matches_borrower is what AS-6 fires on; a live perceiver that abstains 70% of
    # the time is useless (everything → couldnt_check) → OVER-ABSTENTION. Uses the PRODUCTION
    # `over_abstaining`, gated on `_ABSTAINING_DIMENSIONS` — so a pass ALSO proves this AS tag is registered
    # (an unregistered tag would never flag, however high its unknown-rate).
    for dim in _ASSETS_AI_TAGS:
        c = _calibrate(dim, [("no", "unknown")] * 7 + [("no", "no")] * 3)
        assert c.unknown_rate == pytest.approx(0.70) and c.over_abstaining, f"{dim} not registered"


def test_metric_catches_under_abstention_fabrication() -> None:
    # NOT inert: a usable-value tag that COMMITS to a number but is wrong 40% of the time →
    # UNDER-ABSTENTION (fabrication) — the dangerous direction (it feeds the reserves calc that AS-4 reads).
    c = _calibrate("asset.usable_value", [("20000", "20000")] * 6 + [("20000", "99999")] * 4)
    assert (
        c.unknown_rate == 0.0
        and c.accuracy_when_concrete == pytest.approx(0.60)
        and c.under_abstaining
    )


def test_free_text_counterparty_is_deferred_not_silently_mis_scored() -> None:
    # FINDING-2 made concrete: "Chase Wire Dept" and "chase wire" are the SAME counterparty but string
    # equality scores them WRONG — so txn.counterparty is DEFERRED (named in _DEFERRED_FREE_TEXT_TAGS),
    # not fed to the string scorer where it would fabricate an under-abstention flag. Documented, not hidden.
    assert _DEFERRED_FREE_TEXT_TAGS == ("txn.counterparty",)
    assert "txn.counterparty" not in _ASSETS_AI_TAGS
    misleading = _calibrate("txn.counterparty", [("Chase Wire Dept", "chase wire")] * 10)
    assert (
        misleading.accuracy_when_concrete == 0.0
    )  # the artifact we REFUSE to report as a real signal


def test_all_assets_ai_tags_are_covered() -> None:
    # No calibration fatigue: the four structuring outputs + the one judgment verdict, minus the deferred
    # free-text tag (accounted for explicitly, not dropped).
    assert len(_ASSETS_AI_TAGS) == 5 and "as.borrowed_funds" in _ASSETS_AI_TAGS
    assert set(_ASSETS_AI_TAGS).isdisjoint(_DEFERRED_FREE_TEXT_TAGS)


# --------------------------------------------------------------------------- #
# LIVE — the meaningful measure (skipped without a key; never fabricated)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="live calibration needs an API key")
def test_live_calibration_placeholder() -> None:
    # LIVE calibration runs the REAL materialization reasoners (stmt_facts / asset_facts / the AS-12
    # judgment) over raw statement / gift-letter / retirement-account content and scores each produced
    # ENUM/number tag vs a golden label — the only measure that can detect a live model's over/under-
    # abstention. Wiring the assets reasoners into a scored live harness (and a fuzzy scorer for the
    # deferred free-text counterparty) is its own follow-on seam (see the LP-323-AS-C doc). Keyless above runs.
    pytest.skip(
        "live assets-tag calibration harness is a documented follow-on seam (LP-323-AS-C doc)"
    )
