"""LP-393-4 — split a scenario tag's scored labels into CLEAR-CUT vs AMBIGUOUS, which MEAN different things.

A clear-cut cell (B3-B8's primary tag, in ``CLEARCUT_EXPECTATIONS``) has a known expected answer: an AI/Priya
disagreement there is a BUG signal (an obvious 25% drop must read `declining`). An ambiguous cell (B9-B15, and
the asset docs) has NO prior right answer — Priya's label IS the definition, so a disagreement is THE
MEASUREMENT (the AI's implicit definition differs from underwriting practice), not a failure. A single blended
accuracy would hide both, so this keeps them apart.

This is the MECHANISM only (keyless, deterministic): it joins Priya's goldens to the AI's predictions by the
stable ``(tag_id, subject_id)`` key (via LP-390-5's ``score_snapshot_against_golden``, upstream) and classifies
each scored cell. Priya's ``unknown`` is a VALID label (she could not tell), never a skip. The live accuracy
numbers are non-deterministic (real model) and live in docs/tickets/LP-393-4.md, not asserted here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.verification.eval.live_calibration import ScoredTag


@dataclass(frozen=True)
class ScenarioCell:
    """One scored (tag, subject) cell: the AI's value + reasoning vs Priya's label, plus the clear-cut
    expectation when this cell is a clear-cut one (else None → ambiguous, her label is the definition)."""

    tag_id: str
    subject_id: str
    scenario: int | None  # B{n} for a borrower scenario; None for an asset document
    ai_value: str
    priya_value: str
    ai_reasoning: str | None
    expected: str | None  # set only for a clear-cut cell (B3-B8 primary tag)

    @property
    def is_clearcut(self) -> bool:
        return self.expected is not None

    @property
    def ai_agrees_priya(self) -> bool:
        return self.ai_value == self.priya_value

    @property
    def priya_unknown(self) -> bool:
        return self.priya_value == "unknown"


@dataclass(frozen=True)
class TagScore:
    """One tag's cells split by clear-cut vs ambiguous — scored SEPARATELY (they mean different things)."""

    tag_id: str
    cells: tuple[ScenarioCell, ...]

    @property
    def clearcut(self) -> tuple[ScenarioCell, ...]:
        return tuple(c for c in self.cells if c.is_clearcut)

    @property
    def ambiguous(self) -> tuple[ScenarioCell, ...]:
        return tuple(c for c in self.cells if not c.is_clearcut)

    @property
    def n(self) -> int:
        return len(self.cells)

    def agreement_rate(self, cells: Sequence[ScenarioCell]) -> float | None:
        """AI==Priya agreement over the given cell subset (None when empty). Both-`unknown` counts as
        agreement — Priya's `unknown` is a valid label, so the AI matching it is a correct read, not a miss."""
        return sum(c.ai_agrees_priya for c in cells) / len(cells) if cells else None

    def disagreements(self) -> tuple[ScenarioCell, ...]:
        return tuple(c for c in self.cells if not c.ai_agrees_priya)


def scenario_of(subject_id: str) -> int | None:
    """The scenario number B{n} a subject belongs to — parsed from the LP-393-1 borrower id namespace
    (``93000000-…-0000000000{nn}``); an asset document (``inc-asset-…``) has no scenario → None."""
    if subject_id.startswith("93000000-") and subject_id[-2:].isdigit():
        return int(subject_id[-2:])
    return None


def split_scored(
    scored: Sequence[ScoredTag],
    clearcut_expectations: Mapping[int, Mapping[str, str]],
) -> dict[str, TagScore]:
    """Classify each scored cell into clear-cut (its (scenario, tag) has an expected answer) vs ambiguous, and
    group by tag. ``scored`` comes from ``score_snapshot_against_golden`` (the join by (tag_id, subject_id) —
    an unjoinable label is already reported there as `unmatched`, never dropped here)."""
    by_tag: dict[str, list[ScenarioCell]] = {}
    for s in scored:
        n = scenario_of(s.doc_id)
        expected = None
        if n is not None and n in clearcut_expectations:
            expected = clearcut_expectations[n].get(s.tag_id)
        cell = ScenarioCell(
            tag_id=s.tag_id,
            subject_id=s.doc_id,
            scenario=n,
            ai_value=str(s.predicted),
            priya_value=str(s.golden),
            ai_reasoning=s.reasoning,
            expected=expected,
        )
        by_tag.setdefault(s.tag_id, []).append(cell)
    return {tag: TagScore(tag, tuple(cells)) for tag, cells in by_tag.items()}


__all__ = ["ScenarioCell", "TagScore", "scenario_of", "split_scored"]
