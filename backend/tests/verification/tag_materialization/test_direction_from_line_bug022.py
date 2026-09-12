"""bug-022 — nine findings because nobody read the first two words of the line.

Three trivial transactions on LF-XMB2 produced nine Couldn't-check findings: a $70 "Zel To Mariam
Imoisili" and two $30 "Online Transfer To XXXXX8307", each abstaining under AS-1, AS-2 and AS-12
because `txn.is_money_in` is their applicability predicate and it read "unknown".

`documents_section._direction` classifies from `transaction_type` alone — correctly, since a positive
amount carries no direction and inferring one would forge a deposit on every unlabelled withdrawal. When
that field is null the model is handed `"direction": null` and answers unknown, honestly, about a field
that was empty rather than about the sentence in front of it.

This is a floor BENEATH the model, never a replacement for it: a definite "in"/"out" is never
overridden, the fallback reads only openings the bank itself printed, and a line that says it was undone
stays unknown.
"""

from __future__ import annotations

from app.ai.tag_production import TagJudgment
from app.services.tag_production import _Judged, _money_in_tag
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import TransactionRecord
from app.verification.snapshot.tag import TagProducedBy


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _txn(description: str | None) -> TransactionRecord:
    return TransactionRecord(
        content_id="txn1",
        date=_f("2026-02-26"),
        amount=_f("70.00"),
        direction=Field.missing(),  # the extractor could not classify it — the shape this fixes
        description=_f(description) if description is not None else Field.missing(),
    )


def _judged(direction: str | None) -> _Judged:
    """The model's answer: a value, or None for "it did not resolve one"."""
    judgment = TagJudgment(direction, 0.9, "model reasoning") if direction is not None else None
    return _Judged(judgment, None, "the model did not resolve a direction")


# --------------------------------------------------------------------------- #
# The floor
# --------------------------------------------------------------------------- #
def test_the_zelle_line_from_lf_xmb2_resolves_to_money_out() -> None:
    """THE $70 LINE. "Zel To Mariam Imoisili" — three rules abstained on it."""
    tag = _money_in_tag(_txn("Zel To Mariam Imoisili"), _judged("unknown"))

    assert tag.value == "out"


def test_the_online_transfer_line_from_lf_xmb2_resolves_to_money_out() -> None:
    """THE $30 LINES, twice over."""
    tag = _money_in_tag(_txn("Online Transfer To XXXXX8307"), _judged("unknown"))

    assert tag.value == "out"


def test_a_from_line_resolves_to_money_in() -> None:
    tag = _money_in_tag(_txn("Online Transfer From Savings"), _judged(None))

    assert tag.value == "in"


def test_the_resolved_tag_is_derived_and_says_what_it_read() -> None:
    """Not the model's own answer and never dressed as one: no confidence, produced_by DERIVED, and a
    reason naming the words it read, so a ratifier can tell judgment from printing."""
    tag = _money_in_tag(_txn("Zel To Mariam Imoisili"), _judged("unknown"))

    assert tag.produced_by is TagProducedBy.DERIVED
    assert tag.confidence is None
    assert tag.reasoning is not None
    assert "zel to" in tag.reasoning.lower() and "no type" in tag.reasoning.lower()
    assert tag.source_facts == ("txn1",)


# --------------------------------------------------------------------------- #
# What it must never do
# --------------------------------------------------------------------------- #
def test_a_definite_model_answer_is_never_overridden() -> None:
    """The model is asked first. A line reading "To" that the model judged money IN stays money in —
    the model saw the whole line and this rule sees two words of it."""
    tag = _money_in_tag(_txn("Transfer To Escrow Refundable Deposit"), _judged("in"))

    assert tag.value == "in"
    assert tag.produced_by is TagProducedBy.AI


def test_a_definite_out_is_also_left_alone() -> None:
    tag = _money_in_tag(_txn("Online Transfer From Savings"), _judged("out"))

    assert tag.value == "out" and tag.produced_by is TagProducedBy.AI


def test_a_reversed_line_stays_unknown() -> None:
    """ "Zelle payment from J Smith returned" is a different sentence: the preposition no longer says
    where the money ended up, so the honest answer is still the model's."""
    tag = _money_in_tag(_txn("Zelle Payment From J Smith Returned"), _judged("unknown"))

    assert tag.value == "unknown"


def test_a_line_with_no_directional_opening_stays_unknown() -> None:
    """THE EVAL CORPUS'S OWN ABSTENTION. `AMBIGUOUS LINE ITEM` is the only fixture stubbed unknown, and
    it must remain so — the calibration record cannot move under this change."""
    assert _money_in_tag(_txn("AMBIGUOUS LINE ITEM"), _judged("unknown")).value == "unknown"
    assert _money_in_tag(_txn("DEPOSIT ID NUMBER 56194"), _judged("unknown")).value == "unknown"


def test_a_mid_line_preposition_does_not_count() -> None:
    """Anchored at the START. "Check 1827 payable to A Vendor" is not a bank-printed transfer label,
    and reading prepositions anywhere in the line is how this becomes a guess."""
    assert (
        _money_in_tag(_txn("Check 1827 Payable To A Vendor"), _judged("unknown")).value == "unknown"
    )


def test_an_absent_description_stays_unknown() -> None:
    assert _money_in_tag(_txn(None), _judged("unknown")).value == "unknown"


def test_a_payee_whose_name_follows_transfer_is_not_a_direction() -> None:
    """bug-022 review — FROM THE REAL CORPUS, and the reason the table demands the preposition.

    Staging carries two lines reading "Transfer Ila Patel": a payee whose given name begins with the
    letters of a preposition. The table requires "transfer to " / "transfer from " with the trailing
    space, so these stay unknown — but a future prefix of bare "transfer " would read this person's
    name as a direction, and the mistake would be invisible because the line looks directional.
    """
    assert _money_in_tag(_txn("Transfer Ila Patel"), _judged("unknown")).value == "unknown"
    assert _money_in_tag(_txn("Transfer Format Fee"), _judged("unknown")).value == "unknown"


def test_the_eval_corpus_directional_keys_all_agree_with_the_table() -> None:
    """Corroboration from the labelled data rather than from intuition: every directional fixture in the
    eval corpus already carries a stubbed direction, and the table agrees with each one. If a future
    prefix disagreed with the corpus, this fails rather than quietly re-labelling calibrated data."""
    from app.verification.eval.cases import CASES

    for case in CASES:
        for fixture in case.txns:
            resolved = _money_in_tag(_txn(fixture.key), _judged(None))
            if resolved.produced_by is not TagProducedBy.DERIVED:
                continue  # no directional opening — nothing claimed about it
            assert resolved.value == fixture.is_money_in, (
                f"the table reads {fixture.key!r} as {resolved.value!r} while the calibrated corpus "
                f"labels it {fixture.is_money_in!r}"
            )
