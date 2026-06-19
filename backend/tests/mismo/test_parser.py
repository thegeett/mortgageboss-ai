"""Tests for the deterministic MISMO parser (LP-51).

Anchored on a REAL sample (``tests/fixtures/mismo/MISMO16940192.xml``): the
exact-value assertions prove the parse is deterministic and exact. Also covers
the catch-all (nothing dropped), multiple borrowers, tolerance (missing element →
None + warning), HTML-wrapped extraction, malformed / not-MISMO errors, and the
privacy rule (the SSN is never logged).
"""

import copy
from decimal import Decimal
from pathlib import Path

import pytest
import structlog
from app.mismo.parser import NS, MismoParseError, parse_mismo
from lxml import etree

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mismo" / "MISMO16940192.xml"


@pytest.fixture
def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


# --------------------------------------------------------------------------- #
# Real file — exact typed-core values (deterministic exactness)
# --------------------------------------------------------------------------- #


def test_real_file_borrower_exact(fixture_bytes: bytes) -> None:
    result = parse_mismo(fixture_bytes)
    assert result.source_format == "xml"
    assert result.parse_warnings == []  # the real file is complete
    assert len(result.borrowers) == 1
    b = result.borrowers[0]
    assert (b.first_name, b.last_name, b.full_name) == ("Mahesh", "Chhotala", "Mahesh Chhotala")
    assert b.birth_date.isoformat() == "1984-02-17"
    assert b.marital_status == "Married"
    assert b.dependent_count == 3
    assert b.classification == "Primary"
    assert b.email == "maheshmpc9@gmail.com"
    assert b.phone == "2562263263"
    assert b.citizenship == "PermanentResidentAlien"
    assert (b.city, b.state, b.postal_code) == ("Elmwood Park", "NJ", "07407")
    # SSN parsed exactly (9 digits) — value not asserted literally to keep PII out of the test.
    assert b.ssn is not None and len(b.ssn) == 9 and b.ssn.isdigit()


def test_real_file_income_employers_declarations(fixture_bytes: bytes) -> None:
    b = parse_mismo(fixture_bytes).borrowers[0]
    amounts = [i.monthly_amount for i in b.income_items]
    assert amounts == [Decimal("7000.00"), Decimal("9400.00")]
    assert all(i.income_type == "Base" and i.employment_income is True for i in b.income_items)
    assert b.employers == [
        "Swad Mania LLC",
        "CHHOTALA REALTY LLC",
        "Thermofisher Life Science - PPD Development LP",
    ]
    # 1003 declarations captured (feed Phase-3 cross-checks).
    assert b.declarations["BankruptcyIndicator"] == "false"
    assert b.declarations["IntentToOccupyType"] == "Yes"
    assert b.declarations["UndisclosedMortgageApplicationIndicator"] == "false"


def test_real_file_loan_exact(fixture_bytes: bytes) -> None:
    loan = parse_mismo(fixture_bytes).loan
    assert loan is not None
    assert loan.base_loan_amount == Decimal("1104000.00")
    assert loan.note_amount == Decimal("1104000.00")
    assert loan.note_rate_percent == Decimal("6.875")
    assert loan.loan_purpose == "Purchase"
    assert loan.mortgage_type == "Conventional"
    assert loan.lien_priority == "FirstLien"
    assert loan.amortization_type == "Fixed"
    assert loan.amortization_months == 360
    assert loan.application_received_date.isoformat() == "2026-06-02"


def test_real_file_property_exact(fixture_bytes: bytes) -> None:
    prop = parse_mismo(fixture_bytes).property
    assert prop is not None
    assert prop.address_line == "60 North Street"
    assert (prop.city, prop.state, prop.county) == ("Elmwood Park", "NJ", "Bergen County")
    assert prop.estimated_value == Decimal("1380000.00")
    assert prop.sales_contract_amount == Decimal("1380000.00")
    assert prop.usage_type == "PrimaryResidence"
    assert prop.attachment_type == "Detached"
    assert prop.construction_method == "SiteBuilt"
    assert prop.financed_unit_count == 1


def test_real_file_liabilities_and_assets_exact(fixture_bytes: bytes) -> None:
    result = parse_mismo(fixture_bytes)
    assert len(result.liabilities) == 10
    first = result.liabilities[0]
    assert first.liability_type == "MortgageLoan"
    assert first.monthly_payment == Decimal("4263.00")
    assert first.unpaid_balance == Decimal("582417.00")
    assert first.holder_name == "NR/SMS/CAL"

    assert len(result.assets) == 9
    asset = result.assets[0]
    assert asset.asset_type == "GiftOfCash"
    assert asset.value == Decimal("56000.00")


# --------------------------------------------------------------------------- #
# Catch-all — nothing dropped
# --------------------------------------------------------------------------- #


def test_catch_all_captures_non_core(fixture_bytes: bytes) -> None:
    result = parse_mismo(fixture_bytes)
    assert result.catch_all  # populated
    labels = {f.label for s in result.catch_all for f in s.fields}
    # Known non-core leaves are captured (not in the typed core).
    assert "FIPSCountyCode" in labels
    assert "CounselingConfirmationIndicator" in labels


def test_catch_all_excludes_ssn(fixture_bytes: bytes) -> None:
    result = parse_mismo(fixture_bytes)
    ssn = result.borrowers[0].ssn
    catch_values = {f.value for s in result.catch_all for f in s.fields}
    # The (sensitive) SSN is consumed by the typed core — never in the catch-all.
    assert ssn not in catch_values


# --------------------------------------------------------------------------- #
# Multiple borrowers
# --------------------------------------------------------------------------- #


def test_multiple_borrowers(fixture_bytes: bytes) -> None:
    # Duplicate the borrower PARTY to build a two-borrower deal.
    root = etree.fromstring(fixture_bytes)
    parties = root.find(".//m:PARTIES", NS)
    assert parties is not None
    borrower_party = next(
        p
        for p in parties.findall("m:PARTY", NS)
        if any(r.text == "Borrower" for r in p.findall(".//m:PartyRoleType", NS))
    )
    parties.append(copy.deepcopy(borrower_party))
    result = parse_mismo(etree.tostring(root))
    assert len(result.borrowers) == 2
    assert result.borrowers[0].full_name == result.borrowers[1].full_name == "Mahesh Chhotala"


# --------------------------------------------------------------------------- #
# Tolerance — missing optional element → None + warning, no crash
# --------------------------------------------------------------------------- #


def test_tolerance_missing_property_value(fixture_bytes: bytes) -> None:
    root = etree.fromstring(fixture_bytes)
    el = root.find(".//m:SUBJECT_PROPERTY//m:PropertyEstimatedValueAmount", NS)
    assert el is not None
    el.getparent().remove(el)
    result = parse_mismo(etree.tostring(root))
    assert result.property is not None
    assert result.property.estimated_value is None  # tolerated → None
    assert any("estimated value" in w for w in result.parse_warnings)
    # The rest still parsed fine (no crash).
    assert result.loan is not None and result.loan.base_loan_amount == Decimal("1104000.00")


# --------------------------------------------------------------------------- #
# HTML-wrapped XML
# --------------------------------------------------------------------------- #


def test_html_wrapped(fixture_bytes: bytes) -> None:
    wrapped = b"<html><body><pre>" + fixture_bytes + b"</pre></body></html>"
    result = parse_mismo(wrapped)
    assert result.source_format == "html"
    assert result.borrowers[0].full_name == "Mahesh Chhotala"
    assert result.loan is not None and result.loan.base_loan_amount == Decimal("1104000.00")


# --------------------------------------------------------------------------- #
# Validation / graceful errors
# --------------------------------------------------------------------------- #


def test_malformed_not_xml() -> None:
    with pytest.raises(MismoParseError):
        parse_mismo(b"this is not xml at all <<<>>>")


def test_valid_xml_not_mismo() -> None:
    with pytest.raises(MismoParseError) as exc:
        parse_mismo(b"<?xml version='1.0'?><foo><bar>x</bar></foo>")
    assert "MISMO" in str(exc.value)


def test_mismo_without_deal() -> None:
    with pytest.raises(MismoParseError):
        parse_mismo(
            b'<?xml version="1.0"?><MESSAGE xmlns="http://www.mismo.org/residential/2009/schemas"/>'
        )


# --------------------------------------------------------------------------- #
# Privacy — the SSN is never logged
# --------------------------------------------------------------------------- #


def test_ssn_never_logged(fixture_bytes: bytes) -> None:
    with structlog.testing.capture_logs() as logs:
        result = parse_mismo(fixture_bytes)
    ssn = result.borrowers[0].ssn
    assert ssn is not None
    blob = repr(logs)
    assert ssn not in blob  # SSN never logged
    assert "Mahesh" not in blob  # nor names
    assert "1104000.00" not in blob  # nor amounts
    # Metadata-only logging IS present.
    assert any(e.get("event") == "mismo_parsed" for e in logs)
