"""LP-568 — the export's own payoff answer, read but not over-trusted.

MISMO already carries the field this fix needs: `LiabilityPayoffStatusIndicator`, alongside
`LiabilityExclusionIndicator`. The parser was reading four elements per LIABILITY and dropping the
rest, so the answer was sitting in the source file and never reaching the DTI.

THE CATCH, and the reason a `false` is not read as "retained": the one real fixture carries
`LiabilityPayoffStatusIndicator=false` on ALL TEN of its liabilities — five of them mortgages. That
is a serializer default, not ten determinations. Treating it as authoritative would answer the
retained-or-paid-off question on every file, in the direction that removes debt from the DTI, on the
strength of a value nobody set. So only a TRUE is load-bearing; false and absent both mean
"not established" and keep the payment counted.
"""

from __future__ import annotations

from app.mismo.parser import parse_mismo
from lxml import etree
from tests.mismo import synthetic

NS = {"m": "http://www.mismo.org/residential/2009/schemas"}


def _with_payoff_flags(raw: bytes, *, payoff: str | None, exclusion: str | None) -> bytes:
    """Set (or remove) the two indicators on the FIRST liability only."""
    root = etree.fromstring(raw)
    detail = root.find(".//m:LIABILITIES/m:LIABILITY//m:LIABILITY_DETAIL", NS)
    assert detail is not None, "fixture has no LIABILITY_DETAIL to edit"
    for tag, value in (
        ("LiabilityPayoffStatusIndicator", payoff),
        ("LiabilityExclusionIndicator", exclusion),
    ):
        el = detail.find(f"m:{tag}", NS)
        if value is None:
            if el is not None:
                detail.remove(el)
            continue
        if el is None:
            el = etree.SubElement(detail, f"{{{NS['m']}}}{tag}")
        el.text = value
    return etree.tostring(root)


def test_the_real_fixture_says_false_on_every_liability() -> None:
    """The premise of the whole design, pinned. If a future fixture DOES carry a meaningful true,
    this fails and the 'false is a default' reasoning above must be revisited."""
    liabilities = parse_mismo(synthetic.base_bytes()).liabilities

    assert len(liabilities) == 10
    assert all(liability.payoff_status is False for liability in liabilities)
    assert all(liability.exclusion_indicator is False for liability in liabilities)


def test_a_true_payoff_indicator_is_read() -> None:
    raw = _with_payoff_flags(synthetic.base_bytes(), payoff="true", exclusion=None)

    assert parse_mismo(raw).liabilities[0].payoff_status is True


def test_a_true_exclusion_indicator_is_read() -> None:
    """Either indicator answers the question — an excluded liability does not belong in the ratio
    whatever the reason for excluding it."""
    raw = _with_payoff_flags(synthetic.base_bytes(), payoff="false", exclusion="true")

    liability = parse_mismo(raw).liabilities[0]
    assert liability.exclusion_indicator is True
    assert liability.payoff_status is False


def test_an_absent_indicator_is_none_not_false() -> None:
    """Absent ≠ known-false (§8). An export that omits the element has not said "retained"."""
    raw = _with_payoff_flags(synthetic.base_bytes(), payoff=None, exclusion=None)

    liability = parse_mismo(raw).liabilities[0]
    assert liability.payoff_status is None
    assert liability.exclusion_indicator is None


async def test_only_a_true_indicator_sets_the_stored_flag(db_session) -> None:
    """The import's translation, which is where the "false is not retained" rule is enforced.
    A false must reach the DB as NULL — if it landed as False, a later reader looking for
    `is not None` would treat ten serializer defaults as ten determinations."""
    from app.mismo.import_service import create_loan_file_from_mismo
    from app.models import Company, StatedLiability
    from sqlalchemy import select

    company = Company(name="Payoff", slug="payoff-import")
    db_session.add(company)
    await db_session.flush()

    raw = _with_payoff_flags(synthetic.base_bytes(), payoff="true", exclusion=None)
    loan_file = await create_loan_file_from_mismo(
        db_session, parsed=parse_mismo(raw), company_id=company.id, raw_content=raw
    )

    rows = (
        (
            await db_session.execute(
                select(StatedLiability).where(StatedLiability.loan_file_id == loan_file.id)
            )
        )
        .scalars()
        .all()
    )
    flagged = [r for r in rows if r.paid_off_at_closing is True]
    assert len(flagged) == 1
    assert flagged[0].payoff_source == "mismo_payoff"  # LP-569: WHICH indicator fired
    # The other nine carried `false` — they must be NULL, not False.
    assert all(r.paid_off_at_closing is None for r in rows if r not in flagged)


# --------------------------------------------------------------------------------------------- #
# LP-627 — is the stated payment already a PITIA?
# --------------------------------------------------------------------------------------------- #
def test_the_payment_includes_taxes_insurance_indicator_is_read() -> None:
    """DT-6 compares a mortgage statement's BILLED payment against the application's STATED payment.
    Whether the two are the same KIND of figure decides whether the comparison means anything: a
    P&I-only stated payment and a servicer's PITIA differ by exactly the escrow, which is not a
    discrepancy. The application has stated this all along, in `catch_all`, unread."""
    import pathlib

    from app.mismo.parser import parse_mismo

    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures/mismo/MISMO16940192.xml"
    parsed = parse_mismo(fixture.read_bytes())

    stated = [liab.payment_includes_taxes_insurance for liab in parsed.liabilities]
    assert stated, "the fixture states liabilities"
    assert any(value is not None for value in stated), (
        "the indicator is on every LIABILITY_DETAIL in the fixture — reading none of them means the "
        "XPath is wrong and the field is silently back in catch_all"
    )


def test_an_absent_pitia_indicator_is_none_not_false() -> None:
    """Tri-state, like the payoff pair beside it. None is "the export did not say", and reading it as
    False would assert the payment is P&I-only — turning an unstated fact into a claim that changes
    what a DTI comparison means."""
    from app.mismo.schema import ParsedLiability

    assert ParsedLiability().payment_includes_taxes_insurance is None
