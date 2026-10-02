"""Is this condition sheet for this file? (LP-951, the staging trial's item 11.)

A sheet names its borrower and the lender's loan number in its text: UWM in its title line (`LOAN
APPROVAL CONDITIONS - RIVERA - 1226500417`, read by `condition_drafts.letter_title`), Champions on its
page header (`Date: 9/11/26 Loan #: 4400123456`, no borrower). The staging trial imported a sheet for
GURUNG onto a file for Patel without a word, and every draft that followed mixed two loans. So, before a
sheet becomes conditions, code compares:

- **the borrower:** the sheet's surname against the file's borrowers' last names. Any match is a match,
  a co-borrower included. Names are compared without accents, apostrophes or case, word by word and
  joined ("MUNOZ" is Muñoz, "OBRIEN" is O'Brien, "DELACRUZ" is De La Cruz, RIVERA is Rivera-Lopez), and
  a particle alone ("de", "la", "van") is not a match.
- **the loan number:** the sheet's number against the numbers on the file's EARLIER imported sheets.
  The file has no lender loan number of its own to compare with: no column on `loan_files`; the MISMO
  export's `LenderLoan` identifier falls to `catch_all` (not a column), and in the one real export it is
  8 digits where the UWM sheets print 10, so it is not the number a sheet prints (whether it ever is,
  is a question for the domain expert); the closing disclosure's `Loan ID #` and a lender-dashboard
  screenshot's loan number are extracted, but a CD normally arrives at closing, after the conditions.
  So a file's first sheet has nothing to compare against and only the borrower is checked.

WHAT IS NOT READ: a generic sheet or pasted text without UWM's title line or Champions' `Loan #:` has no
facts here, so nothing is compared for it.

A fact the sheet or the file does not have is not a mismatch: nothing is refused on a missing value.

TWO DOORS TURN A SHEET INTO CONDITIONS, AND BOTH ASK: the import route (a draft round's own text) and
`enrich_round_with_pdf` (a PDF attached or forwarded onto an existing round, which on an imported round
creates conditions directly and on a draft merges rows whose title the import never sees, because the
enrich discards the PDF's text).

This WARNS; it never blocks for good. She can go ahead anyway, and that choice is recorded as a round
event (`round_wrong_file_confirmed`) carrying which facts differed, never the names or numbers themselves.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.borrower import Borrower
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_round import ConditionRound, ConditionRoundStatus
from app.models.helpers import only_active
from app.services.condition_drafts import letter_title

#: Champions prints `Date: 9/11/26 Loan #: 4400123456` on every page. Digits with optional spaces or
#: dashes; compared as digits only.
_CHAMPIONS_LOAN = re.compile(r"\bLoan #:\s*(\d[\d -]{4,}\d)")

#: Words that are part of a surname but never identify one on their own ("De La Cruz" and "De Leon"
#: share "de"). A name made only of particles ("Le") is still matched whole.
_PARTICLES = frozenset({"de", "del", "della", "la", "las", "los", "le", "da", "das", "do", "dos",
                        "di", "du", "van", "von", "der", "den", "ter", "st", "san", "mc", "mac",
                        "al", "el", "bin", "ibn", "jr", "sr", "ii", "iii", "iv"})  # fmt: skip


@dataclass
class WrongFile:
    """What differs between a sheet and its file. Shown to her; never logged or stored."""

    sheet_surname: str | None = None
    file_surnames: list[str] = field(default_factory=list)
    sheet_loan_number: str | None = None
    file_loan_numbers: list[str] = field(default_factory=list)
    borrower_differs: bool = False
    loan_number_differs: bool = False


class WrongFileRefused(Exception):
    """A sheet that looks like another file's, sent without her confirmation (409, `wrong_file`)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


IMPORT_REFUSAL = (
    "This sheet does not look like this file's: its borrower or loan number does not match. Check it, "
    "and import only if it is this file's sheet."
)
ATTACH_REFUSAL = (
    "This PDF does not look like this file's: its borrower or loan number does not match. Check it, "
    "and attach it only if it is this file's sheet."
)


def sheet_facts(text: str | None) -> tuple[str | None, str | None]:
    """The sheet's surname and loan number: UWM's title line, else Champions' `Loan #:` (no name)."""
    surname, number = letter_title(text)
    if number is None:
        match = _CHAMPIONS_LOAN.search(text or "")
        if match:
            number = re.sub(r"\D", "", match.group(1))
    return surname, number


def _name_keys(name: str) -> set[str]:
    """Accents, apostrophes and case gone; its words without particles, plus the words joined."""
    plain = "".join(
        ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch)
    )
    plain = re.sub(r"['\u2019`]", "", plain.casefold())
    words = [word for word in re.split(r"[^a-z0-9]+", plain) if word]
    if not words:
        return set()
    return {word for word in words if word not in _PARTICLES} | {"".join(words)}


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


async def compare_sheet(
    db: AsyncSession,
    *,
    loan_file_id: UUID,
    text: str | None,
    exclude_round_id: UUID | None = None,
    also_numbers_from: Iterable[str | None] = (),
) -> WrongFile | None:
    """What in this sheet's `text` does not match the file, or None when nothing comparable differs.

    The file's numbers are those on its IMPORTED rounds (discarded drafts are not the file's), except
    `exclude_round_id`, plus any read from `also_numbers_from` (a round's own pasted text, on enrich).
    """
    surname, number = sheet_facts(text)
    if surname is None and number is None:
        return None

    last_names = _dedupe(
        name
        for name in await db.scalars(
            only_active(
                select(Borrower.last_name)
                .where(Borrower.loan_file_id == loan_file_id)
                .order_by(Borrower.created_at, Borrower.id),
                Borrower,
            )
        )
        if name and _name_keys(name)
    )
    borrower_differs = bool(
        surname
        and _name_keys(surname)
        and last_names
        and not any(_name_keys(surname) & _name_keys(last) for last in last_names)
    )

    query = select(ConditionRound.raw_text).where(
        ConditionRound.loan_file_id == loan_file_id,
        ConditionRound.status == ConditionRoundStatus.IMPORTED,
    )
    if exclude_round_id is not None:
        query = query.where(ConditionRound.id != exclude_round_id)
    texts = list(
        await db.scalars(
            only_active(
                query.order_by(ConditionRound.created_at, ConditionRound.id), ConditionRound
            )
        )
    )
    earlier = _dedupe(
        seen for seen in (sheet_facts(raw)[1] for raw in [*texts, *also_numbers_from]) if seen
    )
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


async def wrong_file_check(db: AsyncSession, *, round_: ConditionRound) -> WrongFile | None:
    """A draft round's own sheet against its file (the import door)."""
    return await compare_sheet(
        db, loan_file_id=round_.loan_file_id, text=round_.raw_text, exclude_round_id=round_.id
    )


def confirmed_event_detail(check: WrongFile) -> dict[str, bool]:
    """The override's event detail: WHICH facts differed, never the names or the numbers (NPI)."""
    return {
        "borrower_differs": check.borrower_differs,
        "loan_number_differs": check.loan_number_differs,
    }


def record_confirmation(
    db: AsyncSession, *, round_: ConditionRound, check: WrongFile, actor_user_id: UUID | None
) -> None:
    """Her override, as a round event. The caller owns the transaction."""
    db.add(
        ConditionEvent(
            company_id=round_.company_id,
            loan_file_id=round_.loan_file_id,
            round_id=round_.id,
            condition_id=None,
            kind=ConditionEventKind.ROUND_WRONG_FILE_CONFIRMED,
            actor_user_id=actor_user_id,
            detail=confirmed_event_detail(check),
        )
    )
