"""The processor-facing subject LABEL (LP-377-B) — declared per subject TYPE, never a raw content-id.

The ticket in a test: a governed finding's subject renders as a filename / amount / borrower / "Loan-level",
dispatched on the KEY'S SHAPE (no rule-id branch). No label is ever a content-id hash, a UUID, or a dotted
tag id; an unresolvable subject reads honestly, never the hash.
"""

from __future__ import annotations

import re
from uuid import uuid4

from app.services.rule_subject_label import resolve_subject_label

# A dotted tag id (id.dob), a content-id hash (doc…/txn…), or a UUID must NEVER appear in a label.
_DOTTED_TAG = re.compile(r"\b[a-z_]+\.[a-z_.]+\b")
_CONTENT_ID = re.compile(r"\b(?:doc|txn)[0-9a-f]{8,}\b")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
# A legitimate filename ends in an extension with a dot — strip it before the dotted-tag check so a real
# filename ("statement.pdf") is not mistaken for a vocabulary tag id ("id.dob").
_FILE_EXT = re.compile(r"\.(?:pdf|jpe?g|png|tiff?|heic|docx?|txt|csv)$", re.IGNORECASE)


def _amount_tags(amount: str = "20000.00", date: str | None = "2026-03-27"):
    tags = [{"tag_id": "txn.amount", "value": amount}]
    if date is not None:
        tags.append({"tag_id": "txn.date", "value": date})
    return tags


# --------------------------------------------------------------------------- #
# Per subject TYPE — the label a processor recognises
# --------------------------------------------------------------------------- #
def test_loan_subject_reads_loan_level() -> None:
    assert resolve_subject_label("loan", []) == "Loan-level"


def test_deposit_names_its_amount_and_date() -> None:
    assert resolve_subject_label("txn54c6369a", _amount_tags()) == "Deposit of $20,000 on 3/27"


def test_deposit_without_a_date_still_names_the_amount() -> None:
    assert resolve_subject_label("txnabc123", _amount_tags(date=None)) == "Deposit of $20,000"


def test_deposit_keeps_cents_when_not_whole() -> None:
    assert (
        resolve_subject_label("txnabc123", _amount_tags(amount="20000.50", date=None))
        == "Deposit of $20,000.50"
    )


def test_document_names_its_file() -> None:
    label = resolve_subject_label(
        "doc067c28e496b10b5f",
        [],
        document_filenames={"doc067c28e496b10b5f": "Statement_Mar2026.pdf"},
    )
    assert label == "Statement_Mar2026.pdf"


def test_borrower_names_the_person() -> None:
    bid = str(uuid4())
    assert resolve_subject_label(bid, [], borrower_names={bid: "Dana Sample"}) == "Dana Sample"


def test_account_reads_a_bank_account() -> None:
    assert resolve_subject_label("account:chase:1234", []) == "a bank account"


# --------------------------------------------------------------------------- #
# The honest fallback (D3) — never a hash, never a fabricated name
# --------------------------------------------------------------------------- #
def test_document_gone_reads_honestly_not_a_hash() -> None:
    # No map entry (removed / re-extracted since the run → its content-id changed).
    label = resolve_subject_label("doc067c28e496b10b5f", [])
    assert label == "a document no longer in this file"
    assert "doc067c" not in label


def test_borrower_gone_reads_honestly_not_a_uuid() -> None:
    bid = str(uuid4())
    label = resolve_subject_label(bid, [])
    assert label == "a borrower no longer on this file"
    assert bid not in label


def test_deposit_without_an_amount_reads_a_deposit() -> None:
    assert resolve_subject_label("txnabc123", []) == "a deposit"


def test_null_subject_key_does_not_crash() -> None:
    assert resolve_subject_label(None, []) == "this file"


# --------------------------------------------------------------------------- #
# THE GUARD — no user-facing label leaks an engine identifier (extends LP-376-C's spirit)
# --------------------------------------------------------------------------- #
def test_no_label_ever_contains_a_content_id_uuid_or_dotted_tag() -> None:
    bid = str(uuid4())
    labels = [
        resolve_subject_label("loan", []),
        resolve_subject_label("txn54c6369a", _amount_tags()),
        resolve_subject_label("txnabc", []),
        resolve_subject_label("doc067c28e496b10b5f", []),  # gone → fallback
        resolve_subject_label("doc067c", [], document_filenames={"doc067c": "W2_2025.pdf"}),
        resolve_subject_label("account:chase:1234", []),
        resolve_subject_label(bid, [], borrower_names={bid: "Dana Sample"}),
        resolve_subject_label(bid, []),  # gone → fallback
        resolve_subject_label(None, []),
    ]
    for label in labels:
        assert label  # never empty
        assert not _CONTENT_ID.search(label), f"content-id leaked into {label!r}"
        assert not _UUID.search(label), f"a UUID leaked into {label!r}"
        assert not _DOTTED_TAG.search(_FILE_EXT.sub("", label)), (
            f"a dotted tag leaked into {label!r}"
        )


# ------------------------------------------------------------------------------------------------ #
# LP-531 — the subject shape that had no branch
# ------------------------------------------------------------------------------------------------ #
def test_a_liability_reads_as_a_debt_not_as_an_unrecognised_item() -> None:
    """⚠️ FOUND ON A REAL FILE. `per_liability` rules have existed since LP-480 and no branch here ever
    matched their key shape, so every one of their findings fell to the unrecognised-key floor. LF-WCHG
    shipped FOUR CR-6 findings whose subject read "an item in this file" — which tells a processor
    neither what the item is, nor that the four rows are four different debts.

    The floor did its job (it never printed `lia7a033a46ec70cc10`). It was simply never reached on
    purpose, and an honest fallback for an unforeseen shape is not an answer for a foreseen one."""
    assert resolve_subject_label("lia7a033a46ec70cc10", ()) == "a debt on this file"


def test_an_unrecognised_shape_still_falls_to_the_honest_floor() -> None:
    """Adding a branch must not remove the floor — the next unforeseen shape needs it just as much."""
    assert resolve_subject_label("wat:xyz", ()) == "an item in this file"


def test_a_missing_expected_document_is_named_rather_than_generic() -> None:
    """LP-330's absent-document subject IS the missing document, so its type is the whole identity.
    IN-8 and ID-7 shipped as "an item in this file" when the file could have said which document."""
    assert resolve_subject_label("missing:voe", ()) == "VOE (not in the file)"
    assert (
        resolve_subject_label("missing:title_commitment", ())
        == "title commitment (not in the file)"
    )
