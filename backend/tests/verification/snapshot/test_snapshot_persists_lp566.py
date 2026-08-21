"""LP-566 — the snapshot must actually persist. Proven per field, not assumed.

Staging had 22 completed runs and ZERO persisted snapshots: the at-rest PII guard refused every write,
and the call site logged only the exception CLASS, so the reason it was already computing went nowhere.

This test is the check that was missing. It feeds the identifier-shaped value each real field was found
carrying through the snapshot's own field builder, serializes, and runs the REAL guard. Anything that
would refuse a write fails here instead — on a machine, before a run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import pytest
from app.verification.snapshot.documents_section import build_document_fields
from app.verification.snapshot.persistence import (
    _LONG_DIGITS,
    RawPiiAtRestError,
    _assert_no_raw_pii,
)

# Every (document_type, field) a staging query found carrying an identifier-shaped value, with a
# stand-in value of the same shape. The point is the SHAPE — a 9+-digit run is what the guard refuses.
#
# LP-569 — THE VALUE'S TYPE IS PART OF THE SHAPE, and getting it wrong is how this file shipped
# green over a broken fix. `tax_year` is `TypedField[int]` parsed with `coerce_int`, so a leaked run
# reaches the snapshot as the INT 202520261234. The original case passed the STRING
# "2025 998877665544", which the extractor can never produce — and the scrub was gated on
# `isinstance(scalar, str)`, so the test exercised the one path that worked while production took
# the one that did not. Each value below is what the field actually carries after
# `model_dump(mode="json")`.
_REAL_FIELDS_CARRYING_DIGIT_RUNS = [
    ("property_tax_bill", "parcel_or_apn", "123456789012"),
    ("property_tax_bill", "tax_bill_or_account_number", "987654321098"),
    ("property_tax_bill", "tax_year", 202520261234),  # INT — an extraction defect, not PII
    ("form_1098", "tax_year", 202420251234),  # the same field on another of the nine doc types
    # This case asserts ONLY that the write is not refused. The ROUTING is wrong here and tracked
    # as LP-570 — a raw number goes through `pre_masked`, losing joinability. Do not read a passing
    # row as "the masking is correct".
    ("homeowners_insurance", "policy_number", "445566778899"),
    ("homeowners_insurance", "policy_status", "Active 112233445566"),  # free text, stays a str
    ("flood_insurance_policy", "policy_status", "Active 112233445566"),
    ("closing_disclosure", "loan_number", "556677889900"),
    ("form_1098", "account_number", "667788990011"),
    ("uscis_notice_of_action", "i94_number", "778899001122"),
    ("drivers_license", "id_number_masked", "889900112233"),
    ("bank_statement", "account_number_masked", "990011223344"),
]


@pytest.mark.parametrize(
    ("document_type", "field", "value"),
    _REAL_FIELDS_CARRYING_DIGIT_RUNS,
    ids=[f"{d}.{f}" for d, f, _ in _REAL_FIELDS_CARRYING_DIGIT_RUNS],
)
def test_no_real_field_refuses_the_write(document_type: str, field: str, value: object) -> None:
    """Each is either masked (`_PII_FIELDS`) or scrubbed (`_SCRUB_FREE_TEXT_FIELDS`). A field in
    neither reaches the guard raw and costs the WHOLE loan file its snapshot — every tag, every
    calculation, the DTI and LTV inputs — which is why this is asserted per field."""
    fields = build_document_fields(
        {field: {"value": value, "confidence": 0.9}}, document_type, loan_file_id=uuid4()
    )

    _assert_no_raw_pii(json.dumps({k: v.model_dump(mode="json") for k, v in fields.items()}))


def test_the_guard_still_refuses_something_it_should() -> None:
    """The mirror. A test that only proves things pass would also pass with the guard deleted, and the
    guard is why the read-only query path can promise raw identifiers never come back."""
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"borrower": {"value": "123-45-6789"}}))


def test_a_nested_structure_never_becomes_a_field() -> None:
    """`transactions`, `additional_accounts` and `additional_sections` all carry identifier-shaped
    values in the real extractions, and all three are nested. `_scalar` returns None for those, so they
    never reach the snapshot's typed fields — which is why they need no masking entry and why adding
    one would have been cargo-culting a fix onto a path the guard never sees."""
    fields = build_document_fields(
        {"transactions": [{"description": "ACH 123456789012"}]},
        "bank_statement",
        loan_file_id=uuid4(),
    )

    assert "transactions" not in fields


def test_a_clean_year_keeps_its_integer_type() -> None:
    """The scrub must only bite when something actually leaked. A real tax_year of 2025 has no
    9+-digit run, so it stays the INT 2025 — stringifying every scrub-listed field would quietly
    change the type of a value the rules read."""
    fields = build_document_fields(
        {"tax_year": {"value": 2025, "confidence": 0.9}}, "property_tax_bill", loan_file_id=uuid4()
    )

    assert fields["tax_year"].value == 2025


def test_every_declaring_doc_type_is_registered() -> None:
    """CLOSE THE CLASS. `tax_year` is declared by nine extractors and `policy_status` by four; a
    defect on any of them costs the whole file its snapshot. This fails when a new extractor adds
    one without registering it, which is the only way the list stays true.

    It covers these two field NAMES, not leak-prone fields in general — a genuinely new one still
    has to be noticed the hard way.
    """
    import re
    from pathlib import Path

    from app.ai.extraction import EXTRACTORS
    from app.verification.snapshot.documents_section import _SCRUB_FREE_TEXT_FIELDS

    extraction_dir = Path(EXTRACTORS["w2"].__module__.replace(".", "/")).parent
    root = Path(__file__).resolve().parents[3] / extraction_dir
    declared: dict[str, set[str]] = {}
    for path in root.glob("*.py"):
        found = set(re.findall(r"^\s+(tax_year|policy_status): TypedField", path.read_text(), re.M))
        if found:
            declared[path.stem] = found

    # Module stem → registry slug, for the one place they differ.
    slug_of = {"form_1099": "1099"}
    missing = sorted(
        f"{slug_of.get(stem, stem)}.{field}"
        for stem, fields in declared.items()
        for field in fields
        if (slug := slug_of.get(stem, stem)) in EXTRACTORS
        and field not in _SCRUB_FREE_TEXT_FIELDS.get(slug, frozenset())
    )
    assert not missing, (
        "These document types declare a field known to carry leaked identifier runs but are not in "
        "_SCRUB_FREE_TEXT_FIELDS. Each one can refuse an entire loan file's snapshot:\n  "
        + "\n  ".join(missing)
    )


# --------------------------------------------------------------------------- #
# LP-615 — THE SECOND WAY TO LOSE A SNAPSHOT: unquantized arithmetic.
#
# Everything above is about an identifier-shaped value arriving in an EXTRACTED FIELD. This class is
# different and the file did not cover it: a value the snapshot COMPUTES ITSELF. `Decimal(1250) /
# Decimal(12)` is 104.1666666666666666666666667, and `_LONG_DIGITS` matches `\b\d{9,}\b(?!\.\d)` —
# the lookahead exempts the INTEGER part of a decimal and nothing else, so a 25-digit FRACTION reads
# as an unmasked account number and the whole write is refused.
#
# That is not hypothetical. On 2026-08-21 LF-3CVT took a homeowners binder with a $1,250 annual
# premium; the 14:07 run computed every finding, then stored no snapshot, naming five paths — the
# insurance tag's value AND its reasoning string, the DTI's insurance breakdown line, and the
# housing_payment and total_monthly_obligations it flowed into.
#
# The property-tax sibling escaped only by luck: 5282.58 / 12 terminates at 440.215. A $5,000 bill
# does not. Every money division that reaches the snapshot is now quantized to cents, and these are
# the divisions and the real premiums that prove it.
# --------------------------------------------------------------------------- #
_MONEY_DIVISIONS_REACHING_THE_SNAPSHOT = [
    # (label, annual-or-period amount, divisor) — the real LF-3CVT figures plus the near-misses.
    ("homeowners insurance (LF-3CVT)", Decimal("1250"), 12),
    ("property taxes (LF-3CVT)", Decimal("5282.58"), 12),
    ("property taxes, a bill that does not terminate", Decimal("5000"), 12),
    ("HOA dues, quarterly", Decimal("100"), 3),
    ("HOA dues, semiannual", Decimal("700"), 6),
]


@pytest.mark.parametrize(("label", "amount", "divisor"), _MONEY_DIVISIONS_REACHING_THE_SNAPSHOT)
def test_a_money_division_quantized_to_cents_never_refuses_the_write(
    label: str, amount: Decimal, divisor: int
) -> None:
    quantized = (amount / Decimal(divisor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Serialized the way the snapshot carries it: a string value AND inside a reasoning sentence,
    # because the insurance tag leaked through BOTH and fixing only the value would still refuse.
    payload = json.dumps({"value": str(quantized), "reasoning": f"monthly {quantized} ({label})"})
    _assert_no_raw_pii(payload)  # must not raise


@pytest.mark.parametrize(("label", "amount", "divisor"), _MONEY_DIVISIONS_REACHING_THE_SNAPSHOT)
def test_the_same_division_unquantized_is_what_the_guard_refuses(
    label: str, amount: Decimal, divisor: int
) -> None:
    """The other half of the proof: without the quantize these refuse — except the one that
    terminates, which is exactly why the bug hid behind property taxes for a day."""
    raw = amount / Decimal(divisor)
    if not _LONG_DIGITS.search(
        str(raw)
    ):  # 5282.58 / 12 = 440.215 — a short fraction, never at risk
        pytest.skip(f"{label} has no 9+ digit run unrounded; it could not have tripped the guard")
    with pytest.raises(RawPiiAtRestError):
        _assert_no_raw_pii(json.dumps({"value": str(raw)}))


def test_the_producers_and_the_dti_round_a_premium_the_same_way() -> None:
    """The tags are documented as agreeing-or-abstaining and NEVER LOOSER than the DTI, which
    computes the same monthly figure from the same extracted field. Rounding one side but not the
    other would break that by a fraction of a cent, so both are pinned to one expected value.

    LP-616 — CALLS THE REAL PRODUCER. This test used to recompute both sides inline with literal
    `quantize` expressions, so it asserted `Decimal("0.01") == _CENTS` and nothing about the code it
    names: deleting the quantize from `_housing_insurance_monthly`, or switching it to ROUND_DOWN,
    left it passing. A parity test that does not call either side pins nothing.
    """
    from app.services.dti import _CENTS
    from app.verification.snapshot.fields import Field, FieldSource
    from app.verification.snapshot.model import (
        DocumentEntry,
        DocumentsSection,
        Snapshot,
        TagsSection,
    )
    from app.verification.tag_materialization.derived import _housing_insurance_monthly

    annual = Decimal("1250")
    binder = DocumentEntry(
        content_id="ins1",
        document_type="homeowners_insurance",
        fields={"annual_premium": Field.present(str(annual), source=FieldSource.EXTRACTED)},
    )
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 17, tzinfo=UTC),
        documents=DocumentsSection.present([binder]),
        tags=TagsSection.present({}),
    )

    tag_value, _reason = _housing_insurance_monthly(snapshot, "loan", None)
    dti_side = (annual / Decimal(12)).quantize(_CENTS, rounding=ROUND_HALF_UP)

    assert Decimal(str(tag_value)) == dti_side == Decimal("104.17")
    # And the tag's own string carries no long fractional run — the thing the guard refuses.
    assert not _LONG_DIGITS.search(str(tag_value))
