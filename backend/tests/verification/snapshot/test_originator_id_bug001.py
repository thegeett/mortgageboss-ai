"""bug-001 — capture the ACH originator id, so two debts to one institution can be told apart.

A payee name cannot separate them: a Chase card and a Chase auto loan are both "Chase", and grouping
FR-5's findings on the name alone would merge them into one obligation and UNDERSTATE the DTI — the
dangerous direction.

The statements print the id beside the payee, and we were dropping it:

    06/03  Chase Credit Crd Autopay   PPD ID: 4760039224   -107.07
    06/11  Chase Credit Crd Autopay   PPD ID: 4760039224     -8.75

On the real file it settled the opposite question. All four Chase payments carry the SAME originator,
so what looked like two accounts — two amounts, two days of the month — is ONE autopay charged twice
a month, reported four times.
"""

from __future__ import annotations

from uuid import UUID

from app.verification.snapshot.documents_section import (
    _IDENTITY_EXCLUDED_TXN_FIELDS,
    _txn_content,
    transaction_field_sets,
)
from app.verification.snapshot.pii import PiiField

_LF = UUID("00000000-0000-0000-0000-00000000f1e0")
_OTHER_LF = UUID("00000000-0000-0000-0000-00000000f1e1")

_ROWS = {
    "transactions": [
        {
            "date": "2026-06-03",
            "description": "Chase Credit Crd Autopay PPD ID: 4760039224",
            "amount": "107.07",
            "transaction_type": "withdrawal",
            "originator_id": "4760039224",
        },
        {
            "date": "2026-06-11",
            "description": "Chase Credit Crd Autopay PPD ID: 4760039224",
            "amount": "8.75",
            "transaction_type": "withdrawal",
            "originator_id": "4760039224",
        },
    ]
}


def test_the_originator_reaches_the_snapshot_masked() -> None:
    """bug-010 — IT REACHES THE SNAPSHOT, AND NOT AS ITSELF.

    A PPD ID is a bare 10-digit run, which is exactly what the LP-209 at-rest guard refuses. Carried
    as a plain `Field.value` it cost staging EVERY snapshot for a week — 36 rows, none newer than
    2026-08-25, while runs kept completing green because the persist is best-effort.
    """
    rows = transaction_field_sets(_ROWS, "bank_statement", loan_file_id=_LF)
    assert rows is not None
    for row in rows:
        field = row["originator_id"]
        assert isinstance(field, PiiField), "a bare digit run must never land as Field.value"
        assert "4760039224" not in str(field.model_dump()), "the raw id is discarded, not stored"
        assert field.display == "****9224", "the last four, the shape every masked account takes"
        assert field.match_hash is not None, "grouping is the whole reason this field exists"


def test_a_line_with_no_originator_is_absent_not_empty() -> None:
    """A cheque, a card purchase and an in-branch transfer print no company id. Absent != empty."""
    rows = transaction_field_sets(
        {"transactions": [{"date": "2026-06-04", "description": "CHECK 1042", "amount": "50.00"}]},
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    assert rows is not None and not rows[0]["originator_id"].is_present


def test_the_originator_is_NOT_part_of_a_transactions_identity() -> None:
    """THE COSTLY PART, and why it is excluded.

    A transaction's content id IS a finding's identity. Folding a new field into it re-keys every
    per-deposit finding on every file — they retire as `no_longer_applies` and mint again, stranding
    any sign-off a processor had made on the old copy. That happened once already in this ticket,
    when the borrower re-link changed six documents' ids and doubled the finding count on a real file.

    And it buys nothing: within one statement, date + amount + direction + description already
    separate every line. The originator says WHO the counterparty is, not WHICH ROW this is."""
    assert "originator_id" in _IDENTITY_EXCLUDED_TXN_FIELDS

    rows = transaction_field_sets(
        _ROWS, "bank_statement", loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0")
    )
    without = transaction_field_sets(
        {
            "transactions": [
                {k: v for k, v in r.items() if k != "originator_id"} for r in _ROWS["transactions"]
            ]
        },
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    assert rows is not None and without is not None
    # Same rows, one carrying the originator and one not → the SAME identity.
    assert _txn_content(rows[0]) == _txn_content(without[0])


def test_two_debts_to_one_institution_are_distinguishable() -> None:
    """What the field is for: the same payee name, two different creditors.

    bug-010 — and masking does not cost it. `match_hash` is deterministic per value within a file,
    so two originators still compare unequal and the same originator still compares equal; the raw
    id was never needed for either.
    """
    rows = transaction_field_sets(
        {
            "transactions": [
                {
                    "date": "2026-06-03",
                    "description": "Chase Credit Crd Autopay",
                    "amount": "107.07",
                    "originator_id": "4760039224",
                },
                {
                    "date": "2026-06-05",
                    "description": "Chase Auto Finance",
                    "amount": "612.00",
                    "originator_id": "9911223344",
                },
            ]
        },
        "bank_statement",
        loan_file_id=UUID("00000000-0000-0000-0000-00000000f1e0"),
    )
    assert rows is not None
    assert rows[0]["originator_id"].match_hash != rows[1]["originator_id"].match_hash


def test_the_same_originator_still_groups_within_a_file() -> None:
    """bug-010 — the property bug-001 actually needed, stated directly. On the real file all four
    Chase payments carry the SAME originator, which is what showed that two apparent accounts were
    one autopay charged twice a month. Equal originators must still be recognisably equal."""
    rows = transaction_field_sets(_ROWS, "bank_statement", loan_file_id=_LF)
    assert rows is not None
    first, second = rows[0]["originator_id"], rows[1]["originator_id"]
    assert first.match_hash == second.match_hash


def test_the_hash_is_salted_PER_FILE() -> None:
    """So the same originator on two different loan files is not a cross-file join key. The salt is
    what makes a stored hash useless outside the file it was built for."""
    here = transaction_field_sets(_ROWS, "bank_statement", loan_file_id=_LF)
    there = transaction_field_sets(_ROWS, "bank_statement", loan_file_id=_OTHER_LF)
    assert here is not None and there is not None
    assert here[0]["originator_id"].match_hash != there[0]["originator_id"].match_hash


def test_masking_did_not_move_a_transaction_identity() -> None:
    """bug-010's own risk, pinned. Changing a field's SHAPE changes the content it serializes to, and
    a transaction's content id IS a finding's identity — so a careless fix would retire and re-mint
    every per-deposit finding on every file. `originator_id` is excluded from that content, which is
    what makes the change safe; this asserts the exclusion still holds after the type changed."""
    rows = transaction_field_sets(_ROWS, "bank_statement", loan_file_id=_LF)
    assert rows is not None
    assert all("originator_id" not in _txn_content(row) for row in rows)


def test_no_finding_subject_is_a_transactions_row_id() -> None:
    """bug-010 — WHAT ACTUALLY MAKES THE MOVED `row_id`s SAFE, pinned so the reason cannot rot.

    Masking a row field moves every `row_id` in that list, because an id is derived from the whole
    row. "Nothing reads the list" would be the wrong reason to call that safe — and it is false:
    `source_document_by_subject` walks every list on every run and puts each `row_id` into the
    parents map. The real reason is narrower: nothing ENUMERATES transactions, so no finding's
    `subject_id` is a transactions row id and the changed keys are inert.

    `stable_row_id=True` on that list anticipates the enumerator that would break this, so the day
    someone adds one this fails and says what it costs: every finding on that list re-keyed once.
    """
    import re
    from pathlib import Path

    called_with = set()
    for path in Path("app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"all_list_rows\(\s*[\w.]+,\s*([^,)\n]+)", text):
            called_with.add(m.group(1).strip())

    assert called_with, "the scan found no call sites — it would pass vacuously"
    resolved = {
        "_TRADELINES_LIST_NAME": "tradelines",
        '"tradelines"': "tradelines",
    }
    unknown = called_with - set(resolved)
    assert not unknown, (
        "a list is enumerated that this test does not know about. If it declares `pii`, masking "
        f"already moved its row_ids and every finding on it re-keys once: {sorted(unknown)}"
    )
    assert {resolved[c] for c in called_with} == {"tradelines"}
