"""LP-524 — every rule that abstains on LF-WCHG now says what would resolve it.

Fifteen of the file's twenty-five attention items are `couldnt_check`, spread across eleven rules. Each
named a missing fact and stopped there, so a processor was told what the engine lacked and never what
to go and get.

⚠️ THE WORDING IS STATIC PER RULE, and that constrains it. The gate short-circuits at the FIRST missing
gated input, and `couldnt_check_fix` cannot see which one that was — so a fix has to hold whichever
input was absent. IH-3 gates on an insurance effective date AND a closing date; its text therefore
covers both without asserting which is the problem. Text that assumed one would be confidently wrong
half the time, which is worse than the vague message it replaced.
"""

from __future__ import annotations

import pytest
from app.verification.rules.specs import load_rule_spec

# Every rule that produced a `couldnt_check` on LF-WCHG's run, with the count it produced.
_ABSTAINING = {
    "CL-1": 1,
    "CR-13": 1,
    "CR-6": 4,
    "ID-7": 1,
    "IH-1": 2,
    "IH-3": 1,
    "IH-9": 1,
    "IN-3": 1,
    "IN-4": 1,
    "IN-8": 1,
    "PR-6": 1,
}


def _fix(rule_id: str) -> str:
    spec = load_rule_spec(rule_id)
    assert spec.deterministic is not None, f"{rule_id} is not a deterministic rule"
    fix = spec.deterministic.couldnt_check_fix
    assert fix is not None, f"{rule_id} has no couldnt_check_fix"
    return fix


def test_the_fifteen_abstentions_are_covered() -> None:
    """The count is the point: this is 15 of the 25 items in the queue, the single largest slice."""
    assert sum(_ABSTAINING.values()) == 15
    for rule_id in _ABSTAINING:
        assert _fix(rule_id)


@pytest.mark.parametrize("rule_id", sorted(_ABSTAINING))
def test_every_fix_asks_for_something(rule_id: str) -> None:
    """⚠️ A fix that describes the problem again is not a fix. Each must open with an instruction — the
    defect being removed is precisely a finding that states a gap and asks for nothing."""
    fix = _fix(rule_id)

    assert any(
        verb in fix for verb in ("Upload", "Obtain", "Confirm", "upload", "obtain", "confirm")
    ), f"{rule_id} never asks for anything: {fix[:80]!r}"
    assert len(fix) > 80, f"{rule_id}'s fix is a stub"


@pytest.mark.parametrize("rule_id", sorted(_ABSTAINING))
def test_every_fix_names_a_document(rule_id: str) -> None:
    """ "Obtain documentation" sends nobody anywhere. Each fix names the actual artefact — a credit
    report, a title commitment, a VOE, a Closing Disclosure — because the processor's next action is to
    request one specific thing from one specific party."""
    documents = (
        "credit report",
        "title commitment",
        "Closing Disclosure",
        "declarations page",
        "appraisal",
        "pay stub",
        "verification of employment",
        "rate-lock confirmation",
        "coverage form",
        "settlement statement",
        "W-2",
    )
    fix = _fix(rule_id)

    assert any(d in fix for d in documents), f"{rule_id} names no document: {fix[:100]!r}"


def test_cr6_refuses_to_read_a_missing_report_as_a_clean_history() -> None:
    """⚠️ THE ONE THAT MATTERS MOST HERE. LF-WCHG has NO credit report, and the model's own reasoning on
    that run said `liab.derogatory_type = none` was "based on absence of information rather than
    confirmation of clean status". A processor reading four CR-6 abstentions could reasonably assume
    the borrower simply has no derogatory events; the fix says explicitly that the check will not make
    that assumption, so the abstention is not mistaken for a pass.

    Asserted as a PROPERTY, not a phrase: LP-530 reworded this fix out of the engine's voice ("this check
    will not assume") into the processor's, and a test that pins wording blocks a wording fix while
    proving nothing about meaning."""
    fix = _fix("CR-6")

    assert "absence is not evidence" in fix
    assert "clean history" in fix


def test_ih3_covers_both_of_its_gated_inputs() -> None:
    """The static-wording constraint, asserted. IH-3 gates on an insurance effective date AND a closing
    date; the gate reports whichever is missing first and the fix cannot know which. Naming only one
    would be wrong half the time."""
    fix = _fix("IH-3")

    assert "closing date" in fix
    assert "policy" in fix


def test_ih1_is_the_only_one_interpolating_document_facts() -> None:
    """LP-525's channel is deliberately narrow. IH-1 needed it because a processor looking at a binder
    that plainly says "Replacement Cost" cannot otherwise see why that is not an answer. The other ten
    are missing-document cases, where naming the document IS the whole answer and no quoted fact would
    add to it."""
    with_facts = {
        rule_id
        for rule_id in _ABSTAINING
        if (spec := load_rule_spec(rule_id)).deterministic is not None
        and spec.deterministic.subject_facts
    }

    assert with_facts == {"IH-1"}
