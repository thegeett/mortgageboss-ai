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
