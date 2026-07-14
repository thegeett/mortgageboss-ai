"""Bank-statement transactions in the snapshot (LP-302a; content_ids LP-312).

Covers: a bank statement's transactions surface as TransactionRecords (date/amount/
direction/description); direction is DERIVED from transaction_type only (an unknown/
ambiguous type + the extractor's positive amount → NO fabricated 'credit'); description
PII (bare 9+-digit runs AND space/dash-grouped accounts/cards) redacted while dates and
the sourcing signal survive; the statement's masked account lives once on the parent
DocumentEntry, NOT copied onto every row; zero-deposit statement → present-empty (distinct
from absent); non-bank doc → absent; and a lossless JSON round-trip (persist guard passes).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.documents_section import (
    build_document_fields,
    build_transactions,
    transaction_field_sets,
)
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    SNAPSHOT_VERSION,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TransactionRecord,
)
from app.verification.snapshot.persistence import _assert_no_raw_pii
from app.verification.snapshot.pii import PiiField

_DOC_ID = "doctest0000000000"


def _txns(
    extracted: dict[str, object],
    document_type: str = "bank_statement",
    *,
    document_content_id: str = _DOC_ID,
) -> tuple[TransactionRecord, ...] | None:
    """Reshape + build transactions for a document (LP-312 two-step API)."""
    return build_transactions(
        transaction_field_sets(extracted, document_type),
        document_content_id=document_content_id,
    )


def _txn(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "date": "2026-05-05",
        "description": "WELLS FARGO DES:PAYROLL ID:123456789 INDN:AKASH PATEL",
        "amount": "8076.93",
        "transaction_type": "deposit",
    }
    base.update(kw)
    return base


def _extracted(
    txns: list[dict[str, object]], account: str | None = "****5667"
) -> dict[str, object]:
    """A bank-statement extraction: the transaction list + the statement's masked account."""
    out: dict[str, object] = {"transactions": txns}
    if account is not None:
        out["account_number_masked"] = {"value": account, "source": None, "confidence": 0.99}
    return out


def test_bank_statement_transactions_surface_as_records() -> None:
    extracted = _extracted([_txn(), _txn(amount="-40.00", transaction_type="fee")])
    txns = _txns(extracted)
    assert txns is not None and len(txns) == 2
    first = txns[0]
    assert isinstance(first, TransactionRecord)
    assert first.content_id.startswith("txn")  # stable content-id stamped
    assert first.date.value == "2026-05-05"
    assert first.amount.value == "8076.93"
    assert first.direction.value == "credit"  # deposit → credit
    assert first.direction.source is FieldSource.DERIVED  # computed, not read verbatim
    assert first.date.source is FieldSource.EXTRACTED
    assert first.date.confidence is None  # extraction transactions carry no confidence
    assert txns[1].direction.value == "debit"  # fee → debit


def test_ambiguous_or_unknown_type_has_no_fabricated_direction() -> None:
    """The core AS-1 fix: a positive amount (the extractor's contract) with an unknown or
    ambiguous type must NOT be guessed as 'credit' — that would forge a deposit."""
    txns = _txns(
        {
            "transactions": [
                _txn(transaction_type="transfer", amount="9500.00"),  # bare transfer — ambiguous
                _txn(transaction_type=None, amount="500.00"),  # no type
                _txn(transaction_type="ach", amount="1200.00"),  # bare ACH — ambiguous
            ]
        }
    )
    assert txns is not None and len(txns) == 3
    for t in txns:
        assert t.direction.absent is True  # unclassifiable → absent, never "credit"


def test_direction_from_negative_amount_is_debit() -> None:
    """A signed export (negative amount) with no type → debit; a positive one stays absent."""
    txns = _txns(
        {
            "transactions": [
                _txn(transaction_type=None, amount="-25.00"),  # negative → debit
                _txn(transaction_type=None, amount="(30.00)"),  # accounting-negative → debit
                _txn(transaction_type=None, amount="42.00"),  # positive, no type → absent
            ]
        }
    )
    assert txns is not None
    assert txns[0].direction.value == "debit"
    assert txns[1].direction.value == "debit"
    assert txns[2].direction.absent is True


def test_description_pii_is_redacted() -> None:
    txns = _txns({"transactions": [_txn()]})
    assert txns is not None
    desc = txns[0].description.value
    assert isinstance(desc, str)
    # the 9-digit payroll id is gone; the sourcing signal + name are kept
    assert "123456789" not in desc
    assert "[redacted]" in desc
    assert "PAYROLL" in desc and "AKASH PATEL" in desc


def test_separated_account_in_description_is_redacted() -> None:
    """Finding (b): space/dash-grouped accounts/cards a bare \\d{9,} misses are scrubbed,
    while dates (≤8 digits) and short ids survive."""
    spaced = _txns({"transactions": [_txn(description="ACH TRANSFER 1234 5678 9012 3456 CHASE")]})
    assert spaced is not None
    d0 = spaced[0].description.value
    assert isinstance(d0, str)
    assert "1234 5678 9012 3456" not in d0 and "9012" not in d0
    assert "[redacted]" in d0 and "CHASE" in d0  # sourcing signal kept

    dashed = _txns({"transactions": [_txn(description="CHECK 1234-5678-9012 CLEARED")]})
    assert dashed is not None
    d1 = dashed[0].description.value or ""
    assert "1234-5678-9012" not in d1 and "[redacted]" in d1

    # A date (8 digits, "2026-05-05") and a short id are NOT redacted.
    dated = _txns({"transactions": [_txn(description="POS 2026-05-05 SAV 5683 COFFEE")]})
    assert dated is not None
    d2 = dated[0].description.value or ""
    assert "2026-05-05" in d2 and "SAV 5683" in d2 and "[redacted]" not in d2


def test_statement_account_lives_on_entry_fields_not_on_each_row() -> None:
    """Finding (#1/#2): the masked account is carried ONCE on the entry's fields — a
    pre-masked, non-matchable PiiField — never duplicated onto every transaction row."""
    extracted = _extracted([_txn(), _txn()], account="****5667")
    fields = build_document_fields(extracted, "bank_statement", loan_file_id=uuid4())
    acct = fields["account_number_masked"]
    assert isinstance(acct, PiiField)
    assert acct.display == "****5667" and acct.match_hash is None  # pre-masked, non-matchable
    # The rows carry no per-row account copy (the field was removed).
    txns = _txns(extracted)
    assert txns is not None
    assert not hasattr(txns[0], "account")


def test_absent_transaction_field_is_missing_not_present_null() -> None:
    txns = _txns({"transactions": [_txn(date=None, amount="100.00")]})
    assert txns is not None
    assert txns[0].date.absent is True  # extractor gave no date → absent
    assert txns[0].amount.value == "100.00"


def test_zero_transactions_is_present_empty_not_absent() -> None:
    empty = _txns({"transactions": []})
    assert empty == ()  # present-empty (a statement with no transactions)
    # ... distinct from absent:
    absent = _txns({})  # no transactions key
    assert absent is None
    assert empty != absent


def test_non_bank_document_has_no_transactions() -> None:
    assert _txns({"employee_name": {"value": "x"}}, "pay_stub") is None
    assert _txns({"transactions": [_txn()]}, "w2") is None  # only bank_statement


def test_transactions_round_trip_losslessly_and_pass_persist_guard() -> None:
    lf = uuid4()
    doc_id = "docroundtrip00000"
    entry = DocumentEntry(
        content_id=doc_id,
        document_type="bank_statement",
        fields={"account_number_masked": Field.present("****3312", source=FieldSource.EXTRACTED)},
        transactions=_txns(
            _extracted([_txn(), _txn(amount="-9.99", transaction_type="fee")], account="****3312"),
            document_content_id=doc_id,
        ),
    )
    snap = Snapshot(
        loan_file_id=lf,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        documents=DocumentsSection.present([entry]),
    )
    assert snap.snapshot_version == SNAPSHOT_VERSION == 4

    # Lossless JSON round-trip (the LP-209 acceptance bar), transactions preserved.
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back == snap
    rt = back.documents.entries[0].transactions
    assert rt is not None and len(rt) == 2 and rt[0].direction.value == "credit"
    assert rt[0].direction.source is FieldSource.DERIVED  # derived provenance survives
    assert rt[0].content_id.startswith("txn")  # content_id survives round-trip

    # The at-rest guard must NOT reject it — the redaction removed the 9+-digit id, and the
    # content_ids (letter-prefixed hex) never trip the long-digit-run rule.
    _assert_no_raw_pii(snap.model_dump_json())  # raises if a raw SSN/9-digit run survived


def test_present_empty_transactions_survive_round_trip() -> None:
    lf = uuid4()
    entry = DocumentEntry(
        content_id="docempty000000000", document_type="bank_statement", transactions=()
    )  # present-empty
    snap = Snapshot(
        loan_file_id=lf,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        documents=DocumentsSection.present([entry]),
    )
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back.documents.entries[0].transactions == ()  # still present-empty, not None
    assert back == snap


def test_transaction_record_is_frozen() -> None:
    rec = TransactionRecord(
        content_id="txnfrozen00000000",
        date=Field.missing(),
        amount=Field.missing(),
        direction=Field.missing(),
        description=Field.missing(),
    )
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen ValidationError
        rec.amount = Field.present("1", source=FieldSource.EXTRACTED)
