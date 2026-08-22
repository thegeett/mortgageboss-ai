"""bug-001 — DT-6's abstention had no action, and the composer wrote its own.

On a real file DT-6 and RE-1 fired on the same unmatched Lake Michigan Credit Union statement:

    RE-1 (needs_review): "...and if so, ADD IT TO THE APPLICATION'S LIABILITY LIST."
    DT-6 (couldnt_check): "Confirm whether the mortgage is BEING PAID OFF AT CLOSING OR RETAINED."

One lien, two different instructions — from the rule whose own header promises it will not
"double-report the discrepancy RE-1 already surfaced".

DT-6 was obeying that promise STRUCTURALLY: its verdict was couldnt_check, exactly as designed. The
prose was the problem, and the cause was three steps back:

  1. the gate path short-circuits before any declared outcome and reads `couldnt_check_fix`;
  2. DT-6 declared its careful guidance on the couldnt_check OUTCOME instead, so the gate found none
     and the finding shipped with `how_to_fix` NULL;
  3. the composer must "make THE SAME REQUEST as suggested_fix" — and with no request to make, it
     reasoned from the situation to a DIFFERENT question, which another rule already owned.
"""

from __future__ import annotations

from app.verification.rules.specs import load_rule_spec


def test_dt6_declares_a_gate_fix_so_the_composer_is_never_left_to_invent_one() -> None:
    fix = load_rule_spec("DT-6").deterministic.couldnt_check_fix
    assert fix is not None
    # It asks for what DT-6 actually needs...
    assert "which liability" in fix and "monthly payment" in fix
    # ...and hands the undisclosed-mortgage question back to the rule that owns it.
    assert "undisclosed-mortgage-obligation check" in fix


def test_dt6_does_not_ask_the_disposition_question_that_belongs_to_re1() -> None:
    """The specific words the composer invented. DT-6 asks which liability the statement belongs to;
    whether the mortgage survives closing is RE-1's question, and RE-1 was asking it."""
    fix = load_rule_spec("DT-6").deterministic.couldnt_check_fix or ""
    lowered = fix.lower()
    assert "paid off at closing" not in lowered
    assert "retained" not in lowered


def test_declaring_the_fix_invalidates_prose_composed_without_it() -> None:
    """Why this reaches the finding already on the file rather than only new ones.

    The composer's cache is persistent and keyed on the FACTS (`sha256(to_json())`), with no prompt
    version in it — so a prompt change alone would leave every already-composed finding exactly as it
    was. Adding a `couldnt_check_fix` changes the facts, which changes the key, which turns the stored
    invented action into a MISS. LP-601 built the same self-healing property for guards."""
    from app.ai.finding_prose import FactSummary

    without = FactSummary(
        rule_name="DT-6",
        subject="a mortgage statement",
        problem="no mortgage liability stated on the application names a matching holder",
        fix=None,
    )
    with_fix = FactSummary(
        rule_name="DT-6",
        subject="a mortgage statement",
        problem="no mortgage liability stated on the application names a matching holder",
        fix="Identify which liability on the application this mortgage statement belongs to.",
    )
    assert without.cache_key() != with_fix.cache_key()


def test_the_composer_is_told_what_to_do_when_no_fix_is_declared() -> None:
    """The systemic half. DT-6 is now covered by declaring a fix, but 44 other rules that can gate
    still declare none, and the prompt had NO rule for that case — it only said the action must match
    a `suggested_fix` that was not there."""
    import re

    from app.ai.finding_prose import SYSTEM_PROMPT

    # Whitespace-normalized: the prompt is hard-wrapped, so pinning a line break would make this fail
    # the next time someone reflows a paragraph rather than when the rule goes missing.
    prompt = re.sub(r"\s+", " ", SYSTEM_PROMPT)
    assert 'WHEN "suggested_fix" IS ABSENT' in prompt
    assert "introduce NO new question" in prompt
    assert "another rule may own that question" in prompt
