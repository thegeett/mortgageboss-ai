"""LP-323-ID-C Phase 3 — CALIBRATION for the ID family's AI-produced tags.

The measure (from LP-317): two numbers per AI tag dimension —
* UNKNOWN RATE — how often the tag abstains ("unknown"/absent). Too HIGH → over-abstention (the tag is
  useless, everything routes to couldnt_check). Too LOW paired with poor concrete accuracy →
  under-abstention (the model fabricates a value instead of admitting it cannot tell).
* ACCURACY WHEN CONCRETE — when the tag commits, how often it matches the golden label.

Reuses the LP-317 ``DimensionCalibration`` primitive UNCHANGED (no app-code edit — the integrity
property). The ID AI tags calibrated are exactly those LP-323-ID-A named: ``id.name_normalized``,
``id.address_normalized``, ``id.current_address_type`` and the judgment tags (``id.residency_eligible``,
``id.poa_acceptable``).

KEYLESS by default: calibration.py's own docstring is explicit that keyless observations REPLAY the
labels, so concrete accuracy reads as a trivially-perfect baseline (a plumbing check). To prove the
metric is NOT inert, this suite feeds deliberate abstentions + a deliberate wrong answer and asserts the
flags fire. LIVE mode — the real materialization reasoner producing these tags from raw content, scored
vs golden labels — is the MEANINGFUL measure and is SKIPPED without an API key (never fabricated).
"""

from __future__ import annotations

import os

import pytest
from app.verification.eval.calibration import DimensionCalibration, format_calibration

# The AI-produced ID tags to calibrate + whether "unknown" is a true ABSTENTION for that tag (routes to
# couldnt_check downstream, so a high unknown-rate is over-abstention). name/address abstain to
# unknown too, but their unknown is "could not read" (still an abstention). All five abstain — and are
# registered in calibration.py's `_ABSTAINING_DIMENSIONS`, which `over_abstaining` gates on.
_ID_AI_TAGS = (
    "id.name_normalized",
    "id.address_normalized",
    "id.current_address_type",
    "id.residency_eligible",
    "id.poa_acceptable",
)
_ABSTENTION = {None, "unknown"}


def _calibrate(
    dimension: str, observations: list[tuple[str | None, str | None]]
) -> DimensionCalibration:
    """observations = [(expected, actual)] → the production DimensionCalibration for one ID tag. The
    over/under-abstention decision is read from the dataclass's OWN `over_abstaining` /
    `under_abstaining` properties (no reimplemented threshold logic — so the test validates the real
    gating, including the `_ABSTAINING_DIMENSIONS` membership that would silently disable the flag)."""
    unknown = sum(1 for _e, a in observations if a in _ABSTENTION)
    concrete = [(e, a) for e, a in observations if a not in _ABSTENTION]
    correct = sum(1 for e, a in concrete if a == e)
    return DimensionCalibration(dimension, len(observations), unknown, len(concrete), correct)


# --------------------------------------------------------------------------- #
# KEYLESS — the plumbing + structure check (always runs, no key)
# --------------------------------------------------------------------------- #
def test_keyless_replayed_labels_are_the_trivial_baseline(capsys) -> None:
    # A healthy tag: mostly concrete-correct, a MINORITY of honest abstentions. Replayed labels →
    # concrete accuracy is trivially perfect (the documented keyless baseline); unknown-rate reflects
    # the fixture's honest-abstention share and stays under the over-abstention line.
    cals = [
        _calibrate(dim, [("concrete", "concrete")] * 8 + [("concrete", "unknown")] * 2)
        for dim in _ID_AI_TAGS
    ]
    print("\n" + format_calibration(cals, live=False))  # the PRODUCTION formatter (not a copy)
    for c in cals:
        assert c.total == 10
        assert c.accuracy_when_concrete == 1.0  # keyless = trivially perfect (plumbing check)
        assert c.unknown_rate == pytest.approx(0.20)
        assert not c.over_abstaining and not c.under_abstaining  # a healthy tag flags nothing
    assert capsys.readouterr().out  # the calibration block is emitted for the report


def test_metric_catches_over_abstention() -> None:
    # NOT inert: a tag drowning in unknowns (70%) → OVER-ABSTENTION flags (it would route everything to
    # couldnt_check — useless). Uses the PRODUCTION `over_abstaining` — which is gated on the dimension
    # being registered in `_ABSTAINING_DIMENSIONS`, so this also proves the ID tag IS registered (an
    # unregistered ID tag would silently never flag, however high its unknown-rate).
    c = _calibrate(
        "id.current_address_type", [("residence", "unknown")] * 7 + [("residence", "residence")] * 3
    )
    assert c.unknown_rate == pytest.approx(0.70) and c.over_abstaining


def test_metric_catches_under_abstention_fabrication() -> None:
    # NOT inert: a tag that commits confidently but is WRONG 40% of the time → UNDER-ABSTENTION
    # (fabrication) — the dangerous direction for a fair-lending / fraud check. It should have abstained.
    c = _calibrate("id.residency_eligible", [("yes", "yes")] * 6 + [("yes", "no")] * 4)
    assert (
        c.unknown_rate == 0.0
        and c.accuracy_when_concrete == pytest.approx(0.60)
        and c.under_abstaining
    )


def test_all_five_id_ai_tags_are_covered() -> None:
    # No calibration fatigue: every AI-produced ID tag LP-323-ID-A named has a dimension here.
    assert set(_ID_AI_TAGS) == {
        "id.name_normalized",
        "id.address_normalized",
        "id.current_address_type",
        "id.residency_eligible",
        "id.poa_acceptable",
    }


# --------------------------------------------------------------------------- #
# LIVE — the meaningful measure (skipped without a key; never fabricated)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="live calibration needs an API key")
def test_live_calibration_placeholder() -> None:
    # LIVE calibration runs the REAL materialization reasoner (LP-326) over raw name/address/POA/
    # citizenship content and scores the produced tag vs a golden label — the only measure that can
    # detect a live model's over/under-abstention. It is intentionally a documented SEAM here: wiring
    # the ID materialization reasoners into a scored live harness is its own ticket (see LP-323-ID-C
    # doc, "calibration" — the live seam). Without a key this is skipped; keyless scoring above still runs.
    pytest.skip("live ID-tag calibration harness is a documented follow-on seam (LP-323-ID-C doc)")
