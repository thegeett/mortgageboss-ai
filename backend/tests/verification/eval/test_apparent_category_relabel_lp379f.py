"""LP-379-F — mapping Priya's free-text apparent_category labels onto the LP-379-E enum (proposed, disciplined).

The discipline these pin: a mapping is CONFIRMED only when the transaction DESCRIPTION supports it (the AI sees
the memo, not Priya's amount-based judgment); a generic "CARD PURCHASE / PAYMENT" memo is HELD (needs Priya),
never guessed; an uncertain note ("not sure it's own transfer") maps to `unknown`, held — a golden never more
certain than the labeler; and Priya's original free text in the committed worksheet is PRESERVED (the mapping
is a translation layer applied at scoring time, not a rewrite of her data).
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.verification.eval.apparent_category_relabel import _ENUM, relabel

_JUDGMENT = Path(__file__).resolve().parents[4] / "docs/calibration/lf6t3n-labels-judgment.csv"


# --------------------------------------------------------------------------- #
# CONFIRMED — only where the description supports the category
# --------------------------------------------------------------------------- #
def _assert(r, enum: str | None, confirmed: bool) -> None:
    assert r.enum == enum and r.confirmed == confirmed, r.rationale


def test_description_supported_labels_are_confirmed() -> None:
    _assert(relabel("payroll", "PAYROLL DIRECT DEPOSIT", "Akash's payroll"), "payroll", True)
    _assert(relabel("interest", "INTEREST EARNED", ""), "interest", True)
    _assert(
        relabel("transfer to own account", "ONLINE TRANSFER TO OWN ACCOUNT", ""),
        "transfer_own",
        True,
    )
    _assert(
        relabel("transfer", "INBOUND PAYMENT RECEIVED", "Ravi transferred to Akash"),
        "transfer_third_party_in",
        True,
    )


# --------------------------------------------------------------------------- #
# HELD — a generic memo carries no payee; the label is Priya's amount/judgment call
# --------------------------------------------------------------------------- #
def test_generic_card_memo_is_held_never_guessed() -> None:
    # the 30-row case: identical memo, many categories Priya inferred from AMOUNT — the AI cannot (and per the
    # prompt should not) reproduce that, so it is held, not scored.
    for free_text in (
        "Credit card payment",
        "Some kind of mortgage payment",
        "transfer to some one",
        "fee",
    ):
        r = relabel(free_text, "CARD PURCHASE / PAYMENT", "Must be American express CC payment")
        assert r.enum is None and r.confirmed is False


def test_ambiguous_typo_label_is_held() -> None:
    r = relabel(
        "big paymrny out", "ONLINE TRANSFER TO OWN ACCOUNT", "Make sure it is just one time"
    )
    assert r.enum is None and r.confirmed is False  # do not guess a typo'd label


# --------------------------------------------------------------------------- #
# UNCERTAINTY-PRESERVING — "not sure" → unknown, held (never a confident category)
# --------------------------------------------------------------------------- #
def test_uncertain_note_maps_to_unknown_and_is_held() -> None:
    r = relabel("transfer", "ONLINE TRANSFER FROM OWN ACCOUNT", "Not sure it is own transfer")
    assert (
        r.enum == "unknown" and r.confirmed is False
    )  # honest golden, not a confident transfer_own
    r2 = relabel(
        "transfer in", "ONLINE TRANSFER TO OWN ACCOUNT", "Not sure whether it is from own account"
    )
    assert r2.enum == "unknown" and r2.confirmed is False


def test_mapping_never_emits_an_off_enum_value() -> None:
    for ft, desc in [
        ("payroll", "PAYROLL DIRECT DEPOSIT"),
        ("transfer to some one", "CARD PURCHASE / PAYMENT"),
        ("Credit card bill", "CARD PURCHASE / PAYMENT"),
        ("transfer to own account", "ONLINE TRANSFER TO OWN ACCOUNT"),
    ]:
        r = relabel(ft, desc, "")
        assert r.enum is None or r.enum in _ENUM


# --------------------------------------------------------------------------- #
# PRESERVE HER WORDS — the mapping is a scoring-time layer, her committed labels are untouched
# --------------------------------------------------------------------------- #
def test_priyas_original_free_text_is_preserved_in_the_worksheet() -> None:
    goldens = {
        r["golden_label"].strip()
        for r in csv.DictReader(_JUDGMENT.open(encoding="utf-8"))
        if r["tag_id"] == "txn.apparent_category" and (r.get("golden_label") or "").strip()
    }
    # her free text is still there verbatim — the mapping did not rewrite her golden column
    assert {
        "transfer to some one",
        "Credit card payment",
        "Some kind of mortgage payment",
    } <= goldens
