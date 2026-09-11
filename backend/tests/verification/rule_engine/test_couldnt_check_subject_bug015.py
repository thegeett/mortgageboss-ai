"""bug-015 — a couldnt_check about a transaction says WHICH transaction.

On LF-XMB2 the Couldn't-check tab carried seven rows a processor cannot tell apart. Four of them, all
AS-12, read exactly:

    "the deposit category could not be read from the documents (it is present but unclear)"

and three more (AS-1, AS-2) read "the file does not clearly establish the deposit direction, so it is
not known whether this requirement applies here". They were about seven different transactions — a
$19,039.08 deposit, a $31,000 deposit, an $8,000 deposit, a $70 Zelle payment, two $30 transfers.

A couldnt_check reason is built from the tag that blocked it (`gate.py`, `applicability.py`) and knows
nothing about the subject, so every subject of a rule gets the same sentence. The composer normally
rewrites these into specific prose; when it rejects its own draft the template ships, which is what
happened here.

The subject is prefixed from the SAME resolver the list view and the composer use, so a finding cannot
name its subject one way in one place and another way in another.
"""

from __future__ import annotations

from app.services.rule_findings import _persistable
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict

_GATE_TEMPLATE = (
    "the transaction category could not be read from the documents (it is present but unclear)"
)


def _tag(tag_id: str, value: str) -> LoadBearingTag:
    return LoadBearingTag(tag_id, value, 0.9, "fixture", ("txnfixture0000001",))


def _evaluation(
    subject_id: str,
    *,
    verdict: Verdict = Verdict.COULDNT_CHECK,
    tags: tuple[LoadBearingTag, ...] = (),
    reasoning: str = _GATE_TEMPLATE,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id="AS-12",
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=None,
        load_bearing_tags=tags,
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning=reasoning,
        how_to_fix=None,
    )


def _message(evaluation: RuleEvaluation) -> str:
    [(_result, _outcome, _severity, message)] = _persistable([evaluation])
    return message


def test_a_deposit_that_could_not_be_checked_names_itself() -> None:
    """THE LF-XMB2 SHAPE — the $19,039.08 deposit of 2026-02-25."""
    message = _message(
        _evaluation(
            "txna10e7b49c4112404",
            tags=(
                _tag("txn.is_money_in", "in"),
                _tag("txn.amount", "19039.08"),
                _tag("txn.date", "2026-02-25"),
            ),
        )
    )

    assert message == f"Deposit of $19,039.08 on 2/25 — {_GATE_TEMPLATE}"


def test_a_withdrawal_is_not_called_a_deposit() -> None:
    """FR-5's subjects are money OUT. The label layer is direction-aware and the prefix inherits that."""
    message = _message(
        _evaluation(
            "txn6b24c5432fedebf5",
            tags=(
                _tag("txn.is_money_in", "out"),
                _tag("txn.amount", "24.34"),
                _tag("txn.date", "2025-12-26"),
            ),
        )
    )

    assert message.startswith("Payment of $24.34 on 12/26 — ")


def test_an_unknown_direction_still_identifies_the_subject() -> None:
    """The direction is the very thing that could not be established here, so the noun is dropped and
    the amount and date — which ARE known — do the identifying. Guessing "deposit" would assert the
    fact the finding says it cannot establish."""
    message = _message(
        _evaluation(
            "txn59248d5b675ba74d",
            tags=(
                _tag("txn.is_money_in", "unknown"),
                _tag("txn.amount", "30.00"),
                _tag("txn.date", "2026-02-20"),
            ),
            reasoning="the file does not clearly establish the transaction direction",
        )
    )

    assert message.startswith("$30 on 2/20 — ")
    assert "deposit" not in message.lower()


def test_two_transactions_no_longer_read_identically() -> None:
    """The complaint, in one assertion: same rule, same template, different subjects."""
    first, second = (
        _message(
            _evaluation(
                subject,
                tags=(
                    _tag("txn.is_money_in", "in"),
                    _tag("txn.amount", amount),
                    _tag("txn.date", date),
                ),
            )
        )
        for subject, amount, date in (
            ("txna10e7b49c4112404", "19039.08", "2026-02-25"),
            ("txnbfc7b8c2627b38d5", "31000.00", "2026-03-16"),
        )
    )

    assert first != second
    assert "$19,039.08" in first and "$31,000" in second


def test_a_subject_the_tags_do_not_identify_is_left_alone() -> None:
    """`_deposit_label` degrades to "a transaction" with no amount. Prefixing that adds nothing and
    would push the sentence a processor reads to the right for no gain."""
    message = _message(_evaluation("txn0bbc15b93316a2a7", tags=(_tag("txn.is_money_in", "in"),)))

    assert message == _GATE_TEMPLATE


def test_a_loan_or_borrower_subject_is_left_alone() -> None:
    """Only a transaction subject. A loan-level couldnt_check already reads about the file as a whole,
    and "Whole file — …" is noise in front of it."""
    assert _message(_evaluation("loan")) == _GATE_TEMPLATE


def test_only_a_couldnt_check_is_prefixed() -> None:
    """Every other outcome interpolates its own operands: AS-1's fired reasoning already opens
    "deposit 19039.08 exceeds the large-deposit threshold …". Prefixing would say it twice."""
    fired = _evaluation(
        "txna10e7b49c4112404",
        verdict=Verdict.FIRED,
        tags=(
            _tag("txn.is_money_in", "in"),
            _tag("txn.amount", "19039.08"),
            _tag("txn.date", "2026-02-25"),
        ),
        reasoning="deposit 19039.08 exceeds the large-deposit threshold 5596.995 and is not sourced",
    )

    assert _message(fired).startswith("deposit 19039.08 exceeds")
