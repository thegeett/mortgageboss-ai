"""Parser hardening against MORE files (LP-57) — the heart of the consolidation.

LP-51..56 were validated against ONE real file. These tests feed the parser
**synthetic variants** of that file (FHA, a distinct second borrower, missing
sections, an unsupported mortgage type, a zero-income deal, HTML-wrapped) to
confirm the LP-51 tolerance claims hold against structural variation.

HONEST LIMITATION (see ``docs/tickets/LP-57.md``): these are derived from the one
real file, not additional real LOS exports. They prove tolerance to the specific
variations applied — not real-world variation a different LOS would produce. A
real FHA file and a real multi-borrower file are still needed to fully harden.
"""

from decimal import Decimal

import pytest
from app.mismo.parser import parse_mismo
from tests.mismo import synthetic


@pytest.fixture
def base() -> bytes:
    return synthetic.base_bytes()


# --------------------------------------------------------------------------- #
# FHA + mortgage-type tolerance (V1 = Conventional + FHA)
# --------------------------------------------------------------------------- #


def test_fha_variant_parses(base: bytes) -> None:
    result = parse_mismo(synthetic.fha_variant(base))
    assert result.loan is not None
    assert result.loan.mortgage_type == "FHA"
    # The rest still parses exactly (the variant changed only the mortgage type).
    assert result.loan.base_loan_amount == Decimal("1104000.00")
    assert result.parse_warnings == []


def test_unsupported_mortgage_type_tolerated(base: bytes) -> None:
    # VA is out of V1 scope — the parser reads it verbatim (mapping to None is the
    # importer's job); it must NOT crash or drop the rest of the loan.
    result = parse_mismo(synthetic.with_mortgage_type(base, "VA"))
    assert result.loan is not None and result.loan.mortgage_type == "VA"
    assert result.loan.base_loan_amount == Decimal("1104000.00")


# --------------------------------------------------------------------------- #
# Multi-borrower — correct per-borrower attribution (no cross-bleed)
# --------------------------------------------------------------------------- #


def test_multi_borrower_distinct_attribution(base: bytes) -> None:
    result = parse_mismo(synthetic.multi_borrower_variant(base))
    assert len(result.borrowers) == 2
    primary, co = result.borrowers
    assert primary.full_name == "Mahesh Chhotala" and co.full_name == "Asha Patel"
    # Each borrower keeps THEIR OWN income — the primary's amounts are unchanged,
    # the co-borrower's are the distinct synthetic values (no cross-attribution).
    assert [i.monthly_amount for i in primary.income_items] == [
        Decimal("7000.00"),
        Decimal("9400.00"),
    ]
    assert [i.monthly_amount for i in co.income_items] == [
        Decimal("3333.00"),
        Decimal("3333.00"),
    ]
    assert primary.classification == "Primary" and co.classification == "Secondary"
    assert primary.employers and co.employers  # each has its own employers


# --------------------------------------------------------------------------- #
# Missing optional sections — graceful (no crash; the rest survives)
# --------------------------------------------------------------------------- #


def test_missing_sections_degrade_gracefully(base: bytes) -> None:
    result = parse_mismo(synthetic.missing_sections_variant(base))
    # Dropped sections → empty, not an error.
    assert result.liabilities == []
    assert result.assets == []
    assert result.property is not None and result.property.estimated_value is None
    # The borrower and loan still parsed exactly.
    assert result.borrowers[0].full_name == "Mahesh Chhotala"
    assert result.loan is not None and result.loan.base_loan_amount == Decimal("1104000.00")
    # The needed-now property value is flagged.
    assert any("estimated value" in w for w in result.parse_warnings)


# --------------------------------------------------------------------------- #
# Zero-income deal — the LP-57 needed-now warning fires (non-blocking)
# --------------------------------------------------------------------------- #


def test_zero_income_deal_warns(base: bytes) -> None:
    result = parse_mismo(synthetic.zero_income_variant(base))
    assert all(b.income_items == [] for b in result.borrowers)
    assert any("no income" in w.lower() for w in result.parse_warnings)
    # Still a usable parse (file would still be created — non-blocking warning).
    assert result.loan is not None and result.borrowers


# --------------------------------------------------------------------------- #
# HTML-wrapped variant
# --------------------------------------------------------------------------- #


def test_html_wrapped_variant(base: bytes) -> None:
    result = parse_mismo(synthetic.html_wrapped(base))
    assert result.source_format == "html"
    assert result.borrowers[0].full_name == "Mahesh Chhotala"
    assert result.loan is not None and result.loan.base_loan_amount == Decimal("1104000.00")
