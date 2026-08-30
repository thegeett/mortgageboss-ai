"""The in-scope findings, split by the system that produced them (LP-UI-021).

The defect this exists for: the calculators' alert read "91 unresolved findings",
a single number spanning three generators. It reconciled with nothing a processor
could see — the verification tabs showed 75 governed and 13 legacy, and the
remaining 3 deterministic cross-source findings appeared on no screen at all. One
number over the governed engine and the legacy sweep is also LP-375's separation
collapsed into a figure.

Counted per system, never as a remainder: a labelled count derived by subtraction
cannot be wrong about its label, so nothing looks like a claim.
"""

from app.models.finding import (
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
)
from app.services.finding_blocking import FindingBreakdown, breakdown_by_system


def _finding(**kw: object) -> Finding:
    return Finding(
        rule_id=kw.pop("rule_id", "CR-1"),
        origin=kw.pop("origin", FindingOrigin.DETERMINISTIC_RULE),
        evaluation_outcome=kw.pop("evaluation_outcome", None),
        status=FindingStatus.YELLOW,
        category=FindingCategory.CREDIT,
        message="a finding",
        confidence=0.9,
        **kw,  # type: ignore[arg-type]
    )


class TestTheBreakdown:
    def test_a_governed_finding_is_the_one_carrying_an_outcome(self) -> None:
        # The governed engine is identified by `evaluation_outcome`, not by
        # origin: the deterministic cross-source rules share DETERMINISTIC_RULE
        # and carry no outcome, so origin alone would merge the two.
        counts = breakdown_by_system([_finding(evaluation_outcome=EvaluationOutcome.OPEN)])
        assert counts == FindingBreakdown(governed=1)

    def test_a_deterministic_finding_without_an_outcome_is_a_cross_check(self) -> None:
        counts = breakdown_by_system([_finding(rule_id="xsrc.income.employer_count_matches_items")])
        assert counts == FindingBreakdown(cross_source=1)

    def test_the_ai_sweep_is_counted_apart(self) -> None:
        # LP-375: never merged with the governed engine, never summed into it.
        counts = breakdown_by_system(
            [
                _finding(evaluation_outcome=EvaluationOutcome.OPEN),
                _finding(rule_id="cross_source.other", origin=FindingOrigin.AI_CROSS_SOURCE),
            ]
        )
        assert counts.governed == 1
        assert counts.legacy == 1

    def test_an_unknown_generator_gets_its_own_number(self) -> None:
        # DOCUMENT_ANALYSIS produces nothing today. The day it does, it must
        # appear rather than inflate one of the three named counts — which is
        # what any "everything else" subtraction would have done silently.
        counts = breakdown_by_system([_finding(origin=FindingOrigin.DOCUMENT_ANALYSIS)])
        assert counts == FindingBreakdown(other=1)

    def test_the_parts_account_for_every_finding(self) -> None:
        findings = [
            _finding(evaluation_outcome=EvaluationOutcome.OPEN),
            _finding(evaluation_outcome=EvaluationOutcome.COULDNT_CHECK),
            _finding(rule_id="xsrc.income.employer_name_consistency"),
            _finding(rule_id="cross_source.other", origin=FindingOrigin.AI_CROSS_SOURCE),
            _finding(origin=FindingOrigin.DOCUMENT_ANALYSIS),
        ]
        counts = breakdown_by_system(findings)
        # The alert never prints this sum — but nothing may go uncounted either,
        # which is the property that makes the named parts trustworthy.
        assert counts.total == len(findings)

    def test_nothing_in_nothing_out(self) -> None:
        assert breakdown_by_system([]) == FindingBreakdown()
