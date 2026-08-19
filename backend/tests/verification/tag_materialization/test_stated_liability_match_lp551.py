"""LP-551 — `txn.stated_liability_match`: does this payment's payee appear on the 1003?

The input that turns FR-5 from a list into a finding. Without it FR-5 matches every recurring payment
to a creditor — a mortgage, a card, an autopay — which is true of every file, so it would ask a
processor to check the borrower's ordinary bills forever.

THE FIXTURES ARE LF-WCHG'S REAL PAYEES AND ITS REAL 1003, not constructed pairs. Every abbreviation
below is one a bank actually printed, and two of the four matches are inferences rather than obvious —
which is the whole reason the tag is graded instead of yes/no.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.snapshot.model import (
    DocumentEntry,
    DocumentsSection,
    Field,
    MismoSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.tag_materialization.derived import txn_stated_liability_match

# The nine liabilities LF-WCHG's application actually states.
_STATED = [
    "UNITED WHSLE MORT",
    "DIGITAL FED CREDIT UNI",
    "HAPPEN BANK",
    "AMEX",
    "DISCOVERC",
    "BANK OF AMERICA",
    "CITI",
    "DISCOVER BANK",
    "APPLE CARD/GS BANK USA",
]


def _snapshot(description: str, *, stated: list[str] | None = None) -> Snapshot:
    facts = {}
    for i, holder in enumerate(_STATED if stated is None else stated):
        facts[f"liability.{i}.holder_name"] = Field(value=holder, source="extracted")
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 18, tzinfo=UTC),
        mismo=MismoSection(facts=facts),
        documents=DocumentsSection(
            entries=[
                DocumentEntry(
                    content_id="bs",
                    document_type="bank_statement",
                    transactions=(
                        TransactionRecord(
                            content_id="t1",
                            date=Field(value="2025-03-03", source="extracted"),
                            amount=Field(value="3286.21", source="extracted"),
                            description=Field(value=description, source="extracted"),
                            direction=Field(value="debit", source="derived"),
                        ),
                    ),
                )
            ]
        ),
        tags=TagsSection.present({}),
    )


def _match(description: str, *, stated: list[str] | None = None) -> str:
    return str(txn_stated_liability_match(_snapshot(description, stated=stated), "t1", None)[0])


# --------------------------------------------------------------------------------------------- #
# THE FOUR REAL PAYEES — every one must be suppressed, or FR-5 reports normality
# --------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # No whole token in common — only the PREFIX test relates these, and a bank really does print
        # the servicer's name unspaced against a 1003 that abbreviates it.
        ("UNITEDWHOLESALE LOAN PAYMT # [REDACTED-ID]", "probable"),
        # Once the generic finance words go, both sides are exactly "CITI".
        ("CITI AUTOPAY PAYMENT # [REDACTED-ID]", "exact"),
        ("DISCOVER E-PAYMENT # # TALLURI ADITY", "probable"),
        # The weakest of the four, and the reason the tag is graded: the card is reached through PayPal
        # and disclosed under the issuing bank's name.
        ("PAYPAL INST XFER # APPLE.COM BILL GU", "probable"),
    ],
)
def test_every_disclosed_payee_on_the_real_file_matches(description: str, expected: str) -> None:
    assert _match(description) == expected


def test_a_payee_on_no_liability_is_none() -> None:
    """The one FR-5 exists for: a recurring creditor payment the application never mentions."""
    assert _match("CARVANA PAYMENT # 4471") == "none"


# --------------------------------------------------------------------------------------------- #
# §8 — absent is not none
# --------------------------------------------------------------------------------------------- #
def test_an_application_with_no_liabilities_is_unknown_not_none() -> None:
    """LOAD-BEARING. "none" means we compared and nothing matched. If the application states no
    liabilities there was nothing to compare against, and calling that "none" would fire FR-5 on EVERY
    payment the borrower makes — on precisely the files carrying the least information."""
    assert _match("CARVANA PAYMENT", stated=[]) == "unknown"


def test_an_unreadable_payee_is_unknown_not_none() -> None:
    """A payee we cannot name cannot be matched against one we can."""
    assert _match("ACH DEBIT 88213") == "unknown"


# --------------------------------------------------------------------------------------------- #
# PRECISION — the generic-word strip must not make unrelated payees look alike
# --------------------------------------------------------------------------------------------- #
def test_two_unrelated_lenders_do_not_match_through_their_generic_words() -> None:
    """Every lender has BANK, CREDIT, PAYMENT in its name. Leaving them in would relate any two payees
    through words that carry no identity at all."""
    assert _match("SOFI BANK LOAN PAYMENT", stated=["HAPPEN BANK", "BANK OF AMERICA"]) == "none"


def test_a_short_coincidental_token_does_not_match() -> None:
    """Below four characters a shared token is a coincidence, not an identity."""
    assert _match("GS FINANCE PAYMENT", stated=["APPLE CARD/GS BANK USA"]) == "none"
