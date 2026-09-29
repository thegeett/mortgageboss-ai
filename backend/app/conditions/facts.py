"""What code reads from a condition's own words (LP-919): numbers, accounts, dates, note meanings.

PRINCIPLE 1, ENFORCED HERE. The AI structures a condition; it never computes. Every figure a screen
shows as "computed by code" comes from this module, from the lender's text and the letter's header,
with `Decimal` arithmetic. An AI-returned amount that does not appear in the lender's text is dropped
by `reading.py`, not trusted.

Everything here is a pure function of strings and dates, so it is tested without a database or a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
#: `#9912`, `··9912`, `ending 9912`, `x9912` — a last four written next to an account.
_LAST4 = re.compile(r"(?:#|ending(?: in)?\s+|x{1,4}|··)\s?(\d{4})\b", re.IGNORECASE)
_BANKS = ("Capital One", "Chase", "Bank of America", "Wells Fargo", "Citibank", "PNC", "Truist")


def money_in(text: str) -> list[Decimal]:
    """Every dollar amount written in `text`, in order, as `Decimal`."""
    out: list[Decimal] = []
    for whole, cents in _MONEY.findall(text):
        out.append(Decimal(f"{whole.replace(',', '')}.{cents or '00'}"))
    return out


def money_is_in(amount: str, text: str) -> bool:
    """Whether an amount the AI returned is written in the lender's text (the only allowed source)."""
    found = money_in(amount)
    return bool(found) and found[0] in money_in(text)


def dates_in(text: str) -> list[date]:
    out: list[date] = []
    for month, day, year in _DATE.findall(text):
        try:
            out.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return out


def last4_in(text: str) -> str | None:
    match = _LAST4.search(text)
    return match.group(1) if match else None


def bank_in(text: str) -> str | None:
    lowered = text.lower()
    for bank in _BANKS:
        if bank.lower() in lowered:
            return bank
    return None


@dataclass(frozen=True)
class Shortfall:
    """7086's arithmetic: required minus verified, from the lender's own two figures."""

    required: Decimal
    verified: Decimal

    @property
    def amount(self) -> Decimal:
        return self.required - self.verified


_REQUIRED = re.compile(
    r"(?:total\s+)?funds\s+required\s+(?:are|is|of)\s+\$\s?([\d,]+\.\d{2})", re.I
)
_VERIFIED = re.compile(r"\$\s?([\d,]+\.\d{2})\s+currently\s+verified", re.I)


def shortfall_in(text: str) -> Shortfall | None:
    """The short-funds figures, when the text states both. None rather than a guess otherwise."""
    required = _REQUIRED.search(text)
    verified = _VERIFIED.search(text)
    if not required or not verified:
        return None
    return Shortfall(
        required=Decimal(required.group(1).replace(",", "")),
        verified=Decimal(verified.group(1).replace(",", "")),
    )


_NOT_EFFECTIVE_UNTIL = re.compile(r"not\s+effective\s+until\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)


@dataclass(frozen=True)
class DatePushBack:
    """6178's case: the policy starts on a date the letter says closing cannot precede."""

    must_not_close_before: date
    policy_starts: date


def date_push_back(text: str, must_not_close_before: date | None) -> DatePushBack | None:
    """A condition that only applies if closing is earlier than a date closing cannot be earlier than.

    Code, not AI (S3-06: "Both dates were read by code from the letter, not by AI"). Fires only when
    the text says the policy is not effective until a date ON OR BEFORE the letter's Must Not Close
    Before, so closing earlier than the policy is impossible and the "if closing is earlier" branch
    cannot apply.
    """
    if must_not_close_before is None:
        return None
    match = _NOT_EFFECTIVE_UNTIL.search(text)
    if not match:
        return None
    starts = dates_in(match.group(1))
    if not starts or starts[0] > must_not_close_before:
        return None
    return DatePushBack(must_not_close_before=must_not_close_before, policy_starts=starts[0])


#: What an underwriter note means, in the processor's words (plan §5 LP-919). Matched on the note's
#: text after its date; an unknown note has no meaning here rather than a guessed one.
NOTE_MEANINGS: dict[str, str] = {
    "not in upload": "The lender did not find it in the last upload — asked again below.",
    "not sufficient": "The lender looked at what was sent and it was not enough — asked again below.",
    "insufficient": "The lender looked at what was sent and it was not enough — asked again below.",
    "expired": "What was sent has expired — a newer one is needed.",
}


def note_meaning(note_text: str) -> str | None:
    lowered = note_text.lower()
    for phrase, meaning in NOTE_MEANINGS.items():
        if phrase in lowered:
            return meaning
    return None


def business_days_after(start: datetime | date, days: int) -> date:
    """`days` business days after `start` (Monday to Friday; US federal holidays not observed — see the ticket)."""
    current = start.date() if isinstance(start, datetime) else start
    added = 0
    while added < days:
        current = date.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            added += 1
    return current
