"""Is this condition sheet for this file? (LP-951, the staging trial's item 11.)

A sheet names its borrower and the lender's loan number in its title line (`LOAN APPROVAL CONDITIONS -
RIVERA - 1226500417`, read by `condition_drafts.letter_title`). The staging trial imported a sheet for
GURUNG onto a file for Patel without a word, and every draft that followed mixed two loans. So, before
import, code compares:

- **the borrower:** the sheet's surname against the file's borrowers' last names. Any match is a match,
  a co-borrower included; a hyphenated or two-word surname matches on any of its words.
- **the loan number:** the sheet's number against the numbers on the file's EARLIER imported sheets.
  The file stores no lender loan number of its own (no column, no extraction), so its first sheet has
  nothing to compare against and only the borrower is checked.

A fact the sheet or the file does not have is not a mismatch: nothing is refused on a missing value.

This WARNS; it never blocks for good. She can import anyway, and that choice is recorded as a round event
(`round_wrong_file_confirmed`) carrying which facts differed, never the names or numbers themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.borrower import Borrower
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.helpers import only_active
from app.services.condition_drafts import letter_title


@dataclass
class WrongFile:
    """What differs between a sheet and its file. Shown to her; never logged or stored."""

    sheet_surname: str | None = None
    file_surnames: list[str] = field(default_factory=list)
    sheet_loan_number: str | None = None
    file_loan_numbers: list[str] = field(default_factory=list)
    borrower_differs: bool = False
    loan_number_differs: bool = False


def _words(name: str) -> set[str]:
    return {word for word in re.split(r"[^a-z]+", name.casefold()) if word}


async def wrong_file_check(db: AsyncSession, *, round_: ConditionRound) -> WrongFile | None:
    """What on this sheet does not match its file, or None when nothing that can be compared differs."""
    surname, number = letter_title(round_.raw_text)
    if surname is None and number is None:
        return None

    last_names = [
        name
        for name in await db.scalars(
            only_active(
                select(Borrower.last_name)
                .where(Borrower.loan_file_id == round_.loan_file_id)
                .order_by(Borrower.created_at, Borrower.id),
                Borrower,
            )
        )
        if name
    ]
    borrower_differs = bool(
        surname and last_names and not any(_words(surname) & _words(last) for last in last_names)
    )

    earlier: list[str] = []
    for raw_text in await db.scalars(
        only_active(
            select(ConditionRound.raw_text)
            .where(
                ConditionRound.loan_file_id == round_.loan_file_id,
                ConditionRound.status == ConditionRoundStatus.IMPORTED,
                ConditionRound.id != round_.id,
            )
            .order_by(ConditionRound.created_at, ConditionRound.id),
            ConditionRound,
        )
    ):
        _, seen = letter_title(raw_text)
        if seen and seen not in earlier:
            earlier.append(seen)
    loan_number_differs = bool(number and earlier and number not in earlier)

    if not (borrower_differs or loan_number_differs):
        return None
    return WrongFile(
        sheet_surname=surname,
        file_surnames=last_names,
        sheet_loan_number=number,
        file_loan_numbers=earlier,
        borrower_differs=borrower_differs,
        loan_number_differs=loan_number_differs,
    )


def confirmed_event_detail(check: WrongFile) -> dict[str, bool]:
    """The override's event detail: WHICH facts differed, never the names or the numbers (NPI)."""
    return {
        "borrower_differs": check.borrower_differs,
        "loan_number_differs": check.loan_number_differs,
    }
