"""LP-596 — the 1003's real-estate-owned schedule, parsed and made visible to the engine.

WHAT WAS WRONG. MISMO has always carried ``OWNED_PROPERTY`` and the parser has always retained it —
in ``catch_all``, which the snapshot does not read. So the facts existed, were stored, were displayed,
and were invisible to every decision. Three live rules reported they could not determine things the
application states outright:

  * DT-6 / DT-8 ask whether a mortgage is the lien being refinanced or one on property the borrower
    retains. ``OwnedPropertyDispositionStatusType`` and ``OwnedPropertySubjectIndicator`` say.
  * AS-4 waives minimum reserves for a one-unit principal residence ONLY when there are no other
    financed properties (B3-4.1-01, 2%/4%/6% of aggregate UPB by count). Sizing that needs the
    schedule.

The real export carries five of these. That is the fixture every test here runs against.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal
from types import SimpleNamespace as ns
from uuid import uuid4

from app.mismo.parser import parse_mismo
from app.verification.snapshot.mismo_section import build_mismo_section

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures/mismo/MISMO16940192.xml"


def _parsed():
    return parse_mismo(_FIXTURE.read_bytes())


def test_the_real_export_yields_all_five_owned_properties() -> None:
    owned = _parsed().owned_properties
    assert len(owned) == 5


def test_each_block_carries_the_facts_the_rules_need() -> None:
    """Every field the blocked rules read, asserted on real values rather than a shape."""
    owned = _parsed().owned_properties

    assert {o.disposition_status for o in owned} == {"Retain"}
    # The five lien balances — these are what join an owned property to a stated liability.
    assert sorted(o.lien_upb for o in owned if o.lien_upb is not None) == [
        Decimal("311262.00"),
        Decimal("351804.00"),
        Decimal("405282.00"),
        Decimal("539618.00"),
        Decimal("582417.00"),
    ]
    # One is the borrower's principal residence — B3-4.1-01 EXCLUDES it from the reserves aggregate,
    # so AS-4 cannot size a requirement without this field.
    assert sum(1 for o in owned if o.current_usage_type == "PrimaryResidence") == 1
    assert sum(1 for o in owned if o.rental_income_gross is not None) == 2


def test_the_lien_upbs_match_the_stated_mortgage_liabilities() -> None:
    """The JOIN this ticket unlocks. The schedule and the liability list describe the same debts from
    two angles; matching them is how a rule learns which lien sits on which property — the question
    DT-8 currently answers from a checkbox alone."""
    parsed = _parsed()
    mortgage_balances = {
        liability.unpaid_balance
        for liability in parsed.liabilities
        if liability.liability_type == "MortgageLoan"
    }
    owned_upbs = {o.lien_upb for o in parsed.owned_properties}

    assert owned_upbs == mortgage_balances, (
        "the schedule's lien balances no longer line up with the stated mortgages — the join that "
        "identifies which property secures which debt has broken"
    )


def test_subject_indicator_is_read_but_is_false_on_every_block() -> None:
    """THE TRAP, PINNED. Every block says ``OwnedPropertySubjectIndicator=false`` — the subject
    property is described in its own section, not repeated in the schedule. A consumer that reads
    "no block is marked subject" as "this loan has no subject property" would be reading a default
    as a determination, exactly the mistake ``paid_off_at_closing`` was hardened against in LP-568.

    Only a True identifies the subject. This test exists so a future change that starts trusting the
    false has to argue with it.
    """
    owned = _parsed().owned_properties

    assert all(o.is_subject is False for o in owned)
    assert not any(o.is_subject for o in owned)


def test_the_address_inside_each_block_is_not_parsed() -> None:
    """Each OWNED_PROPERTY nests a full PROPERTY/ADDRESS — the borrower's other home. No rule asks
    for it, so it is deliberately left to the catch-all (display only) rather than pulled into a
    typed column that the snapshot, the readonly views and every log line would then have to scrub."""
    owned = _parsed().owned_properties

    fields = set(type(owned[0]).model_fields)
    assert not (fields & {"address_line", "city", "state", "postal_code", "address"})


def test_the_schedule_reaches_the_snapshot() -> None:
    """THE POINT OF THE TICKET. Parsing it changed nothing until it was projected into the snapshot —
    that is the step ``catch_all`` never had, and the reason the engine could not see any of this."""
    parsed = _parsed()
    rows = [ns(id=uuid4(), is_deleted=False, **o.model_dump()) for o in parsed.owned_properties]
    loan_file = ns(
        id=uuid4(),
        loan_program=None,
        loan_purpose=None,
        loan_amount=None,
        note_amount=None,
        note_rate_percent=None,
        lien_priority=None,
        amortization_type=None,
        amortization_months=None,
        application_received_date=None,
        total_mortgaged_properties=None,
        rate_set_date=None,
        seller_paid_closing_costs=None,
        refinance_type=None,
        status=None,
    )

    facts = build_mismo_section(
        loan_file=loan_file,  # type: ignore[arg-type]
        borrowers=[],
        property_=None,
        liabilities=[],
        assets=[],
        owned_properties=rows,  # type: ignore[arg-type]
        housing_expenses=[],
    )

    upbs = {facts[k].value for k in facts if k.endswith(".lien_upb")}
    assert upbs == {"405282.00", "582417.00", "311262.00", "539618.00", "351804.00"}
    assert {facts[k].value for k in facts if k.endswith(".disposition_status")} == {"Retain"}


def test_a_file_with_no_schedule_projects_nothing_rather_than_zeroes() -> None:
    """Absent is not zero (§8). A purchase with no REO must leave the keys OUT, so a rule reading
    them resolves couldnt_check rather than concluding the borrower owns nothing."""
    loan_file = ns(
        id=uuid4(),
        loan_program=None,
        loan_purpose=None,
        loan_amount=None,
        note_amount=None,
        note_rate_percent=None,
        lien_priority=None,
        amortization_type=None,
        amortization_months=None,
        application_received_date=None,
        total_mortgaged_properties=None,
        rate_set_date=None,
        seller_paid_closing_costs=None,
        refinance_type=None,
        status=None,
    )

    facts = build_mismo_section(
        loan_file=loan_file,  # type: ignore[arg-type]
        borrowers=[],
        property_=None,
        liabilities=[],
        assets=[],
        owned_properties=[],
        housing_expenses=[],
    )

    assert not [k for k in facts if k.startswith("owned_property.")]
