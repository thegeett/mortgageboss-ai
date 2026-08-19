"""LP-572 — a liability's identity must not move when a fact ABOUT it changes.

A stated liability has no id in the snapshot: its subject id is a content hash over the four fields
MISMO projects. That makes the hash's input list load-bearing in a way that is easy to miss — add a
field to it and every liability on every file re-keys, so existing findings point at subjects that no
longer exist.

LP-568's `paid_off_at_closing` is exactly the kind of field that invites the mistake. It describes a
liability (does this obligation survive closing?) without identifying it, and a processor ticking the
box must not change WHICH debt it is. So the gathered-fields list is a superset of the identity list,
and this test is what keeps them from being re-merged.
"""

from __future__ import annotations

from uuid import uuid4

from app.verification.rule_engine.enumerators import (
    _MISMO_LIABILITY_FIELDS,
    _MISMO_LIABILITY_ID_FIELDS,
    liability_rows,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import MismoSection, Snapshot


def _snapshot(*, paid_off: str | None) -> Snapshot:
    facts = {
        "liability.1.type": Field.present("MortgageLoan", source=FieldSource.PARSED),
        "liability.1.monthly_payment": Field.present("3186.00", source=FieldSource.PARSED),
        "liability.1.unpaid_balance": Field.present("435012.22", source=FieldSource.PARSED),
        "liability.1.holder_name": Field.present("UNITED WHSLE MORT", source=FieldSource.PARSED),
    }
    if paid_off is not None:
        facts["liability.1.paid_off_at_closing"] = Field.present(
            paid_off, source=FieldSource.PARSED
        )
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        mismo=MismoSection(facts=facts),
    )


def test_flagging_a_payoff_does_not_re_key_the_liability() -> None:
    """THE INVARIANT. The same debt, before and after a processor marks it paid off at closing, is
    the same subject — otherwise applying the exclusion would orphan every finding about it."""
    before = liability_rows(_snapshot(paid_off=None))
    after = liability_rows(_snapshot(paid_off="True"))

    assert len(before) == len(after) == 1
    assert before[0].subject_id == after[0].subject_id


def test_the_identity_list_is_the_four_projected_fields() -> None:
    """Pinned as a literal, not derived from the other tuple, so a change has to be deliberate."""
    assert _MISMO_LIABILITY_ID_FIELDS == (
        "type",
        "monthly_payment",
        "unpaid_balance",
        "holder_name",
    )


def test_gathered_fields_are_a_superset_of_identity_fields() -> None:
    """The two lists must not be re-merged: gathering a field lets a parsed producer read it,
    hashing it decides what the subject IS. Every identity field must still be gathered."""
    assert set(_MISMO_LIABILITY_ID_FIELDS) < set(_MISMO_LIABILITY_FIELDS)
    assert "paid_off_at_closing" in _MISMO_LIABILITY_FIELDS
    assert "paid_off_at_closing" not in _MISMO_LIABILITY_ID_FIELDS


def test_the_flag_reaches_the_row_a_parsed_producer_reads() -> None:
    """Gathering it is the point — a producer must be able to see it on the raw fields."""
    (row,) = liability_rows(_snapshot(paid_off="True"))

    assert "paid_off_at_closing" in row.fields
