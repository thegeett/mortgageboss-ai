"""bug-001 — one bank-statement row, three identities.

On a real file the cross-check tab churned: nine findings resolved and nine opened after four
documents were added, several the same issue reworded — and one pair carried a BYTE-IDENTICAL title,
"Recurring Chase credit card payments not matched to stated liabilities". Nothing had resolved.

`finding_key` is `sha256(kind + sorted paths)`, so identity is the snapshot addresses. Both rows were
the same kind with the same title, so the PATHS differed — and the indices were identical, so it was
not the index drift one would guess:

    run 1   documents.entries.0.transactions.13.description
    run 2   documents.entries.0.lists.transactions.13.fields.amount.value

Same statement, same row, two channels and two quoted fields. `documents_section` publishes a bank
statement's transactions twice — `entry.transactions` (typed, feeds AS-1) and
`entry.lists["transactions"]` (generic, LP-437) — and says so in its own comment: "the SAME extracted
transactions rows populate BOTH". The grounding check accepts both, correctly. Identity hashed them
verbatim, which is the failure LP-613 fixed for leaf-vs-route, arriving through a second door.
"""

from __future__ import annotations

from app.ai.snapshot_cross_source import _canonical_path

_NO_KEYS = frozenset[str]()


def _key(path: str) -> str:
    return _canonical_path(path, _NO_KEYS)


# --------------------------------------------------------------------------- #
# The reported case
# --------------------------------------------------------------------------- #
def test_the_two_channels_of_one_transaction_are_one_identity() -> None:
    """The exact pair from the file, run 1 against run 2."""
    assert _key("documents.entries.0.transactions.13.description") == _key(
        "documents.entries.0.lists.transactions.13.fields.amount.value"
    )


def test_a_different_quoted_field_of_one_row_is_one_identity() -> None:
    """Within one transaction the field is the model's choice of what to quote about a single event
    — commentary, in LP-604's sense, like the title."""
    assert _key("documents.entries.1.transactions.6.description") == _key(
        "documents.entries.1.transactions.6.amount"
    )


# --------------------------------------------------------------------------- #
# The precision half — what must NOT merge
# --------------------------------------------------------------------------- #
def test_two_different_rows_stay_distinct() -> None:
    """THE ROW INDEX IS KEPT, as LP-613 kept it: stripping it would collapse two different
    transactions onto one key, which is the failure measurement rejected there."""
    assert _key("documents.entries.0.transactions.13.description") != _key(
        "documents.entries.0.transactions.14.description"
    )


def test_the_same_row_number_in_two_documents_stays_distinct() -> None:
    assert _key("documents.entries.0.transactions.13.description") != _key(
        "documents.entries.1.transactions.13.description"
    )


def test_two_facts_about_one_liability_stay_distinct() -> None:
    """Deliberately NOT applied to the flat sections. A balance mismatch and a payment mismatch are
    genuinely different findings about one debt, and merging them would hide one behind the other."""
    assert _key("liability.3.unpaid_balance") != _key("liability.3.monthly_payment")


def test_a_documents_own_field_is_not_treated_as_a_row() -> None:
    """`documents.entries.0.fields.annual_premium.value` addresses the DOCUMENT, not a row in it —
    there is no row index, so the row rule must not fire and swallow the field."""
    path = "documents.entries.0.fields.annual_premium.value"
    assert _key(path) == path


def test_a_non_document_path_is_untouched() -> None:
    assert _key("mismo.facts.property.postal_code") == "mismo.facts.property.postal_code"
