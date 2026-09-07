"""LP-443 — the list-capture bridge, proven end to end.

The chain the prompt→extractor→snapshot had a hole in the middle: the prompt asked for BARE rows, the
generated extractor had no field to store them, and the snapshot reader expected {value}-wrapped rows. This
pins the bridge: (1) the snapshot reads BARE rows (the shipping bank_statement.transactions shape) with an
honest None confidence; (2) bank_statement's transactions land in entry.lists AND coexist with the legacy
entry.transactions (AS-1's input, byte-unchanged); (3) the generator emits the capture + a count cross-check
that downgrades SUCCEEDED→PARTIAL when the model drops rows it declared. Nothing is wired beyond bank_statement.
"""

from __future__ import annotations

import json
from uuid import UUID

from app.ai.extraction.appraisal import _parse_appraisal_json
from app.ai.extraction.bank_statement import _parse_bank_statement_json
from app.models.extraction import ExtractionStatus
from app.verification.snapshot import documents_section as ds
from app.verification.snapshot.fields import FieldSource

# bug-010 — the per-file salt a masked row field is hashed with. Fixed, so a rebuilt row is
# byte-identical run to run.
_LF = UUID("00000000-0000-0000-0000-00000000f1e0")

_BANK_JSON = json.dumps(
    {
        "typed_core": {
            "account_holder_name": {"value": "J. Rivera", "page": 1, "snippet": "J. Rivera"},
            "ending_balance": {"value": "8450.00", "page": 1, "snippet": "bal"},
        },
        "transactions": [
            {
                "date": "2026-05-02",
                "description": "PAYROLL ACCT 123456789 DEP",
                "amount": "5000.00",
                "transaction_type": "deposit",
                "running_balance": "8450.00",
                "page": 2,
                "snippet": "PAYROLL",
            },
            {
                "date": "2026-05-11",
                "description": "RENT",
                "amount": "1800.00",
                "transaction_type": "withdrawal",
                "running_balance": "6650.00",
                "page": 2,
                "snippet": "RENT",
            },
        ],
        "confidence": 0.94,
        "reasoning": "checking statement",
    }
)


def _bank_extracted() -> dict:
    """A real bank_statement extraction, dumped exactly as the pipeline persists extracted_data."""
    result = _parse_bank_statement_json(_BANK_JSON)
    assert result is not None
    return result.data.model_dump(mode="json")


# --------------------------------------------------------------------------- #
# The bridge: bare transaction rows land in entry.lists (was 0 before LP-443)
# --------------------------------------------------------------------------- #
def test_bank_statement_transactions_land_in_generic_lists() -> None:
    extracted = _bank_extracted()
    drafts = ds.build_list_rows(
        extracted, "bank_statement", loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0")
    )
    rows = ds.finalize_lists(drafts, document_content_id="docBANK")["transactions"]
    assert len(rows) == 2  # both rows captured — the hole is closed
    r0 = rows[0].fields
    assert r0["date"].value == "2026-05-02"
    assert r0["amount"].value == "5000.00"
    assert r0["amount"].source is FieldSource.EXTRACTED
    assert r0["amount"].confidence is None  # bare row → honest None (D4), never fabricated
    assert r0["direction"].value == "credit"  # derived (deposit → credit)
    assert "[redacted]" in r0["description"].value and "123456789" not in r0["description"].value
    assert rows[0].row_id is not None and rows[0].row_id.startswith("lst")  # stable id


def test_bare_row_field_confidence_is_none() -> None:
    # The bridge NEVER fabricates a per-field confidence for a bare row.
    f = ds._list_field("5000.00")
    assert f.value == "5000.00" and f.confidence is None and f.source is FieldSource.EXTRACTED
    assert ds._list_field(None).absent is True


# --------------------------------------------------------------------------- #
# Coexistence: the legacy transactions path is byte-unchanged (feeds live AS-1)
# --------------------------------------------------------------------------- #
def test_legacy_transactions_coexist_unchanged() -> None:
    extracted = _bank_extracted()
    field_sets = ds.transaction_field_sets(
        extracted, "bank_statement", loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0")
    )
    assert field_sets is not None and len(field_sets) == 2
    txns = ds.build_transactions(field_sets, document_content_id="docBANK")
    assert txns is not None and len(txns) == 2
    # Same rows, same derived direction as the generic list — belt-and-braces, no migration.
    assert txns[0].direction.value == "credit" and txns[1].direction.value == "debit"


def test_bank_statement_list_is_wired() -> None:
    # bank_statement was the Phase-A proof; Phase B wired the generated list-bearing batch alongside it.
    # LP-461 added additional_accounts (combined-statement recovery) as a SECOND wired list.
    assert "bank_statement" in ds._LIST_SPECS
    assert ds._LIST_SPECS["bank_statement"] == (
        ds._TRANSACTIONS_LIST,
        ds._BANK_STATEMENT__ADDITIONAL_ACCOUNTS_LIST,
    )


# --------------------------------------------------------------------------- #
# The generator's count cross-check (proven on the regenerated appraisal module)
# --------------------------------------------------------------------------- #
def _appraisal(count: int, n_rows: int) -> ExtractionStatus:
    rows = [
        {"comp_number": i, "address": f"{i} Oak", "sale_price": "440000", "page": 4, "snippet": "c"}
        for i in range(1, n_rows + 1)
    ]
    payload = {
        "typed_core": {
            "appraised_value": {"value": "450000", "page": 1, "snippet": "v"},
            "comparable_count": {"value": count, "page": 1, "snippet": "n"},
        },
        "comparable_sales": rows,
        "confidence": 0.9,
        "reasoning": "x",
    }
    result = _parse_appraisal_json(json.dumps(payload))
    assert result is not None
    return result.status


def test_count_crosscheck_downgrades_to_partial_on_mismatch() -> None:
    # The model declared 3 comparables but returned 2 → rows dropped without the API truncating → PARTIAL.
    assert _appraisal(count=3, n_rows=2) is ExtractionStatus.PARTIAL


def test_count_crosscheck_passes_when_count_matches() -> None:
    assert _appraisal(count=2, n_rows=2) is ExtractionStatus.SUCCEEDED


def test_appraisal_captures_list_rows() -> None:
    # The generated appraisal module now HAS a capture field (the extractor-side half of the bridge).
    payload = {
        "typed_core": {"appraised_value": {"value": "450000", "page": 1, "snippet": "v"}},
        "comparable_sales": [
            {
                "comp_number": 1,
                "address": "1 Oak",
                "sale_price": "440000",
                "page": 4,
                "snippet": "c",
            }
        ],
        "confidence": 0.9,
        "reasoning": "x",
    }
    result = _parse_appraisal_json(json.dumps(payload))
    assert result is not None
    assert len(result.data.comparable_sales) == 1
    # Serializes to bare JSON scalars — the shape the snapshot reads.
    dumped = result.data.model_dump(mode="json")["comparable_sales"][0]
    assert dumped["sale_price"] == "440000" and dumped["comp_number"] == 1


def test_reserved_source_field_is_never_surfaced() -> None:
    # LP-446 review: 27 specs mistakenly declared a `source` row field (the reserved per-row provenance
    # key). The snapshot must NEVER surface it as a data Field, regardless of the ListSpec declaration —
    # else every such list carries a junk `source` Field holding the provenance value.
    spec = ds.ListSpec(name="probe", fields=("amount", "source"))
    fields = ds._list_row_fields(
        {"amount": "100.00", "source": "junk-or-provenance"}, spec, loan_file_id=_LF
    )
    assert "amount" in fields and fields["amount"].value == "100.00"
    assert "source" not in fields  # reserved key skipped
    # And on a real source-bearing shipping list (security_positions), no `source` Field surfaces.
    real = ds._list_row_fields(
        {"description": "VANGUARD 500", "market_value": "1000", "source": "x"},
        ds._SECURITY_POSITIONS_LIST,
        loan_file_id=_LF,
    )
    assert "source" not in real and real["description"].value == "VANGUARD 500"


def test_list_row_pii_has_a_redact_backstop() -> None:
    # LP-443 review: list-row PII is not _PII_FIELDS-routed, so a model masking failure would persist a
    # full account number / TIN. Every list with a PII-shaped row field declares it in `redact`, so the
    # 9+-digit scrub redacts a leaked full number while leaving a genuinely-masked value untouched.
    import re

    pat = re.compile(
        r"(account_number|loan_number|card_number|_ssn|_tin\b|tin_masked|_ein|passport|"
        r"visa_number|uscis|a_number|_last4|number_masked)",
        re.I,
    )
    unguarded = {
        f"{dt}.{s.name}.{f}"
        for dt, specs in ds._LIST_SPECS.items()
        for s in specs
        for f in s.fields
        if pat.search(f) and f not in s.redact
    }
    assert unguarded == set(), f"list-row PII fields with no redact backstop: {unguarded}"

    # End to end: a leaked full account number is scrubbed; a genuinely-masked value survives.
    leaked = ds._list_row_fields(
        {"account_number_masked": "4111111111111111"}, ds._TRADELINES_LIST, loan_file_id=_LF
    )
    masked = ds._list_row_fields(
        {"account_number_masked": "****1111"}, ds._TRADELINES_LIST, loan_file_id=_LF
    )
    assert leaked["account_number_masked"].value == "[redacted]"  # a masking miss is scrubbed
    assert masked["account_number_masked"].value == "****1111"  # a real mask is preserved


# --------------------------------------------------------------------------- #
# bug-010 — the per-list PII route (`ListSpec.pii`), the step LP-443 deferred
# --------------------------------------------------------------------------- #


def test_pii_routing_beats_redact_and_hashes_the_raw_value() -> None:
    """THE ORDER IS THE WHOLE POINT, and the first cut had it backwards.

    `ListSpec.pii` exists to replace the `redact` backstop, so the two WILL be declared on the same
    field — `_TRADELINES_LIST` already carries `redact={"account_number_masked"}`. Redacting first
    and masking second hashes the string "[redacted]", which gives every leaked account on the file
    the SAME match_hash and makes two unrelated accounts compare equal. Masking runs from the raw
    value; a masked field needs no scrub, because the mask is strictly stronger.
    """
    from app.verification.snapshot.pii import PiiKind

    spec = ds.ListSpec(
        name="probe",
        fields=("account_number_masked",),
        redact=frozenset({"account_number_masked"}),
        pii={"account_number_masked": (PiiKind.ACCOUNT, False)},
    )
    one = ds._list_row_fields({"account_number_masked": "4111111111111111"}, spec, loan_file_id=_LF)
    two = ds._list_row_fields({"account_number_masked": "5500000000000004"}, spec, loan_file_id=_LF)

    first = one["account_number_masked"]
    assert first.display == "****1111", "the last four of the REAL number, not of '[redacted]'"
    assert first.match_hash is not None
    assert first.match_hash != two["account_number_masked"].match_hash, (
        "two unrelated accounts must never compare equal — the failure hashing '[redacted]' causes"
    )


def test_a_pre_masked_row_field_keeps_its_last_four() -> None:
    """The list-row PII LP-443 deferred is mostly the PRE-masked kind, so the route has to express
    it. Through `from_raw` a stored "****1111" masks to "****" — the last four the extractor
    deliberately exposed is destroyed — and still hashes, so every account ending 1111 compares
    equal. `pre_masked=True` keeps the display and carries no hash."""
    from app.verification.snapshot.pii import PiiKind

    spec = ds.ListSpec(
        name="probe",
        fields=("account_number_masked",),
        pii={"account_number_masked": (PiiKind.ACCOUNT, True)},
    )
    field = ds._list_row_fields({"account_number_masked": "****1111"}, spec, loan_file_id=_LF)[
        "account_number_masked"
    ]

    assert field.display == "****1111"
    assert field.match_hash is None, "only the masked form was ever captured — not matchable"


def test_an_absent_row_field_is_not_given_a_mask() -> None:
    """A masked display on a field the extractor never read would fabricate a value."""
    from app.verification.snapshot.pii import PiiKind

    spec = ds.ListSpec(
        name="probe",
        fields=("account_number_masked",),
        pii={"account_number_masked": (PiiKind.ACCOUNT, False)},
    )
    field = ds._list_row_fields({}, spec, loan_file_id=_LF)["account_number_masked"]
    assert not field.is_present and field.absent


def test_a_pii_name_that_is_not_a_field_is_refused_at_import() -> None:
    """bug-010 — `_LIST_SPECS` is emitted by the LP-438 generator from `schema_specs/*.json`, so a
    regeneration that renames a field would leave the registry naming a key that no longer exists.
    Masking would silently stop, the raw value would land in the row again, and the at-rest guard
    would resume refusing every snapshot on the file — the exact failure bug-010 fixed, reintroduced
    with no signal. It fails loudly instead, at load."""
    import pytest
    from app.verification.snapshot.pii import PiiKind

    with pytest.raises(ValueError, match="undeclared field"):
        ds.ListSpec(
            name="probe", fields=("amount",), pii={"renamed_away": (PiiKind.ACCOUNT, False)}
        )

    # A derived field is a legitimate target, and must not be refused.
    ds.ListSpec(
        name="probe",
        fields=("transaction_type",),
        derived=(ds.DerivedSpec(field="direction", from_field="transaction_type", mapping={}),),
        pii={"direction": (PiiKind.ACCOUNT, False)},
    )
