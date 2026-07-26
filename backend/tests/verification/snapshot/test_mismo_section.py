"""MISMO section assembler (LP-205) — stable keys, PII routing, absent≠empty.

Uses in-memory (transient) ORM objects — no DB, no session.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app.models.borrower import Borrower
from app.models.lender import LoanProgram
from app.models.loan_file import LoanFile, LoanPurpose
from app.models.property import OccupancyType, Property, PropertyType
from app.models.stated_financials import (
    StatedAsset,
    StatedEmployer,
    StatedIncomeItem,
    StatedLiability,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.mismo_section import _scalar, build_mismo_section
from app.verification.snapshot.pii import PiiField

_RAW_SSN = "123-45-6789"


def _uuid(n: int) -> UUID:
    """A deterministic UUID so id-based ordering in tests is predictable."""
    return UUID(int=n)


def _loan_file() -> LoanFile:
    lf = LoanFile()
    lf.id = uuid4()
    lf.loan_program = LoanProgram.CONVENTIONAL
    lf.loan_purpose = LoanPurpose.PURCHASE
    lf.loan_amount = Decimal("1160000.00")
    lf.note_rate_percent = Decimal("6.1250")
    lf.amortization_months = 360
    return lf


def _borrower(pos: int, first: str, last: str, *, ssn: str | None = None, bid: int = 0) -> Borrower:
    b = Borrower()
    b.id = _uuid(bid or pos)
    b.borrower_position = pos
    b.first_name = first
    b.last_name = last
    b.is_primary = pos == 1
    b.ssn = ssn
    return b


def _income(amount: Decimal | None, itype: str, *, iid: int) -> StatedIncomeItem:
    it = StatedIncomeItem()
    it.id = _uuid(iid)
    it.monthly_amount = amount
    it.income_type = itype
    it.employment_income = True
    return it


def _build(**kw: object) -> dict[str, object]:
    """build_mismo_section over a small sample, defaulting the collections."""
    lf = kw.get("loan_file") or _loan_file()
    return build_mismo_section(
        loan_file=lf,  # type: ignore[arg-type]
        borrowers=kw.get("borrowers", []),  # type: ignore[arg-type]
        property_=kw.get("property_"),  # type: ignore[arg-type]
        liabilities=kw.get("liabilities", []),  # type: ignore[arg-type]
        assets=kw.get("assets", []),  # type: ignore[arg-type]
    )


def _full_sample() -> tuple[LoanFile, dict[str, object]]:
    lf = _loan_file()
    b1 = _borrower(1, "Akash", "Patel", ssn=_RAW_SSN, bid=10)
    b1.stated_income_items = [
        _income(Decimal("6000.00"), "Base", iid=2),
        _income(Decimal("500.00"), "Bonus", iid=1),
    ]
    b1.stated_employers = [_e("Wells Fargo", eid=1)]
    b2 = _borrower(2, "Priya", "Patel", bid=20)
    prop = Property()
    prop.id = uuid4()
    prop.city = "Charlotte"
    prop.state = "NC"
    prop.property_type = PropertyType.SINGLE_FAMILY
    prop.occupancy_type = OccupancyType.PRIMARY_RESIDENCE
    prop.estimated_value = Decimal("1200000.00")
    liabs = [
        _liab("Installment", Decimal("300"), "Chase", lid=5),
        _liab("Revolving", Decimal("50"), "Amex", lid=1),
    ]
    assets = [_asset("CheckingAccount", Decimal("40000"), "Wells Fargo", aid=3)]
    section = build_mismo_section(
        loan_file=lf, borrowers=[b2, b1], property_=prop, liabilities=liabs, assets=assets
    )
    return lf, section


def _e(name: str, *, eid: int) -> StatedEmployer:
    e = StatedEmployer()
    e.id = _uuid(eid)
    e.employer_name = name
    e.is_current = True
    return e


def _liab(ltype: str, pmt: Decimal, holder: str | None, *, lid: int) -> StatedLiability:
    lb = StatedLiability()
    lb.id = _uuid(lid)
    lb.liability_type = ltype
    lb.monthly_payment = pmt
    lb.holder_name = holder
    return lb


def _asset(atype: str, value: Decimal, holder: str, *, aid: int) -> StatedAsset:
    a = StatedAsset()
    a.id = _uuid(aid)
    a.asset_type = atype
    a.value = value
    a.holder_name = holder
    return a


# --------------------------------------------------------------------------- #
# Keys at the expected stable dotted paths
# --------------------------------------------------------------------------- #


def test_expected_keys_present_at_dotted_paths() -> None:
    _lf, section = _full_sample()
    for key in (
        "loan.amount",
        "loan.program",
        "property.city",
        "property.estimated_value",
        "borrower.1.first_name",
        "borrower.1.income.1.monthly_amount",
        "borrower.1.employer.1.name",
        "borrower.2.first_name",
        "liability.1.monthly_payment",
        "asset.1.value",
    ):
        assert key in section, key
    # money stringified exactly; enums as their value
    assert section["loan.amount"].value == "1160000.00"
    assert section["loan.program"].value == "conventional"
    assert section["borrower.1.is_primary"].value is True


def test_borrower_ordered_by_position_not_input_order() -> None:
    # _full_sample passes [b2, b1]; the primary (position 1) must be borrower.1.
    _lf, section = _full_sample()
    assert section["borrower.1.first_name"].value == "Akash"
    assert section["borrower.2.first_name"].value == "Priya"


def test_nested_collections_ordered_by_stable_id() -> None:
    # income items have ids 2 (Base) and 1 (Bonus); id-order → income.1 = Bonus (id 1).
    _lf, section = _full_sample()
    assert section["borrower.1.income.1.income_type"].value == "Bonus"
    assert section["borrower.1.income.2.income_type"].value == "Base"


# --------------------------------------------------------------------------- #
# PII
# --------------------------------------------------------------------------- #


def test_ssn_is_a_masked_piifield_with_no_raw_value() -> None:
    _lf, section = _full_sample()
    ssn = section["borrower.1.ssn"]
    assert isinstance(ssn, PiiField)
    assert ssn.display == "***-**-6789"
    assert ssn.match_hash is not None and ssn.match_hash.startswith("v1:")
    # The raw SSN appears nowhere in the produced section.
    blob = repr({k: v.model_dump() for k, v in section.items()})
    assert "123456789" not in blob
    assert _RAW_SSN not in blob


# --------------------------------------------------------------------------- #
# source=parsed, confidence=null everywhere (nothing fabricated)
# --------------------------------------------------------------------------- #


def test_every_field_is_parsed_with_null_confidence() -> None:
    _lf, section = _full_sample()
    for value in section.values():
        assert value.source is FieldSource.PARSED
        assert value.confidence is None  # deterministic parse → never a fabricated number


# --------------------------------------------------------------------------- #
# Absent ≠ empty
# --------------------------------------------------------------------------- #


def test_missing_subentity_is_absent_not_present_null() -> None:
    """A borrower with one income item → income.2.* keys ABSENT (omitted)."""
    lf = _loan_file()
    b = _borrower(1, "Akash", "Patel", bid=1)
    b.stated_income_items = [_income(Decimal("6000"), "Base", iid=1)]
    section = _build(loan_file=lf, borrowers=[b])
    assert "borrower.1.income.1.monthly_amount" in section
    assert "borrower.1.income.2.monthly_amount" not in section  # absent, not present-null
    # A borrower with NO income items → no income keys, no error.
    b2 = _borrower(2, "Priya", "Patel", bid=2)
    section2 = _build(loan_file=lf, borrowers=[b2])
    assert not any(k.startswith("borrower.1.income") for k in section2 if "borrower.1" in k)


def test_null_is_absent_but_empty_string_is_present_empty() -> None:
    """A NULL column is omitted (absent); a genuine empty string is present-empty."""
    lf = _loan_file()
    blank = _liab("Installment", Decimal("100"), "", lid=1)  # holder = "" (present-empty)
    null_holder = _liab("Revolving", Decimal("50"), None, lid=2)  # holder NULL (absent)
    section = _build(loan_file=lf, liabilities=[blank, null_holder])
    assert section["liability.1.holder_name"] == Field.present("", source=FieldSource.PARSED)
    assert section["liability.1.holder_name"].value == ""  # present-empty
    assert "liability.2.holder_name" not in section  # absent (omitted)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_same_input_produces_identical_keys() -> None:
    _lf1, a = _full_sample()
    _lf2, b = _full_sample()
    assert set(a) == set(b)  # deterministic key set, not reshuffled


def test_empty_loan_file_yields_only_present_loan_terms() -> None:
    """No borrowers/property/liabilities/assets → just the non-null loan terms, no error."""
    lf = _loan_file()
    section = _build(loan_file=lf)
    assert section  # loan.* present
    assert all(k.startswith("loan.") for k in section)


# --------------------------------------------------------------------------- #
# Soft-delete filtering (uniform in build, not just income/employers)
# --------------------------------------------------------------------------- #


def test_build_filters_soft_deleted_borrowers_liabilities_and_assets() -> None:
    """build_mismo_section is pure/public — it must drop soft-deleted rows itself."""
    lf = _loan_file()
    live = _borrower(1, "Akash", "Patel", bid=1)
    gone = _borrower(2, "Ghost", "Patel", bid=2)
    gone.deleted_at = datetime(2026, 7, 9, tzinfo=UTC)
    live_liab = _liab("Installment", Decimal("300"), "Chase", lid=1)
    gone_liab = _liab("Revolving", Decimal("50"), "Amex", lid=2)
    gone_liab.deleted_at = datetime(2026, 7, 9, tzinfo=UTC)
    live_asset = _asset("CheckingAccount", Decimal("40000"), "Wells Fargo", aid=1)
    gone_asset = _asset("Savings", Decimal("10000"), "Chase", aid=2)
    gone_asset.deleted_at = datetime(2026, 7, 9, tzinfo=UTC)

    section = _build(
        loan_file=lf,
        borrowers=[live, gone],
        liabilities=[live_liab, gone_liab],
        assets=[live_asset, gone_asset],
    )
    assert section["borrower.1.first_name"].value == "Akash"
    assert not any(k.startswith("borrower.2.") for k in section)  # 'Ghost' filtered
    assert section["liability.1.holder_name"].value == "Chase"
    assert not any(k.startswith("liability.2.") for k in section)
    assert section["asset.1.holder_name"].value == "Wells Fargo"
    assert not any(k.startswith("asset.2.") for k in section)


# --------------------------------------------------------------------------- #
# PII absent ≠ empty; unhandled types; malformed declarations
# --------------------------------------------------------------------------- #


def test_present_empty_ssn_is_masked_placeholder_null_ssn_is_absent() -> None:
    lf = _loan_file()
    blank = _borrower(1, "Akash", "Patel", ssn="", bid=1)  # present-but-empty SSN
    null_ssn = _borrower(2, "Priya", "Patel", ssn=None, bid=2)  # NULL SSN → absent
    section = _build(loan_file=lf, borrowers=[blank, null_ssn])

    ssn = section["borrower.1.ssn"]
    assert isinstance(ssn, PiiField)
    assert ssn.display == "***-**-****"  # present, masked placeholder
    assert ssn.match_hash is None  # empty → non-matchable, not fabricated
    assert "borrower.2.ssn" not in section  # NULL SSN omitted (absent)


def test_scalar_raises_on_an_unhandled_type_never_fabricates_a_repr() -> None:
    with pytest.raises(TypeError):
        _scalar(object())


def test_non_dict_declarations_degrade_to_no_declarations_no_crash() -> None:
    lf = _loan_file()
    b = _borrower(1, "Akash", "Patel", bid=1)
    b.declarations = ["not", "a", "dict"]  # type: ignore[assignment]  # malformed JSON shape
    section = _build(loan_file=lf, borrowers=[b])  # must not raise
    assert not any(".declaration." in k for k in section)
