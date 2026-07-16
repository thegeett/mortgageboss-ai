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
# abstention), so its unknown-rate is informational - never flagged. The ID family's AI tags (LP-323-
# ID-C) all abstain to "unknown" (name/address = "could not read"; residency/POA = "cannot judge"),
# so they are registered here — else over_abstaining would be silently inert for the whole ID family.
# The income family's AI tags (LP-323-IN-C) likewise abstain to "unknown" (a structuring output that
# couldn't read the figure / a judgment that couldn't decide), so they are registered here too.
_ABSTAINING_DIMENSIONS = {
    "txn.is_money_in",
    "txn.has_identified_source",
    "id.name_normalized",
    "id.address_normalized",
    "id.current_address_type",
    "id.residency_eligible",
    "id.poa_acceptable",
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
    # The assets family's AI tags (LP-323-AS-C) abstain to "unknown" too (a statement-owner match that
    # couldn't be read; a liquidation-terms / reserve-eligibility / usable-value structuring that
    # couldn't decide; a borrowed-funds judgment that couldn't decide), so they are registered here — else
    # over_abstaining would be silently inert for the AS family. txn.apparent_category stays UNregistered
    # (its "unknown" is a legitimate value, per the note above); txn.counterparty is free-text (FINDING-2:
    # not string-scorable) so it is not calibrated here at all.
    "stmt.owner_matches_borrower",
    "stmt.is_reserve_eligible",
    "asset.liquidation_terms",
    "asset.usable_value",
    "as.borrowed_funds",
}
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
