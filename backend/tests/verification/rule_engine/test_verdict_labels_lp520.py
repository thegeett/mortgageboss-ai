"""LP-520 — a judgment finding must state its QUESTION, not a bare domain value.

THE PROBLEM, from live staging output on LF-WCHG:

    the AI judged 'yes' — an AI verdict a human must ratify (it never auto-ships); $2,000 is above ...

Judged WHAT? The message never says. And on AS-12 the polarity is the counterintuitive one — "yes"
means *this may be borrowed funds*, the answer that needs work — where a reader meeting a bare "yes"
would assume the opposite. The evaluator is generic across every judgment rule and has nothing
rule-specific to say, so the SPEC says it: `verdict_labels` maps each `value_domain` entry to a
sentence.

Also here: `_money` now always renders cents. It never lost precision ($1,999.87 rendered in full), but
"$2,000" gave a reader no way to tell exact from rounded, and on a fraud-adjacent finding that doubt is
not worth the tidier line.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.verification.rule_engine.judgment import _money, _verdict_message
from app.verification.rules.specs import JudgmentEval, load_rule_spec
from pydantic import ValidationError

_AS12_LABELS = load_rule_spec("AS-12").judgment.verdict_labels  # type: ignore[union-attr]


def _judgment(**overrides: object) -> JudgmentEval:
    base: dict[str, object] = {
        "subject": "per_deposit",
        "load_bearing_tags": ("txn.apparent_category",),
        "reasoned_over": ("txn.apparent_category",),
        "output_tag": "as.borrowed_funds",
        "value_domain": ("yes", "no", "unknown"),
        "system_prompt": "x",
    }
    return JudgmentEval(**(base | overrides))  # type: ignore[arg-type]


def test_a_labelled_verdict_states_the_question_instead_of_a_bare_value() -> None:
    message = _verdict_message("yes", 0.9, 0.5, labels=_AS12_LABELS)

    assert "may come from an undisclosed borrowed source" in message
    assert "'yes'" not in message, "the bare domain value must not survive alongside its label"


def test_an_unlabelled_rule_keeps_its_previous_wording_exactly() -> None:
    """ADDITIVE. Most judgment rules have not adopted labels; their findings must be untouched, so this
    can land rule by rule rather than as one sweeping text change."""
    assert _verdict_message("yes", 0.9, 0.5) == (
        "the AI judged 'yes' — an AI verdict a human must ratify (it never auto-ships)"
    )


def test_a_low_confidence_labelled_verdict_keeps_both_the_label_and_the_numbers() -> None:
    message = _verdict_message("no", 0.2, 0.5, labels=_AS12_LABELS)

    assert "does not appear to come from a borrowed source" in message
    assert "0.2 < 0.5" in message


def test_an_unknown_label_reads_as_a_statement_not_as_something_the_ai_judged() -> None:
    """ "the AI judged that the tags do not support a confident judgment" is nonsense — an `unknown`
    label describes the STATE of the evidence, so it stands as its own sentence."""
    message = _verdict_message("unknown", None, 0.5, labels=_AS12_LABELS)

    assert message.startswith("the tags do not support a confident judgment")
    assert "the AI judged" not in message


def test_the_derivation_survives_a_label() -> None:
    """LP-518's materiality arithmetic must still be appended — the two features compose."""
    message = _verdict_message("yes", 0.9, 0.5, "$8,000.00 is above the floor", _AS12_LABELS)

    assert "may come from an undisclosed borrowed source" in message
    assert message.endswith("; $8,000.00 is above the floor")


def test_a_partial_label_map_is_rejected_at_load() -> None:
    """⚠️ THE DECISIVE VALIDATION. A map missing one value falls back to the raw verdict for exactly
    that value — the defect this field exists to remove, reappearing on the rarest answer, where nobody
    would notice it. Total or absent; never partial."""
    with pytest.raises(ValidationError, match=r"verdict_labels is missing value\(s\)"):
        _judgment(verdict_labels={"yes": "bad", "no": "fine"})  # `unknown` omitted


def test_a_label_outside_the_value_domain_is_rejected_at_load() -> None:
    """A typo'd key would never be looked up, leaving that verdict silently unlabelled."""
    with pytest.raises(ValidationError, match="outside value_domain"):
        _judgment(verdict_labels={"yes": "a", "no": "b", "unknown": "c", "maybe": "d"})


def test_no_labels_is_valid_and_means_not_adopted_yet() -> None:
    assert _judgment().verdict_labels == {}


def test_the_exempt_override_domain_check_still_runs_on_an_unlabelled_rule() -> None:
    """⚠️ REGRESSION GUARD. Adding `verdict_labels` orphaned LP-516's
    `exempt_unless_judgment_in`-outside-`value_domain` check behind the new validator's early return,
    so it silently stopped running for every rule without labels — the exact class of silent-disable
    this ticket's own validation is written to prevent. Asserted on an UNLABELLED rule specifically,
    because that is the case that broke."""
    from app.verification.rules.specs import TagCondition

    with pytest.raises(ValidationError, match="outside value_domain"):
        _judgment(
            exempt_when=TagCondition(tag="txn.apparent_category", op="eq", value="payroll"),
            exempt_unless_judgment_in=("YES",),  # wrong case — not in the domain
        )


def test_as12_declares_a_label_for_every_answer_it_can_give() -> None:
    judgment = load_rule_spec("AS-12").judgment
    assert judgment is not None
    assert set(judgment.verdict_labels) == set(judgment.value_domain)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("2000", "$2,000.00"),  # the case that motivated this — no longer bare "$2,000"
        ("1999.87", "$1,999.87"),
        ("1316.666666", "$1,316.67"),  # display-only rounding; the COMPARISON stays full-precision
        ("0.03", "$0.03"),
    ],
)
def test_money_always_shows_cents(amount: str, expected: str) -> None:
    assert _money(Decimal(amount)) == expected
