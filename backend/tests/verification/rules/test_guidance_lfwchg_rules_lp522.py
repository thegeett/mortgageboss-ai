"""LP-522 phase 2 — guidance for the judgment rules a processor actually sees on LF-WCHG.

AS-12 proved the shape; these are the other three judgment rules that produced findings on the real
file: OC-2 (occupancy reasonableness), DT-7 (ATR documentation completeness) and CR-8 (mortgage payment
history). The remaining fourteen are untouched and keep their LP-520 wording — writing fixes for rules
nobody has looked at is how a processor gets sent for the wrong document.

Two shape lessons landed here, both from the rules themselves rather than from design:

* `explain_by` had to become OPTIONAL. `action` keys on the VERDICT and `explain` on a TAG, so a rule
  whose distinction already lives in its verdicts has no second axis: CR-8's six values say more than
  any of the four tags it reasons over would.
* Such a rule declares `default` alone, which is the honest shape there rather than a degenerate one.
"""

from __future__ import annotations

import pytest
from app.verification.rules.specs import JudgmentEval, load_rule_spec
from pydantic import ValidationError

# LP-551 — FR-5 was authored WITH guidance, so it joins the written set rather than the untouched one.
# OC-3 joined in LP-622, once its rental-support text was written against its own guideline
# citation (B3-3.8-01) and the enum its explanatory tag actually carries.
_RULES = ("AS-12", "OC-2", "DT-7", "CR-8", "FR-5", "OC-3")


@pytest.mark.parametrize("rule_id", _RULES)
def test_every_verdict_has_an_action(rule_id: str) -> None:
    """A verdict with no action leaves that finding headless — the defect this ticket removes, hiding
    on whichever answer is rarest."""
    judgment = load_rule_spec(rule_id).judgment
    assert judgment is not None and judgment.guidance is not None

    assert set(judgment.guidance.action) == set(judgment.value_domain)


@pytest.mark.parametrize("rule_id", _RULES)
def test_every_action_is_an_instruction_not_a_verdict(rule_id: str) -> None:
    """⚠️ THE WHOLE POINT. The old text opened with "the AI judged…", which states a conclusion and not
    a task. Every action must read as something a processor DOES."""
    judgment = load_rule_spec(rule_id).judgment
    assert judgment is not None and judgment.guidance is not None

    for verdict, action in judgment.guidance.action.items():
        assert "the AI judged" not in action, f"{rule_id}/{verdict}"
        assert action[0].isupper(), (
            f"{rule_id}/{verdict} should open with an imperative: {action!r}"
        )
        assert action.rstrip().endswith("."), f"{rule_id}/{verdict} should be a sentence"


@pytest.mark.parametrize("rule_id", _RULES)
def test_every_case_carries_both_a_why_and_a_fix(rule_id: str) -> None:
    judgment = load_rule_spec(rule_id).judgment
    assert judgment is not None and judgment.guidance is not None

    for name, case in judgment.guidance.explain.items():
        assert case.why.strip(), f"{rule_id}/{name}"
        assert case.how_to_fix.strip(), f"{rule_id}/{name}"


def test_cr8_keys_its_distinction_on_the_verdict_not_on_a_tag() -> None:
    """⚠️ THE CASE THAT MADE `explain_by` OPTIONAL — and NOT for want of tags. CR-8 reasons over four.
    Its evidence axis IS the verdict: six values naming the exact distinction (`one_30_day_late`,
    `excessive_60_plus`, `not_interpretable`, …), where `liab.payment_status` would be a weaker proxy
    for what the verdict states outright. So the actions carry the difference and `default` carries the
    shared context.

    (An earlier version of this test asserted `reasoned_over == ()`, from misreading a multi-line YAML
    list as empty. The shape was right; the reason was not.)"""
    judgment = load_rule_spec("CR-8").judgment
    assert judgment is not None and judgment.guidance is not None

    assert len(judgment.reasoned_over) == 4  # tags exist — they are just not the axis
    assert len(judgment.value_domain) == 6
    assert judgment.guidance.explain_by is None
    assert set(judgment.guidance.explain) == {"default"}


def test_cases_without_an_explanatory_tag_are_rejected_at_load() -> None:
    """Cases that nothing can select would sit in the spec looking authored and never render."""
    with pytest.raises(ValidationError, match="no `explain_by` tag to select them"):
        JudgmentEval(
            subject="loan",
            load_bearing_tags=("occupancy.stated",),
            reasoned_over=("occupancy.stated",),
            output_tag="occupancy.reasonable",
            value_domain=("yes", "no", "unknown"),
            system_prompt="x",
            guidance={
                "action": {"yes": "A.", "no": "B.", "unknown": "C."},
                "explain": {
                    "default": {"why": "w", "how_to_fix": "f"},
                    "somecase": {"why": "w", "how_to_fix": "f"},
                },
            },
        )


def test_dt7_never_asserts_an_ability_to_repay_determination() -> None:
    """⚠️ A COMPLIANCE BOUNDARY, not a wording preference. Ability-to-repay is a CREDITOR obligation
    under Regulation Z, assessed at underwriting. A processor assembling a file is not the party making
    it, and text telling them to "confirm the borrower can repay" would put a compliance conclusion in
    the wrong queue. DT-7 asks only what the file CARRIES — the spec's own header says the rule's NAME
    invites the stronger reading, which is exactly why this is pinned.
    """
    judgment = load_rule_spec("DT-7").judgment
    assert judgment is not None and judgment.guidance is not None
    text = " ".join(
        [
            *judgment.guidance.action.values(),
            *(c.why for c in judgment.guidance.explain.values()),
            *(c.how_to_fix for c in judgment.guidance.explain.values()),
        ]
    ).lower()

    for forbidden in ("can repay", "able to repay", "ability of the borrower", "determine whether"):
        assert forbidden not in text, (
            f"DT-7 guidance drifts into an ATR determination: {forbidden!r}"
        )
    assert "document" in text


def test_oc2_says_what_a_wrong_occupancy_costs() -> None:
    """Occupancy drives pricing, the LTV limit and reserves. A fix that only asked for a document would
    read as paperwork; a processor needs to know a misstatement changes the loan."""
    judgment = load_rule_spec("OC-2").judgment
    assert judgment is not None and judgment.guidance is not None

    conflict = judgment.guidance.explain["no"].how_to_fix.lower()
    assert "pricing" in conflict and "reserves" in conflict


def test_every_active_judgment_rule_has_guidance() -> None:
    """LP-622 — WAS `test_the_other_judgment_rules_are_untouched`, an allow-list of the five rules that
    had adopted LP-522. Fourteen had not, and every one of them rendered "the AI judged '<value>' — an
    AI verdict a human must ratify" with how_to_fix NULL: our engine explained to a processor instead of
    their loan. OC-3 was the one a processor actually read.

    Inverted deliberately. An allow-list grows quietly and says nothing when a NEW judgment rule ships
    wordless; this fails the moment one does. LP-522's caution — "inventing a fix for a rule nobody has
    read is worse than vague wording" — is honoured by having read each spec's criteria, guideline and
    tag enum, not by leaving the text unwritten."""
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
    from app.verification.rules.kinds import RuleKindName, kind_for

    wordless = [
        rule_id
        for rule_id in sorted(ACTIVE_RULE_IDS)
        if (kind := kind_for(rule_id)) is not None
        and kind.kind is RuleKindName.JUDGMENTAL
        and (spec := load_rule_spec(rule_id)).judgment is not None
        and spec.judgment.guidance is None
    ]

    assert not wordless, (
        f"these judgment rules would render \"the AI judged '<value>'\" with no fix: {wordless}"
    )


def test_every_judgment_rule_has_an_action_for_every_verdict() -> None:
    """A verdict with no action raises KeyError at message time — on whichever answer is rarest, which
    is the one least likely to be seen before a processor does."""
    from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
    from app.verification.rules.kinds import RuleKindName, kind_for

    for rule_id in sorted(ACTIVE_RULE_IDS):
        kind = kind_for(rule_id)
        if kind is None or kind.kind is not RuleKindName.JUDGMENTAL:
            continue
        judgment = load_rule_spec(rule_id).judgment
        if judgment is None or judgment.guidance is None:
            continue
        missing = set(judgment.value_domain) - set(judgment.guidance.action)
        assert not missing, f"{rule_id} has no action for verdict(s) {sorted(missing)}"
