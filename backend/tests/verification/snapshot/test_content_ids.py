"""Stable, run-independent content-ids for raw snapshot facts (LP-312).

Proves the four guarantees deterministically (no DB): stability (same content → same id
every time), uniqueness (identical-content siblings → distinct ids via the tiebreak),
run-independence (a document inserted/removed elsewhere does not change another fact's id),
and PII-at-rest safety (ids never trip the persistence guard).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.verification.snapshot.content_id import (
    DOC_PREFIX,
    TXN_PREFIX,
    assign_content_ids,
    content_fingerprint,
    unordered_fingerprint,
)
from app.verification.snapshot.documents_section import (
    TransactionFieldSet,
    _document_base,
    build_transactions,
    transaction_field_sets,
)
from app.verification.snapshot.model import BorrowerRef
from app.verification.snapshot.persistence import _assert_no_raw_pii


def _txn(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "date": "2026-05-05",
        "description": "PAYROLL DEPOSIT",
        "amount": "50.00",
        "transaction_type": "deposit",
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- #
# The hashing helpers
# --------------------------------------------------------------------------- #


def test_assign_ids_are_deterministic_and_content_derived() -> None:
    payloads = [{"a": 1}, {"b": 2}, {"a": 1, "b": 2}]
    once = assign_content_ids(TXN_PREFIX, payloads)
    twice = assign_content_ids(TXN_PREFIX, payloads)
    assert once == twice  # deterministic
    assert all(i.startswith(TXN_PREFIX) for i in once)
    assert len(set(once)) == 3  # distinct content → distinct ids


def test_assign_ids_tiebreak_distinguishes_identical_content() -> None:
    dup = [{"x": 1}, {"x": 1}, {"x": 1}]
    ids = assign_content_ids(DOC_PREFIX, dup)
    assert len(set(ids)) == 3  # identical content → still 3 DISTINCT ids (occurrence tiebreak)


def test_assign_ids_are_position_independent() -> None:
    a, b, c = {"a": 1}, {"b": 2}, {"c": 3}
    base = assign_content_ids(DOC_PREFIX, [a, b, c])
    # Insert a new item at the FRONT: the ids of a/b/c must be unchanged (not positional).
    shifted = assign_content_ids(DOC_PREFIX, [{"z": 9}, a, b, c])
    assert shifted[1:] == base


def test_unordered_fingerprint_ignores_order() -> None:
    items = [{"a": 1}, {"b": 2}, {"c": 3}]
    assert unordered_fingerprint(items) == unordered_fingerprint(list(reversed(items)))
    # A changed member changes the fingerprint.
    assert unordered_fingerprint(items) != unordered_fingerprint([{"a": 1}, {"b": 2}, {"c": 4}])


def test_content_fingerprint_is_stable() -> None:
    assert content_fingerprint({"a": 1, "b": 2}) == content_fingerprint({"b": 2, "a": 1})


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #


def _sets(txns: list[dict[str, Any]]) -> list[TransactionFieldSet]:
    fs = transaction_field_sets(
        {"transactions": txns},
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    assert fs is not None
    return fs


def test_transaction_ids_are_stable_across_builds() -> None:
    txns = [_txn(), _txn(amount="100.00")]
    first = build_transactions(_sets(txns), document_content_id="docABC00000000000")
    second = build_transactions(_sets(txns), document_content_id="docABC00000000000")
    assert first is not None and second is not None
    assert [t.content_id for t in first] == [t.content_id for t in second]


def test_identical_transactions_get_distinct_ids() -> None:
    # Two byte-identical deposits (same day/amount/description) — a real duplicate.
    records = build_transactions(_sets([_txn(), _txn()]), document_content_id="docABC00000000000")
    assert records is not None and len(records) == 2
    assert records[0].content_id != records[1].content_id  # the tiebreak works


def test_transaction_ids_are_scoped_under_their_document() -> None:
    """Identical transaction content under two different statements → different ids."""
    fs = _sets([_txn()])
    a = build_transactions(fs, document_content_id="docAAA00000000000")
    b = build_transactions(fs, document_content_id="docBBB00000000000")
    assert a is not None and b is not None
    assert a[0].content_id != b[0].content_id  # scoped by parent, no cross-document collision


def test_content_ids_never_trip_the_pii_guard() -> None:
    """The letter-prefixed hex ids can never present a bare 9+-digit run to the guard."""
    records = build_transactions(
        _sets([_txn() for _ in range(50)]), document_content_id="docABC00000000000"
    )
    assert records is not None
    # JSON, because the guard now walks the decoded document to attribute a match to a field
    # (LP-509-C1) and its one production caller passes `snapshot.model_dump_json()`.
    _assert_no_raw_pii(json.dumps([t.content_id for t in records]))  # raises if any id looked
    # like a raw account/SSN


# --------------------------------------------------------------------------- #
# Documents (via the base payload the builder hashes)
# --------------------------------------------------------------------------- #


def test_document_ids_are_stable_and_position_independent() -> None:
    doc_a = _document_base("pay_stub", (), {}, None)
    doc_b = _document_base("w2", (), {}, None)
    doc_c = _document_base("bank_statement", (), {}, _sets([_txn()]))

    base = assign_content_ids(DOC_PREFIX, [doc_a, doc_b, doc_c])
    # A new document inserted at the front leaves the other three ids unchanged...
    shifted = assign_content_ids(
        DOC_PREFIX, [_document_base("appraisal", (), {}, None), doc_a, doc_b, doc_c]
    )
    assert shifted[1:] == base
    # ...and because a transaction's id is derived from its (unchanged) parent document id,
    # its transactions' ids are unaffected too.
    txns_before = build_transactions(_sets([_txn()]), document_content_id=base[2])
    txns_after = build_transactions(_sets([_txn()]), document_content_id=shifted[3])
    assert txns_before is not None and txns_after is not None
    assert [t.content_id for t in txns_before] == [t.content_id for t in txns_after]


def test_documents_differing_only_in_transactions_get_distinct_ids() -> None:
    """Two statements identical in type/fields but differing in transactions → distinct ids,
    deterministically (the transactions fingerprint feeds the document id)."""
    doc_1 = _document_base("bank_statement", (), {}, _sets([_txn(amount="10.00")]))
    doc_2 = _document_base("bank_statement", (), {}, _sets([_txn(amount="20.00")]))
    ids = assign_content_ids(DOC_PREFIX, [doc_1, doc_2])
    assert ids[0] != ids[1]


def test_document_id_is_independent_of_borrower_ref_order() -> None:
    """A joint document's id must NOT depend on the order its borrower links arrive in.

    The link query orders by confidence, and equal-confidence borrowers (both spouses matched
    exactly on a joint statement) have no stable relative order — so the same document could
    present its refs in either order across rebuilds. The id derivation sorts them, so the id
    is identical regardless of order (otherwise the id would drift between runs)."""
    b1 = BorrowerRef(borrower_id=UUID(int=1), name="Akash Patel")
    b2 = BorrowerRef(borrower_id=UUID(int=2), name="Priya Patel")
    forward = _document_base("bank_statement", (b1, b2), {}, None)
    reversed_ = _document_base("bank_statement", (b2, b1), {}, None)
    assert assign_content_ids(DOC_PREFIX, [forward]) == assign_content_ids(DOC_PREFIX, [reversed_])
