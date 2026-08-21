"""LP-612 — FR-5 said "accounted for" about an amount it never looked at.

FROM THE RUN. On LF-3CVT, after the bank statements landed:

    UNITED WHSLE MORT   bank $3,286.21/mo   application $3,186.00   -> "accounted for"
    CITI                bank $4,802.22/mo   application    $49.00   -> "accounted for"

Neither is a defect in the rule. FR-5 asks whether a recurring debit's payee is DISCLOSED, and in both
cases it is; its own criteria say "the file's stated liabilities are not reachable from a transaction
subject", and the exemption fires on `txn.stated_liability_match` — a payee match.

The defect was the sentence. "Already accounted for" reads as the payment having been checked, over a
$100 gap and a $4,753 one. The rule that compares a stated housing payment against what the servicer
bills is DT-6, and it needs a mortgage statement or 1098 to run.
"""

from __future__ import annotations

from app.verification.rules.specs import load_rule_spec

_ASKING = ("obtain", "confirm", "verify", "review", "check", "upload", "provide", "request")


def _message() -> str:
    return " ".join((load_rule_spec("FR-5").judgment.exempt_message or "").split())


def test_the_pass_no_longer_claims_the_payment_is_accounted_for() -> None:
    assert "already accounted for" not in _message().lower()


def test_it_says_what_was_matched() -> None:
    """A processor should be able to tell what this pass rests on without opening the rule."""
    message = _message().lower()

    assert "payee" in message
    assert "liability list" in message


def test_it_says_what_was_not_matched() -> None:
    """THE POINT. The amount is the thing a reader assumes was checked, and it is the one thing this
    rule cannot reach."""
    message = _message().lower()

    assert "not compared" in message
    assert "amount" in message or "what leaves the account" in message


def test_it_still_reads_as_a_pass() -> None:
    """FR-5's spec is explicit that a pass reads as a pass — no "confirm", no "verify", no "obtain".
    Stating the SCOPE of a match is not asking for work, and the distinction has to hold or the
    composer's `asking_on_a_pass` guard rejects this and ships the raw template instead."""
    message = _message().lower()

    assert not message.startswith(_ASKING)
    for verb in _ASKING:
        assert f" {verb} the " not in message, f"the pass reads as a task ({verb})"


def test_the_exemption_still_fires_on_a_payee_match_only() -> None:
    """The wording changed; the mechanism did not. Both grades still clear, per FR-3's FP > FN bar."""
    judgment = load_rule_spec("FR-5").judgment
    values = {c.value for c in judgment.exempt_when}

    assert values == {"exact", "probable"}
    assert judgment.exempt_unless_judgment_in == ()
