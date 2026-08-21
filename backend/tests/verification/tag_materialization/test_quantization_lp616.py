"""LP-616 — the divisions LP-615 missed, and the gates its rounding moved past.

LP-615 quantized the MONEY divisions that reach the snapshot and left the RATIO divisions alone, so
the failure it was written to eliminate — a fractional run the at-rest guard reads as an account
number, and refuses the whole snapshot over — stayed reachable on any file with an income shortfall.
Rounding also landed AFTER two fail-closed gates, turning a sub-cent figure into a confident zero.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.persistence import RawPiiAtRestError, _assert_no_raw_pii
from app.verification.tag_materialization.derived import (
    _CENTS,
    _UNKNOWN,
    _housing_insurance_monthly,
    _housing_taxes_monthly,
    _quantized,
)


def _persists(value: object) -> bool:
    """Whether a tag value of this shape survives the at-rest guard — the real question."""
    try:
        _assert_no_raw_pii(json.dumps({"tag": str(value)}))
    except RawPiiAtRestError:
        return False
    return True


# --------------------------------------------------------------------------------------------- #
# The ratios — the sites LP-615 missed
# --------------------------------------------------------------------------------------------- #
def test_an_income_shortfall_ratio_does_not_cost_the_file_its_snapshot() -> None:
    """`(5500 - 4000) / 5500` is 0.2727… to 28 digits, and the guard reads that as an account number.

    Not money, but the same code path to the same guard — which is why quantizing only the money
    divisions left the failure in place.
    """
    unrounded = (Decimal("5500") - Decimal("4000")) / Decimal("5500")
    assert not _persists(unrounded), "the fixture must reproduce the original failure"

    rounded = _quantized(unrounded, Decimal("0.000001"))
    assert rounded is not None
    assert _persists(rounded)


def test_a_ytd_pace_ratio_does_not_cost_the_file_its_snapshot() -> None:
    """The divisor is 30.4375, so this one essentially never terminates on ordinary inputs."""
    elapsed = Decimal(94) / Decimal("30.4375")
    ytd_monthly = Decimal("40000") / elapsed
    unrounded = (Decimal("13150") - ytd_monthly) / Decimal("13150")
    assert not _persists(unrounded), "the fixture must reproduce the original failure"

    rounded = _quantized(unrounded, Decimal("0.000001"))
    assert rounded is not None
    assert _persists(rounded)


def test_quantize_abstains_rather_than_crashing_the_run() -> None:
    """`Decimal.quantize` RAISES past the context's 28 digits — on exactly the input this defends
    against, a 30-digit account number mis-extracted into an amount field.

    Unguarded it crashes tag materialization and takes the whole verification run with it, where
    before the run finished and the guard refused the persist naming the offending path. A crash is
    not an improvement on a diagnosable refusal.
    """
    account_number_shaped = Decimal("123456789012345678901234567890")
    assert _quantized(account_number_shaped, _CENTS) is None


# --------------------------------------------------------------------------------------------- #
# The gates — rounding must not manufacture a confident zero
# --------------------------------------------------------------------------------------------- #
def _snapshot(docs: list[DocumentEntry]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        documents=DocumentsSection.present(docs),
        tags=TagsSection.present({}),
    )


def _doc(doc_type: str, field: str, value: str) -> DocumentEntry:
    return DocumentEntry(
        content_id="d1",
        document_type=doc_type,
        fields={field: Field.present(value, source=FieldSource.EXTRACTED)},
    )


@pytest.mark.parametrize(
    ("producer", "doc_type", "field"),
    [
        (_housing_insurance_monthly, "homeowners_insurance", "annual_premium"),
        (_housing_taxes_monthly, "property_tax_bill", "annual_tax_amount"),
    ],
)
def test_a_sub_cent_annual_figure_abstains_instead_of_reporting_zero(
    producer: object, doc_type: str, field: str
) -> None:
    """The non-positive gate used to read the ANNUAL figure, before rounding.

    A $0.05 annual premium passed it and then rounded to a monthly "0.00" — a confident zero, which
    both of these functions document as the thing they exist to prevent ("absent ≠ 0 … the exact
    false-green the DTI's gate exists to prevent"). The gate has to see the number the tag will carry.
    """
    value, reason = producer(_snapshot([_doc(doc_type, field, "0.05")]), "loan", None)  # type: ignore[operator]

    assert value == _UNKNOWN, f"0.05/yr rounded to a confident zero: {value!r}"
    assert "non-positive" in reason


@pytest.mark.parametrize(
    ("producer", "doc_type", "field", "expected"),
    [
        (_housing_insurance_monthly, "homeowners_insurance", "annual_premium", "104.17"),
        (_housing_taxes_monthly, "property_tax_bill", "annual_tax_amount", "104.17"),
    ],
)
def test_an_ordinary_annual_figure_still_produces_its_monthly(
    producer: object, doc_type: str, field: str, expected: str
) -> None:
    """The gate reordering must not cost the ordinary case."""
    value, _reason = producer(_snapshot([_doc(doc_type, field, "1250")]), "loan", None)  # type: ignore[operator]

    assert value == expected
    assert _persists(value)


def test_two_hoa_statements_a_cent_apart_still_abstain() -> None:
    """Rounding on the way INTO the conflict set made a fail-closed guard looser.

    Two HOA statements at 300.00 and 300.01 quarterly are two different figures, and this tag's job is
    to abstain when it cannot tell which applies. Both rounded to 100.00 and it reported agreement —
    a deliberate ambiguity guard relaxed as a side effect of a formatting fix. Rounding now happens on
    the way out, after the comparison.
    """
    from app.verification.tag_materialization.derived import _housing_hoa_monthly

    def _stmt(dues: str, cid: str) -> DocumentEntry:
        return DocumentEntry(
            content_id=cid,
            document_type="hoa_statement",
            fields={
                "dues_amount": Field.present(dues, source=FieldSource.EXTRACTED),
                "dues_frequency": Field.present("quarterly", source=FieldSource.EXTRACTED),
            },
        )

    value, reason = _housing_hoa_monthly(
        _snapshot([_stmt("300.00", "h1"), _stmt("300.01", "h2")]), "loan", None
    )

    assert value == _UNKNOWN, "a cent of disagreement is still a disagreement"
    assert "conflicting" in reason
