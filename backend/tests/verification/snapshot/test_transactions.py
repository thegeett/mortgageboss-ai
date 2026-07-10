"""Bank-statement transactions in the snapshot (LP-302a).

Covers: a bank statement's transactions surface as TransactionRecords (date/amount/
direction/description); the per-statement account carried as a PRE-MASKED, non-matchable
PiiField (display=****NNNN, match_hash=None — never hashed, no false collisions);
description PII (9+-digit runs / SSN) redacted; zero-deposit statement → present-empty
(distinct from absent); non-bank doc → absent; the version bump to 2; and a lossless JSON
round-trip incl. transactions (persist guard passes).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.documents_section import build_transactions
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
    txns = build_transactions(extracted, "bank_statement")
    assert txns is not None and len(txns) == 2
    first = txns[0]
    assert isinstance(first, TransactionRecord)
    assert first.date.value == "2026-05-05"
    assert first.amount.value == "8076.93"
    assert first.direction.value == "credit"  # deposit → credit
    assert first.date.source is FieldSource.EXTRACTED
    assert first.date.confidence is None  # extraction transactions carry no confidence
    assert txns[1].direction.value == "debit"  # fee → debit


def test_transaction_account_is_pre_masked_display_only_and_non_matchable() -> None:
    txns = build_transactions(
        _extracted([_txn(), _txn()], account="1234567890125667"), "bank_statement"
    )
    assert txns is not None and len(txns) == 2
    acct = txns[0].account
    assert isinstance(acct, PiiField)
    # Pre-masked: display is the canonical last-4; NO raw value survived, NO hash.
    assert acct.display == "****5667"
    assert acct.match_hash is None
    assert acct.is_matchable is False  # structurally non-matchable (LP-203 invariant)
    # Two None-hash accounts NEVER match each other (no false same-last-4 collision).
    assert acct.matches(txns[1].account) is False
    assert txns[1].account.matches(acct) is False
    # Every row on the statement carries the SAME per-statement account.
    assert txns[0].account == txns[1].account


def test_transaction_account_absent_when_statement_has_none() -> None:
    txns = build_transactions(_extracted([_txn()], account=None), "bank_statement")
    assert txns is not None
    assert txns[0].account.absent is True  # no statement account → absent, not a fake mask


def test_description_pii_is_redacted() -> None:
    txns = build_transactions({"transactions": [_txn()]}, "bank_statement")
    assert txns is not None
    desc = txns[0].description.value
    assert isinstance(desc, str)
    # the 9-digit payroll id is gone; the sourcing signal + name are kept
    assert "123456789" not in desc
    assert "[redacted]" in desc
    assert "PAYROLL" in desc and "AKASH PATEL" in desc


def test_direction_from_amount_sign_when_no_type() -> None:
    txns = build_transactions(
        {"transactions": [_txn(transaction_type=None, amount="-25.00")]}, "bank_statement"
    )
    assert txns is not None and txns[0].direction.value == "debit"


def test_absent_transaction_field_is_missing_not_present_null() -> None:
    txns = build_transactions(
        {"transactions": [_txn(date=None, amount="100.00")]}, "bank_statement"
    )
    assert txns is not None
    assert txns[0].date.absent is True  # extractor gave no date → absent
    assert txns[0].amount.value == "100.00"


def test_zero_transactions_is_present_empty_not_absent() -> None:
    empty = build_transactions({"transactions": []}, "bank_statement")
    assert empty == ()  # present-empty (a statement with no transactions)
    # ... distinct from absent:
    absent = build_transactions({}, "bank_statement")  # no transactions key
    assert absent is None
    assert empty != absent


def test_non_bank_document_has_no_transactions() -> None:
    assert build_transactions({"employee_name": {"value": "x"}}, "pay_stub") is None
    assert build_transactions({"transactions": [_txn()]}, "w2") is None  # only bank_statement


def test_transactions_round_trip_losslessly_and_pass_persist_guard() -> None:
    lf = uuid4()
    entry = DocumentEntry(
        document_type="bank_statement",
        fields={"account_number_masked": Field.present("****3312", source=FieldSource.EXTRACTED)},
        transactions=build_transactions(
            _extracted([_txn(), _txn(amount="-9.99", transaction_type="fee")], account="****3312"),
            "bank_statement",
        ),
    )
    snap = Snapshot(
        loan_file_id=lf,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        documents=DocumentsSection.present([entry]),
    )
    assert snap.snapshot_version == SNAPSHOT_VERSION == 2

    # Lossless JSON round-trip (the LP-209 acceptance bar), transactions preserved.
    back = Snapshot.model_validate_json(snap.model_dump_json())
    assert back == snap
    rt = back.documents.entries[0].transactions
    assert rt is not None and len(rt) == 2 and rt[0].direction.value == "credit"
    # The pre-masked, non-matchable account survives the round-trip intact.
    assert rt[0].account.display == "****3312" and rt[0].account.match_hash is None

    # The at-rest guard must NOT reject it — the redaction removed the 9+-digit id.
    _assert_no_raw_pii(snap.model_dump_json())  # raises if a raw SSN/9-digit run survived


def test_present_empty_transactions_survive_round_trip() -> None:
    lf = uuid4()
    entry = DocumentEntry(document_type="bank_statement", transactions=())  # present-empty
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
        date=Field.missing(),
        amount=Field.missing(),
        direction=Field.missing(),
        description=Field.missing(),
        account=PiiField.missing(),
    )
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen ValidationError
        rec.amount = Field.present("1", source=FieldSource.EXTRACTED)
