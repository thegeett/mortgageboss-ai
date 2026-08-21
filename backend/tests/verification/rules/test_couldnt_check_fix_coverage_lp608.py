"""LP-608 — a rule that cannot run must still say what to do about it.

FIVE ACTIVE RULES SHIPPED NO FIX TEXT while each needing two to four kinds of document. With nothing
to anchor to, the composer invents an action from the problem text — and on LF-3CVT DT-7 shipped:

    "Add the missing ability-to-repay documentation."

DT-7 needs a credit report, pay stubs or W-2s, bank statements and the Closing Disclosure. That
sentence names none of them. It restates the verdict instead of instructing, and a processor cannot
act on it.

The four deterministic ones now declare `couldnt_check_fix`. DT-7 is a JUDGMENT rule and has no such
field — its action comes from `guidance.action`, so that is where its fix went.
"""

from __future__ import annotations

import pytest
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import load_rule_spec

_NEEDED_TWO_OR_MORE = ("AS-4", "ID-5", "PC-7", "PR-2")


@pytest.mark.parametrize("rule_id", _NEEDED_TWO_OR_MORE)
def test_a_multi_document_rule_says_what_to_upload(rule_id: str) -> None:
    fix = load_rule_spec(rule_id).deterministic.couldnt_check_fix

    assert fix and fix.strip(), f"{rule_id} still ships no couldnt_check fix"


@pytest.mark.parametrize("rule_id", _NEEDED_TWO_OR_MORE)
def test_the_fix_names_every_document_kind_the_rule_needs(rule_id: str) -> None:
    """THE POINT. IH-3's fix named one side of a two-sided comparison, so a processor who uploaded it
    found the rule still unable to answer. A static sentence has to hold whichever input is the
    missing one — which means naming them all."""
    spec = load_rule_spec(rule_id)
    fix = (spec.deterministic.couldnt_check_fix or "").lower()

    for group in spec.requires_documents or ():
        # Any ALTERNATIVE in the group satisfies it — a group is "a driver's license OR a passport
        # OR ...", so naming one of them is naming the group.
        words = [w for t in group for w in t.split("_") if len(w) > 3]
        assert any(w in fix for w in words), (
            f"{rule_id}'s fix never mentions {list(group)} — a processor who supplies everything it "
            f"does name would find it still unable to answer"
        )


def test_dt7_tells_a_processor_which_documents_to_get() -> None:
    """DT-7 is a judgment rule: no `couldnt_check_fix` field exists, so its action lives in
    `guidance.action`. It read "Add the missing ability-to-repay documentation." — a restatement of
    the verdict, naming none of the four document kinds the rule declares."""
    guidance = load_rule_spec("DT-7").judgment.guidance
    action = guidance.action["no"].lower()

    assert "add the missing ability-to-repay documentation" not in action
    for kind in ("credit report", "bank statement", "closing disclosure"):
        assert kind in action, f"DT-7's action does not name the {kind}"


def test_no_active_multi_document_rule_is_left_silent() -> None:
    """The audit that found the five, kept as a test so a NEW rule cannot join them quietly."""
    silent = []
    for rule_id in sorted(ACTIVE_RULE_IDS):
        spec = load_rule_spec(rule_id)
        if len(spec.requires_documents or ()) < 2:
            continue
        body = spec.deterministic
        if body is None:  # a judgment rule carries its action in `guidance` instead
            continue
        if not (body.couldnt_check_fix or "").strip():
            silent.append(rule_id)

    assert not silent, (
        f"these rules need several documents and say nothing about which when they cannot run: "
        f"{silent}"
    )


def test_in3_offers_both_branches_not_just_upload() -> None:
    """LP-609 — IN-3 asked a processor to upload a pay stub on a file that already carried two.

    The composer could not correct that on its own: its instruction is to make THE SAME REQUEST as the
    fix text, and the guard rejects a rewrite that asks for anything else. So the alternative has to
    exist in the template for it to have something legitimate to choose.

    Why one document needed two branches at all: IN-3 reads
    `income.ytd_annualized_shortfall_pct`, whose own dependencies reach past the pay stub. The
    document can be present and the rule still unable to answer — a shape no audit of the spec can
    see, since the spec declares one document and names it.
    """
    fix = load_rule_spec("IN-3").deterministic.couldnt_check_fix or ""

    assert "Upload the borrower's most recent pay stub" in fix  # the file-has-nothing branch
    assert "already in the file" in fix  # the file-has-them branch
    assert "legible" in fix, "the second branch must say what to DO, not merely note they are there"


# --------------------------------------------------------------------------- #
# LP-610 — a fix that asks for both every time asks again for what you gave it
# --------------------------------------------------------------------------- #

#: Every active rule needing two kinds of document. LP-603/608 made each NAME both sides, which fixed
#: a text that presumed which one was missing; all nine then asked for BOTH every time, so a file
#: carrying one was told to upload it again — IN-3's symptom, one step milder.
_TWO_SIDED = ("AS-4", "CL-1", "CR-13", "CR-6", "ID-5", "IH-3", "PC-7", "PR-2", "PR-6")


@pytest.mark.parametrize("rule_id", _TWO_SIDED)
def test_a_two_document_fix_says_what_to_do_when_one_is_already_there(rule_id: str) -> None:
    """The composer can only choose among requests the template makes, so the second branch has to be
    written here. `document_kinds_on_file` (LP-609) is what lets it pick."""
    fix = " ".join((load_rule_spec(rule_id).deterministic.couldnt_check_fix or "").split()).lower()

    assert "already in the file" in fix, (
        f"{rule_id} asks for both documents unconditionally, so a file carrying one is told to "
        f"upload it again"
    )


def test_pc7_does_not_ask_for_the_second_document_it_does_not_need() -> None:
    """⚠️ PC-7 IS NOT LIKE THE OTHER EIGHT, and a uniform clause got it wrong before this test.

    Its two document groups are ALTERNATIVES for one fact — the closing date comes from the purchase
    agreement OR the Closing Disclosure — not two sides of a comparison. "Upload only the other" would
    contradict its own preceding sentence and send a processor after a document nothing needs.
    """
    fix = " ".join((load_rule_spec("PC-7").deterministic.couldnt_check_fix or "").split())

    assert "upload only the other" not in fix.lower()
    assert "nothing further is needed" in fix.lower()


def test_the_other_eight_do_ask_for_the_missing_side() -> None:
    """The inverse of the PC-7 case: where the two documents really are two sides, the one that is
    missing is still owed."""
    for rule_id in (r for r in _TWO_SIDED if r != "PC-7"):
        fix = " ".join((load_rule_spec(rule_id).deterministic.couldnt_check_fix or "").split())
        assert "upload only the other" in fix.lower(), rule_id
