"""LP-524 — a "couldn't check" finding must say what it means and what to do.

TWO DEFECTS, both on the path that produces the LARGEST share of a processor's queue. On the first real
file, 15 of 25 attention items were `couldnt_check`, and every one of them:

* threw away a better sentence it already had. IH-1's recipe writes "the binder does not state a
  dwelling loss-settlement basis"; the gate replaced it with "the dwelling loss-settlement basis could
  not be read from the documents (it is present but unclear)" — which says nothing, and worse implies a
  READING failure when the fact simply is not in the document; and
* carried no `how_to_fix` at all, because `how_to_fix` lives on an OUTCOME and the gate short-circuits
  before any outcome runs. LP-522 gave judgment verdicts a fix; this path had none either way.

⚠️ THIS IS THE TEMPLATE FLOOR, not the finished text. It cannot yet mention the document's own facts —
IH-1 still cannot say "Coverage A of $577,000" or name the HQ-220 endorsement, because a rule sees only
its tags. That is the next layer; this is what sits underneath it and what a failed or rejected
composition falls back to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.gate import GateStatus, evaluate_gate
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

_AUTHORED = "the binder does not state a dwelling loss-settlement basis"


def _tag(value: str, *, produced_by: TagProducedBy, reasoning: str | None) -> Tag:
    return Tag(
        value=value,
        confidence=None if produced_by is not TagProducedBy.AI else 0.9,
        reasoning=reasoning,
        source_facts=("doc",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _gate(tag: Tag | None) -> tuple[GateStatus, str]:
    result = evaluate_gate({"ins.dwelling_settlement_basis": tag}, confidence_floor=0.5)
    return result.status, result.reason or ""


# --------------------------------------------------------------------------------------------- #
# THE MESSAGE — the gate stops discarding a written explanation
# --------------------------------------------------------------------------------------------- #
def test_a_derived_recipes_sentence_becomes_the_message() -> None:
    """The headline. A recipe that abstains has already written WHY, specifically and carefully; the
    gate used to replace it with a generic sentence that told a processor nothing."""
    status, reason = _gate(_tag("unknown", produced_by=TagProducedBy.DERIVED, reasoning=_AUTHORED))

    assert status is GateStatus.COULDNT_CHECK
    assert reason == _AUTHORED
    assert "present but unclear" not in reason


def test_an_ai_tags_prose_is_NOT_promoted_to_the_message() -> None:
    """⚠️ THE LINE THIS DRAWS. A derived tag's reasoning is authored code — reviewed, stable, written
    for this purpose. An AI tag's is model prose of unpredictable length written for a different
    audience: on AS-12 it ran ~400 words and buried the one fact that mattered. Those keep the generic
    wording until a composer layer can summarise them."""
    verbose = "The deposit description explicitly claims " + ("x " * 80)
    _status, reason = _gate(_tag("unknown", produced_by=TagProducedBy.AI, reasoning=verbose))

    assert reason.startswith("the ")
    assert "present but unclear" in reason
    assert "explicitly claims" not in reason


@pytest.mark.parametrize("label", ["parsed", "fixture-labeled", "n/a", ""])
def test_a_label_is_not_a_sentence_and_never_becomes_the_message(label: str) -> None:
    """⚠️ THE BUG THE EXISTING TESTS CAUGHT. A first version promoted ANY non-AI reasoning, and the
    suite's own fixtures carry things like "parsed" — which would have reached a processor's screen as
    the entire explanation. Worse than the generic sentence it replaced."""
    _status, reason = _gate(_tag("unknown", produced_by=TagProducedBy.DERIVED, reasoning=label))

    assert "present but unclear" in reason


def test_an_absent_tag_keeps_its_own_distinct_message() -> None:
    """§8: absent ≠ unknown. A tag never produced is a different problem from one that abstained, and
    the two must not converge just because both block."""
    _status, absent = _gate(None)
    _status2, unknown = _gate(
        _tag("unknown", produced_by=TagProducedBy.DERIVED, reasoning=_AUTHORED)
    )

    assert "could not be found in the file" in absent
    assert absent != unknown


# --------------------------------------------------------------------------------------------- #
# THE FIX — the gate path can finally carry one
# --------------------------------------------------------------------------------------------- #
def _ih1_finding(reasoning: str = _AUTHORED):
    tag = _tag("unknown", produced_by=TagProducedBy.DERIVED, reasoning=reasoning)
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        documents=DocumentsSection.present(
            [DocumentEntry(content_id="hoi", document_type="homeowners_insurance")]
        ),
        tags=TagsSection.present({"hoi": {"ins.dwelling_settlement_basis": tag}}),
    )
    [result] = evaluate_deterministic_rule(load_rule_spec("IH-1"), snapshot)
    return result


def test_a_couldnt_check_finding_now_says_what_would_resolve_it() -> None:
    """⚠️ THE HEADLINE DEFECT. `how_to_fix` lives on an OUTCOME and the gate short-circuits before any
    outcome runs, so NO couldn't-check finding could carry one — 15 of 25 items on the real file."""
    result = _ih1_finding()

    assert result.verdict is Verdict.COULDNT_CHECK
    assert result.how_to_fix is not None
    assert "declarations page" in result.how_to_fix


def test_ih1_explains_that_a_personal_property_basis_is_not_the_dwelling_one() -> None:
    """The actual confusion on the real file: both binders state "Personal Property Replacement Cost
    Loss Settlement" (HQ-290) and nothing for the dwelling. A processor reading "no basis" while
    looking at the words "Replacement Cost" needs to be told those are different coverages — otherwise
    the finding reads as the system failing to see what is plainly there."""
    fix = _ih1_finding().how_to_fix or ""

    assert "personal property" in fix.lower()
    assert "Coverage C" in fix


def test_a_rule_that_declares_no_fix_still_carries_none() -> None:
    """ADDITIVE. Every other rule keeps its current behaviour until its own wording is written."""
    spec = load_rule_spec("AS-7")
    assert spec.deterministic is not None
    assert spec.deterministic.couldnt_check_fix is None
