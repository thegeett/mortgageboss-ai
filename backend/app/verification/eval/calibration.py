"""Calibration metrics (LP-317 Phase 3) - measure abstention, don't assume it.

Two numbers per tag dimension, aggregated over the eval set:

* UNKNOWN RATE - how often a tag abstains (``unknown`` / absent). Too HIGH → over-abstention: the
  tag is useless (everything routes to couldnt_check). Too LOW paired with poor concrete accuracy →
  under-abstention: the model fabricates a concrete value instead of admitting it cannot tell.
* ACCURACY WHEN CONCRETE - when the tag commits to a concrete value (in/out, yes/no,
  verified/self_asserted/none), how often it matches the golden label. This is where fabrication
  shows up: a confident wrong answer is worse than an honest unknown.

These are only meaningful in LIVE mode (the real model can abstain or be wrong); keyless observations
replay the labels, so they read as a trivially perfect baseline (useful as a plumbing check).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.verification.eval.harness import CaseResult, TagObservation

# The abstention value for the tags that have one. source_strength / apparent_category do not
# abstain to "unknown" the same way, so their unknown-rate is reported as informational only.
_ABSTENTION = {None, "unknown"}
# Dimensions where "unknown" is a genuine ABSTENTION (→ couldnt_check downstream), so a high rate is
# over-abstention. For apparent_category, "unknown" is a legitimate value (not a fraud-relevant
# abstention), so its unknown-rate is informational - never flagged.
_ABSTAINING_DIMENSIONS = {"txn.is_money_in", "txn.has_identified_source"}
_OVER_ABSTENTION = 0.30  # above this unknown-rate, an abstaining tag is drowning in unknowns
_UNDER_ABSTENTION_ACCURACY = 0.90  # concrete accuracy below this = fabrication risk


@dataclass(frozen=True)
class DimensionCalibration:
    """Calibration for one tag dimension over the eval set."""

    dimension: str
    total: int
    unknown: int
    concrete: int
    concrete_correct: int

    @property
    def unknown_rate(self) -> float:
        return self.unknown / self.total if self.total else 0.0

    @property
    def accuracy_when_concrete(self) -> float:
        return self.concrete_correct / self.concrete if self.concrete else 0.0

    @property
    def over_abstaining(self) -> bool:
        # Only meaningful where "unknown" is a true abstention (not a legitimate category value).
        return self.dimension in _ABSTAINING_DIMENSIONS and self.unknown_rate > _OVER_ABSTENTION

    @property
    def under_abstaining(self) -> bool:
        # Committing confidently but wrong often - the dangerous direction for a fraud check.
        return self.concrete > 0 and self.accuracy_when_concrete < _UNDER_ABSTENTION_ACCURACY


def _observations(results: list[CaseResult]) -> list[TagObservation]:
    return [o for r in results for o in r.observations]


def summarize(results: list[CaseResult]) -> list[DimensionCalibration]:
    """Aggregate per-dimension calibration across every scored observation."""
    by_dim: dict[str, list[TagObservation]] = {}
    for observation in _observations(results):
        by_dim.setdefault(observation.dimension, []).append(observation)

    summaries: list[DimensionCalibration] = []
    for dimension, group in sorted(by_dim.items()):
        unknown = sum(1 for o in group if o.actual in _ABSTENTION)
        concrete = [o for o in group if o.actual not in _ABSTENTION]
        correct = sum(1 for o in concrete if o.actual == o.expected)
        summaries.append(
            DimensionCalibration(dimension, len(group), unknown, len(concrete), correct)
        )
    return summaries


def format_calibration(summaries: list[DimensionCalibration], *, live: bool) -> str:
    """A calibration summary block for the GO/NO-GO report."""
    mode = "LIVE MODEL" if live else "KEYLESS (stubbed - trivially perfect; plumbing check only)"
    lines = ["-" * 78, f"CALIBRATION - {mode}", "-" * 78]
    lines.append(f"{'dimension':<28} {'n':>4} {'unknown%':>9} {'acc-concrete%':>14}  flags")
    for s in summaries:
        flags = []
        if s.over_abstaining:
            flags.append("OVER-ABSTENTION")
        if s.under_abstaining:
            flags.append("UNDER-ABSTENTION/fabrication")
        lines.append(
            f"{s.dimension:<28} {s.total:>4} {s.unknown_rate * 100:>8.1f}% "
            f"{s.accuracy_when_concrete * 100:>13.1f}%  {', '.join(flags) or 'ok'}"
        )
    return "\n".join(lines)
