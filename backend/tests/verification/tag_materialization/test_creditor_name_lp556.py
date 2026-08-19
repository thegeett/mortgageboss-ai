"""LP-556 — `liab.creditor_name`: which debt a per-liability finding is about.

Four active rules enumerate per_liability (CR-1, CR-6, CR-8, CR-12) and every finding they produced
read "a debt on this file". On the real file CR-6 shipped FOUR identical rows — a processor could not
tell which account each concerned, nor that they were four different accounts rather than one repeated.

The AS-12 fix is the precedent: an identifying value the finding carries INLINE as provenance, so the
read path needs no snapshot. `liab.is_disputed` proves the shape for this subject family.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.services.rule_subject_label import resolve_subject_label
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.derived import liability_creditor_name


def _row(**fields: str):
    from app.verification.rule_engine.enumerators import LiabilityRow

    return LiabilityRow(
        subject_id="lia1",
        source="mismo_stated",
        fields={k: Field.present(v, source=FieldSource.EXTRACTED) for k, v in fields.items()},
        values=dict(fields),
        origin="liability.0",
        unresolved_reason=None,
        snapshot=Snapshot(
            loan_file_id=uuid4(), run_id=uuid4(), created_at=datetime(2026, 8, 18, tzinfo=UTC)
        ),
    )


def _name(**fields: str) -> str:
    snapshot = Snapshot(
        loan_file_id=uuid4(), run_id=uuid4(), created_at=datetime(2026, 8, 18, tzinfo=UTC)
    )
    return str(liability_creditor_name(snapshot, "lia1", _row(**fields))[0])


# --------------------------------------------------------------------------------------------- #
# BOTH SOURCES — the union is the point
# --------------------------------------------------------------------------------------------- #
def test_a_mismo_stated_liability_names_its_holder() -> None:
    """MISMO calls the column `holder_name`; a tradeline calls it `creditor_name`. Reading either
    directly would abstain on half the subjects — the ADR-376 lesson `liab.is_disputed` records — so
    this resolves the CANONICAL name through the alias map."""
    assert _name(holder_name="UNITED WHSLE MORT") == "UNITED WHSLE MORT"


def test_a_liability_with_no_holder_abstains_rather_than_inventing_one() -> None:
    """A MISMO row naming no holder is a real case the enumerator already flags; the label falls back
    to the generic rather than the tag fabricating a name."""
    assert _name(type="Revolving") == "unknown"


# --------------------------------------------------------------------------------------------- #
# THE PII PROPERTY — this tag exists to be RENDERED
# --------------------------------------------------------------------------------------------- #
def test_an_account_number_inside_the_creditor_field_is_scrubbed() -> None:
    """⚠️ A BUREAU PRINTS ACCOUNT NUMBERS INSIDE THE CREDITOR FIELD often enough that the liability
    CONTEXT builder routes every list value through the scrubber for exactly this reason. A tag whose
    whole purpose is to reach a processor's screen must not be the one place that skips it."""
    scrubbed = _name(holder_name="CHASE CARD 4111111111111111")

    assert "4111111111111111" not in scrubbed


# --------------------------------------------------------------------------------------------- #
# THE PAYOFF — four identical rows become four accounts
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("creditor", ["UNITED WHSLE MORT", "AMEX", "CITI", "DISCOVER BANK"])
def test_the_subject_label_names_the_account(creditor: str) -> None:
    """The four liabilities behind CR-6's four findings on the real file."""
    label = resolve_subject_label(
        "lia7a033a46ec70cc10", [{"tag_id": "liab.creditor_name", "value": creditor}]
    )

    assert label == creditor


def test_the_generic_survives_when_no_creditor_is_carried() -> None:
    """A rule that does not carry the tag, or a liability with no holder, still reads honestly — never
    the content-id hash the floor exists to keep away from a processor (LP-377-B)."""
    label = resolve_subject_label("lia7a033a46ec70cc10", [])

    assert label == "a debt on this file"
    assert "lia7a03" not in label
