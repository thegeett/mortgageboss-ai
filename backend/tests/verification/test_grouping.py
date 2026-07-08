"""LP-125R FIX 9 — the shared account-grouping module (AS-8 continuity + AS-1 sourcing use ONE scheme).

Pins that the promoted grouping is a single implementation: the same account yields the same opaque token
and the same "account N" label across rules, distinct accounts don't merge, and no PII leaks into a label.
"""

from datetime import date
from decimal import Decimal

from app.verification.evaluators.grouping import (
    account_grouping_token,
    account_token_from_fields,
    label_accounts,
)
from app.verification.fact_namespace.snapshot import BankStatementFacts, Fact


def _stmt(
    *, bank="Chase", masked="****1", account_type="checking", holder=None
) -> BankStatementFacts:
    return BankStatementFacts(
        source_document_id="d",
        bank_name=bank,
        account_number_masked=masked,
        account_type=account_type,
        account_holder_name=holder,
        period_start=Fact[date](value=None),
        period_end=Fact[date](value=None),
        beginning_balance=Fact[Decimal](value=None),
        ending_balance=Fact[Decimal](value=None),
    )


def test_same_account_same_token() -> None:
    assert account_grouping_token(_stmt()) == account_grouping_token(_stmt())


def test_distinct_accounts_distinct_tokens() -> None:
    assert account_grouping_token(_stmt(masked="****1")) != account_grouping_token(
        _stmt(masked="****2")
    )
    # Same last-4 at different banks must NOT collide.
    assert account_grouping_token(_stmt(bank="Chase", masked="****9")) != account_grouping_token(
        _stmt(bank="Wells", masked="****9")
    )


def test_ungroupable_without_bank() -> None:
    assert account_grouping_token(_stmt(bank=None, masked="****1")) is None
    assert account_grouping_token(_stmt(bank=None, masked=None, holder=None)) is None


def test_labels_are_stable_pii_free_ordinals() -> None:
    a, b = _stmt(masked="****1"), _stmt(masked="****2")
    labels = label_accounts([b, a])  # order-independent — sorted by token
    assert set(labels.values()) == {"account 1", "account 2"}
    # Same account across a second call → same label set (stable within a run).
    assert label_accounts([a, b]) == labels
    # A masked number never appears in a label.
    assert all("****" not in v for v in labels.values())


def test_doc_fields_token_matches_statement_token() -> None:
    # FIX 5 — a sourcing doc that carries the same account fields resolves to the SAME account token.
    stmt = _stmt(bank="Chase", masked="****1", account_type="checking")
    doc_token = account_token_from_fields(
        {"bank_name": "Chase", "account_number_masked": "****1", "account_type": "checking"}
    )
    assert doc_token == account_grouping_token(stmt)


def test_both_evaluators_use_the_shared_grouping() -> None:
    # AS-8 and AS-1 both import the shared functions (no private per-module grouping / label drift).
    from app.verification.evaluators import bank_statement_continuity as as8
    from app.verification.evaluators import large_deposit as as1

    assert as8.account_grouping_token is account_grouping_token
    assert as8.label_accounts is label_accounts
    assert as1.account_grouping_token is account_grouping_token
    assert as1.label_accounts is label_accounts
