"""LP-810 — the drafting engine's guards, which are the only thing between a model and a borrower.

`finding_prose`'s guards keep a processor from reading something silly. These keep a lender from
making a statement it is not allowed to make: a rate, a payment amount, a Reg Z triggering term, an
approval, a settlement-service recommendation, an account number.

Every check here is DETERMINISTIC, and that is the design. Asking a model whether a model said
something it should not have has the same failure mode as the thing it is checking.

Each refusal is paired with an acceptance of ordinary prose that shares its vocabulary, because a
guard that turns away legitimate text is one nobody finds out about until a draft silently falls back
to the plain template every single time — which looks exactly like the flag being off.
"""

from __future__ import annotations

import pytest
from app.ai.email_draft import (
    DraftComposition,
    DraftFacts,
    rejection_reason,
)

_FACTS = DraftFacts(
    borrower_first_name="the borrower",
    loan_reference="LF-6T3N",
    requested_labels=("Bank statements — the two most recent months", "W-2s — the last two years"),
)


def _draft(opening: str = "We are working through your file.", **kw: str) -> DraftComposition:
    parts = {
        "opening": opening,
        "bridge": "Here is what we still need:",
        "closing": "Ask us if anything is unclear.",
    }
    parts.update(kw)
    return DraftComposition(**parts)  # type: ignore[arg-type]


def test_ordinary_framing_passes() -> None:
    """The control for everything below. Without it, a `rejection_reason` that refused everything
    would satisfy every other test in this file — and the symptom would be a draft that always falls
    back to the plain template, which is indistinguishable from the flag being off."""
    assert rejection_reason(_FACTS, _draft()) is None


# --------------------------------------------------------------------------------------------- #
# Regulatory refusals
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Your rate of 6.5% is locked.", "rate"),
        ("The APR will be confirmed at closing.", "rate"),
        ("We have your interest rate on file.", "rate"),
        ("Your payment will be $2,400 a month.", "money_amount"),
        ("The downpayment is still outstanding.", "triggering_term"),
        ("We need this before your monthly payment is set.", "triggering_term"),
        ("The finance charge has been calculated.", "triggering_term"),
        ("Good news, your loan is approved.", "commitment"),
        ("You are pre-approved for this amount.", "commitment"),
        ("Your file was declined by the underwriter.", "commitment"),
        ("We guarantee this will close on time.", "commitment"),
        ("Please wire to routing number 021000021.", "payment_routing"),
        ("Send your account number when you can.", "payment_routing"),
    ],
)
def test_a_statement_a_lender_may_not_make_is_refused(text: str, reason: str) -> None:
    """12 CFR §1026.24(d)(1) makes the amount of any payment, the amount or percentage of any
    downpayment, the number of payments or period of repayment, and the amount of any finance charge
    into triggering terms — stating one obliges further disclosures no email carries. Whether a
    request to an existing applicant is an "advertisement" is not a question this code should decide
    on the fly, so the scanner refuses the term rather than the argument.

    Read 2026-09-07 from 12 CFR §1026.24, Advertising."""
    assert rejection_reason(_FACTS, _draft(text)) == reason


def test_a_settlement_service_recommendation_needs_both_halves() -> None:
    """RESPA territory, and the guard is scoped to a RECOMMENDATION plus a SERVICE. Either alone is
    ordinary English — "your title company will send it to us" is a sentence a processor writes every
    day, and refusing it would make the flag useless on any file with a title company in it."""
    assert (
        rejection_reason(_FACTS, _draft("We recommend using our title company."))
        == "settlement_service"
    )
    assert rejection_reason(_FACTS, _draft("Your title company will send that to us.")) is None
    assert rejection_reason(_FACTS, _draft("We recommend sending these together.")) is None


# --------------------------------------------------------------------------------------------- #
# The model does not write instructions
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text",
    [
        "Make sure all pages are included.",
        "The statement must show your name and the full period.",
        "Be sure to send every page.",
        "We cannot accept a screenshot.",
    ],
)
def test_an_invented_instruction_is_refused(text: str) -> None:
    """The plan asks that the model quote the catalog's guidance and never invent an instruction,
    enforced the way numbers are enforced. Numbers work because a number is a token; a reworded
    instruction is a judgement, and a judgement is exactly what a deterministic guard cannot make.

    So the rule is made STRUCTURAL instead: the model writes only the framing, and the document list
    is interpolated from the catalog. That removes the legitimate case, which leaves an obligation
    sentence in the model's output always being an invented one — and THAT is decidable."""
    assert rejection_reason(_FACTS, _draft(text)) == "invented_instruction"


def test_a_message_that_breaks_two_rules_reports_the_more_serious_one() -> None:
    """`rejection_reason` returns ONE reason, so its order is a decision. Regulatory refusals come
    before stylistic ones: "must show your account number" is both an invented instruction and a
    routing reference, and the routing half is the one that would matter if it went out.

    Found by writing this case as an instruction test and watching it report the other reason — which
    is the ordering working, not a bug, but only visible because the assertion named a specific
    reason rather than merely asserting that something was refused."""
    both = _draft("The statement must show your account number.")
    assert rejection_reason(_FACTS, both) == "payment_routing"


def test_the_real_instructions_still_reach_the_borrower() -> None:
    """The control for the rule above, and the one that matters: refusing the model's instructions is
    only acceptable because the catalog's own instructions are in the email. LP-800's guidance goes in
    through `render_document_block`, not through anything checked here."""
    from app.communications.templates import render_document_block

    block = render_document_block(("bank_statement",))
    assert "must show" in block or "Every page" in block
    assert "page 1 of 5" in block


# --------------------------------------------------------------------------------------------- #
# Shared guards, not re-derived
# --------------------------------------------------------------------------------------------- #
def test_a_leaked_identifier_is_refused() -> None:
    """`leaked_identifiers_in` imported from `finding_prose` rather than restated — bug-006 was a
    second copy of that union drifting from the first."""
    text = "Regarding borrower 7558383f-dfbb-47c3-8b3f-aa1ca5494987, we need a little more."
    assert rejection_reason(_FACTS, _draft(text)) == "identifier"


def test_an_invented_number_is_refused() -> None:
    """The hallucination check, shared with `finding_prose`. 45 appears nowhere in the facts."""
    assert rejection_reason(_FACTS, _draft("We have been waiting 45 days for these.")).startswith(
        "unsupported_numbers"
    )


def test_a_number_from_a_requested_label_is_not_licensed_anywhere() -> None:
    """LP-597 and LP-613 each cost a shipped defect to learn this: a label like "W-2s — the last two
    years" would otherwise license its digits ANYWHERE in the output. The labels are passed as
    `unlicensed`, so a number that only appears inside one cannot be quoted as a fact."""
    facts = DraftFacts(
        borrower_first_name="the borrower",
        loan_reference="LF-6T3N",
        requested_labels=("Form 1099 for 2024",),
    )
    assert rejection_reason(facts, _draft("We are still missing 1099 items.")) is not None


# --------------------------------------------------------------------------------------------- #
# The cache key
# --------------------------------------------------------------------------------------------- #
def test_the_same_request_produces_the_same_key() -> None:
    """Determinism is why the cache exists. LP-809 regenerates on every add and every remove, so
    without a stable key a processor who adds one document finds the other paragraphs reworded under
    their cursor — bug-008 arriving on text a person is editing."""
    assert (
        _FACTS.cache_key()
        == DraftFacts(
            borrower_first_name="the borrower",
            loan_reference="LF-6T3N",
            requested_labels=(
                "Bank statements — the two most recent months",
                "W-2s — the last two years",
            ),
        ).cache_key()
    )


def test_a_different_document_list_produces_a_different_key() -> None:
    """The positive control: a key that never changed would also satisfy the test above."""
    other = DraftFacts(
        borrower_first_name="the borrower",
        loan_reference="LF-6T3N",
        requested_labels=("Bank statements — the two most recent months",),
    )
    assert other.cache_key() != _FACTS.cache_key()


def test_reordering_the_documents_changes_the_key() -> None:
    """Order is what the borrower reads, so it is part of the composition and part of the key."""
    reversed_labels = DraftFacts(
        borrower_first_name="the borrower",
        loan_reference="LF-6T3N",
        requested_labels=(
            "W-2s — the last two years",
            "Bank statements — the two most recent months",
        ),
    )
    assert reversed_labels.cache_key() != _FACTS.cache_key()
