"""Asking people (LP-922): the round's draft emails, built from the plan, sent by nobody but her.

WHAT THIS MAKES. At plan confirm, one ask draft per recipient holding every open ask item of the round
(the borrower, the title company / attorney, the LO, …) and one question per push-back or
ask-the-underwriter condition. An unsent draft to the same recipient takes new items rather than a
second draft being made — "one email per third party, accumulating".

PHASE 4'S MESSAGE, AS IT IS. Each draft is a `Communication` (status `draft`); "Mark as sent" is Phase
4's `send_draft` (the record, the needs' reminder clock, `communication_sent`, the evidence row — and no
transmission, because no transport is connected). This module adds what Phase 4 does not know: which
conditions a draft is for, the words, and our status moving to Waiting when she marks it sent.

THE WORDS ARE THE LIBRARY'S, FILLED BY CODE. Every figure, date, account ending and loan number comes
from the reading's specifics or the letter, never from a model. A template whose placeholder has no
value falls back to the item's own name and acceptable form rather than printing a hole. Last four only.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.communications.sanitise import sanitise_html
from app.conditions.library import ConditionType, LibraryItem, load_library
from app.documents.display_names import in_sentence
from app.models.borrower import Borrower
from app.models.communication import (
    BodyFormat,
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
)
from app.models.communication_needs_item import CommunicationNeedsItem
from app.models.company import Company
from app.models.condition import (
    BucketKind,
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
    OwnerHint,
)
from app.models.condition_draft import ConditionDraft, DraftRecipient
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound
from app.models.condition_vocabulary import ConditionItemStatus, Performer, PlanOption
from app.models.lender import Lender
from app.models.lender_contact import LenderContact, LenderContactRole
from app.models.loan_file import LoanFile
from app.models.loan_file_participant import ParticipantRole
from app.models.needs_item import NeedsItem
from app.models.property import Property
from app.models.user import User

logger = structlog.get_logger(__name__)

TEMPLATE_ASK = "condition_request"
TEMPLATE_QUESTION = "condition_question"
TEMPLATE_VERSION = "v1"

_ASKS = frozenset({PlanOption.ASK_BORROWER, PlanOption.ASK_THIRD_PARTY})
_QUESTIONS = frozenset({PlanOption.PUSH_BACK, PlanOption.ASK_UNDERWRITER})
_LIVE_ITEM = frozenset({ConditionItemStatus.OPEN, ConditionItemStatus.REQUESTED})
#: An ask still to be answered, as S3-01 counts one: neither dropped nor done.
_OPEN_ASK = frozenset(
    {ConditionItemStatus.OPEN, ConditionItemStatus.REQUESTED, ConditionItemStatus.RECEIVED}
)

if TYPE_CHECKING:
    from app.services.condition_plan import AskShape


class AskItemShape(Protocol):
    """An item as `waiting_on_when_sent` reads it: its routing, and whether it is still open."""

    @property
    def option(self) -> PlanOption: ...
    @property
    def performer(self) -> Performer: ...
    @property
    def performers(self) -> Sequence[str]: ...
    @property
    def status(self) -> ConditionItemStatus: ...
    @property
    def draft(self) -> Any: ...


#: `condition_plan.recipient_for`'s keys, as stored.
_RECIPIENT_KEY: dict[str, DraftRecipient] = {member.value: member for member in DraftRecipient}

#: Who we wait on once a draft to this recipient is marked sent (Stage 2's owners; M5: LO = broker).
WAITING_ON: dict[DraftRecipient, OwnerHint] = {
    DraftRecipient.BORROWER: OwnerHint.BORROWER,
    DraftRecipient.TITLE_ATTORNEY: OwnerHint.TITLE,
    DraftRecipient.LO: OwnerHint.BROKER,
    DraftRecipient.INSURANCE: OwnerHint.INSURANCE,
    DraftRecipient.UNDERWRITER: OwnerHint.LENDER,
    DraftRecipient.LENDER: OwnerHint.LENDER,
    DraftRecipient.HOA: OwnerHint.UNKNOWN,
    DraftRecipient.EMPLOYER: OwnerHint.UNKNOWN,
    DraftRecipient.OTHER_PARTY: OwnerHint.UNKNOWN,
}

#: Where a missing address is remembered: a file participant of this role (Phase 4's
#: `add_participant`). The LO's lives on the file itself.
PARTICIPANT_ROLE: dict[DraftRecipient, ParticipantRole] = {
    DraftRecipient.BORROWER: ParticipantRole.BORROWER,
    DraftRecipient.TITLE_ATTORNEY: ParticipantRole.TITLE,
    DraftRecipient.INSURANCE: ParticipantRole.INSURER,
    DraftRecipient.EMPLOYER: ParticipantRole.EMPLOYER,
    DraftRecipient.HOA: ParticipantRole.OTHER,
    DraftRecipient.OTHER_PARTY: ParticipantRole.OTHER,
    DraftRecipient.UNDERWRITER: ParticipantRole.UNDERWRITER,
    # LP-942: an address she types for the lender is remembered on the lender side too. SHARED with the
    # underwriter question (as HOA and OTHER_PARTY share OTHER): an address typed on a question to the
    # underwriter overwrites it, one way only, and matters only when the lender has no contacts. It is read
    # only after the lender's own contacts (`_lender_address`).
    DraftRecipient.LENDER: ParticipantRole.UNDERWRITER,
}

#: The dialog's title (S3-04, S3-05), before " · round N".
TITLE: dict[DraftRecipient, str] = {
    DraftRecipient.BORROWER: "Email to the borrower",
    DraftRecipient.TITLE_ATTORNEY: "Email to the title company / attorney",
    DraftRecipient.LO: "Email to the loan officer",
    DraftRecipient.INSURANCE: "Email to the insurance agent",
    DraftRecipient.HOA: "Email to the HOA",
    DraftRecipient.EMPLOYER: "Email to the employer",
    DraftRecipient.OTHER_PARTY: "Email to the other party",
    DraftRecipient.UNDERWRITER: "Question to the underwriter",
    DraftRecipient.LENDER: "Email to the lender",
}

#: How S3-05's "Other drafts this round" names a recipient.
SHORT_LABEL: dict[DraftRecipient, str] = {
    DraftRecipient.BORROWER: "Borrower",
    DraftRecipient.TITLE_ATTORNEY: "Title/attorney",
    DraftRecipient.LO: "LO",
    DraftRecipient.INSURANCE: "Insurance agent",
    DraftRecipient.HOA: "HOA",
    DraftRecipient.EMPLOYER: "Employer",
    DraftRecipient.OTHER_PARTY: "Other party",
    DraftRecipient.UNDERWRITER: "Underwriter",
    DraftRecipient.LENDER: "Lender",
}

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_TITLE_LINE = re.compile(
    r"LOAN APPROVAL CONDITIONS\s*-\s*(?P<surname>[^-\n]+?)\s*-\s*(?P<number>\d{6,})", re.I
)


class DraftRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------------------------- #
# Facts from the letter and the file — read by code
# --------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LetterFacts:
    """What the emails name about the loan. Every field is read by code from the letter or the file."""

    surname: str | None
    loan_number: str | None
    lender_short: str
    property_line: str | None
    mortgagee_clause: str | None
    must_not_close_before: date | None
    #: `(name, role)` of the underwriter the letter names — `UW II` first, else `Senior UW`.
    underwriter: tuple[str, str] | None


def letter_title(raw_text: str | None) -> tuple[str | None, str | None]:
    """`LOAN APPROVAL CONDITIONS - RIVERA - 1226500417` → `("RIVERA", "1226500417")`."""
    match = _TITLE_LINE.search(raw_text or "")
    if not match:
        return None, None
    return match.group("surname").strip().upper(), match.group("number")


def _underwriter(header: dict[str, Any] | None) -> tuple[str, str] | None:
    team = (header or {}).get("lender_team") or []
    for role in ("UW II", "Senior UW", "UW"):
        for member in team:
            if isinstance(member, dict) and member.get("role") == role and member.get("name"):
                return str(member["name"]), role
    return None


def _first_word(name: str) -> str:
    return name.split()[0] if name.split() else name


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def money_short(value: Decimal) -> str:
    """`$2,850` for a whole amount, `$2,850.50` otherwise — S3-04's "the $2,850 earnest money"."""
    text = money(value)
    return text[:-3] if text.endswith(".00") else text


def long_date(value: date) -> str:
    """`Thursday, September 3` — S3-04's due date."""
    return f"{value.strftime('%A')}, {_MONTHS[value.month - 1]} {value.day}"


def us_date(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def months_phrase(months: list[str]) -> str | None:
    """`["2026-07", "2026-08"]` → `July and August 2026`."""
    parsed: list[tuple[int, int]] = []
    for month in sorted(set(months)):
        try:
            year, number = (int(part) for part in month.split("-"))
        except ValueError:
            continue
        parsed.append((year, number))
    if not parsed:
        return None
    if len({year for year, _ in parsed}) == 1:
        names = [_MONTHS[number - 1] for _, number in parsed]
        joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
        return f"{joined} {parsed[0][0]}"
    return " and ".join(f"{_MONTHS[number - 1]} {year}" for year, number in parsed)


# --------------------------------------------------------------------------------------------- #
# The words
# --------------------------------------------------------------------------------------------- #


def fill(template: str, values: dict[str, str | None]) -> str | None:
    """Fill a library template, HTML-escaped, `**…**` as bold. None when a placeholder has no value."""
    needed = set(_PLACEHOLDER.findall(template))
    if any(not values.get(name) for name in needed):
        return None
    escaped = html.escape(template, quote=False)
    for name in needed:
        escaped = escaped.replace("{" + name + "}", html.escape(values[name] or "", quote=False))
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


#: LP-950 — a run of digits (hyphen-joined groups count as one run) that is not a dollar figure, a
#: decimal or part of a word. Five or more digits is an account-shaped number: the same line the
#: privacy test draws ("no long digit run" outside the loan number).
_DIGIT_RUN = re.compile(r"(?<![\w$.,])\d+(?:-\d+)*(?![\w,])")


def mask_accounts(text: str, *, keep: str | None = None) -> str:
    """Every account-shaped number in the lender's words, masked to its last four (LP-950).

    Code, never the model. `keep` is the lender's loan number, which the emails already print in full
    and which a reader needs whole. Dollar figures (`$2,850.00`) and dates (`09/30/2026`) are not runs
    of five digits and pass unchanged.
    """

    def masked(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 5 or (keep is not None and digits == re.sub(r"\D", "", keep)):
            return match.group(0)
        return f"****{digits[-4:]}"

    return _DIGIT_RUN.sub(masked, text)


def lender_words(condition: Condition, letter: LetterFacts) -> str:
    """The lender's own words for a condition, as an email may quote them: the "TC:" marker dropped,
    the closing full stop dropped, and every account number masked to its last four."""
    words = re.sub(r"^\s*TC:\s*", "", condition.verbatim_text or "").strip().rstrip(".")
    return mask_accounts(words, keep=letter.loan_number)


def _plain_line(condition: Condition, item: ConditionItem, letter: LetterFacts) -> str:
    """A line with no library wording: the item's own acceptable form, or THE LENDER'S WORDS.

    LP-950 — a generic item (no library type) carries placeholders, `GENERIC_NAME` and
    `GENERIC_ACCEPTABLE`. Neither may reach a reader outside the app: the title company was told
    "Final inspection — what the lender's words describe" and nothing else (staging trial, item 2). So a
    placeholder, or an empty acceptable form, is replaced by what the lender actually wrote.
    """
    from app.services.condition_reading import GENERIC_ACCEPTABLE, GENERIC_NAME

    words = html.escape(lender_words(condition, letter), quote=False)
    name = html.escape(item.name, quote=False) if item.name and item.name != GENERIC_NAME else ""
    acceptable = (item.acceptable or "").strip().rstrip(".")
    if acceptable and acceptable != GENERIC_ACCEPTABLE.rstrip("."):
        detail = html.escape(acceptable, quote=False)
        detail = f"{detail[0].lower()}{detail[1:]}"
    else:
        detail = f"as the lender wrote it: “{words}”" if words else ""
    if not name:
        return f"<strong>{words}</strong>." if words else "The lender's condition."
    return f"<strong>{name}</strong> — {detail}." if detail else f"<strong>{name}</strong>."


def _amount(condition: Condition, item: ConditionItem | None) -> Decimal | None:
    """The amount a line names: this item's, else a sibling item's in the reading, else the first
    dollar figure in the lender's own words. Code, never the model."""
    candidates: list[Any] = list(
        ((item.specifics or {}) if item is not None else {}).get("amounts") or []
    )
    for read in (condition.reading or {}).get("items") or []:
        candidates.extend(((read or {}).get("specifics") or {}).get("amounts") or [])
    for candidate in candidates:
        value = _decimal(candidate)
        if value is not None:
            return value
    from app.conditions.facts import money_in

    found = money_in(condition.verbatim_text or "")
    return found[0] if found else None


def _values(
    condition: Condition, item: ConditionItem | None, letter: LetterFacts
) -> dict[str, str | None]:
    """The placeholder values for one item of one condition. Code only."""
    amount = _amount(condition, item)
    shortfall = ((condition.reading or {}).get("figures") or {}).get("shortfall") or {}
    required = _decimal(shortfall.get("required"))
    verified = _decimal(shortfall.get("verified"))
    instruction = lender_words(condition, letter)
    return {
        "amount": money(amount) if amount is not None else None,
        "amount_short": money_short(amount) if amount is not None else None,
        "loan_number": letter.loan_number,
        "required": money(required) if required is not None else None,
        "verified": money(verified) if verified is not None else None,
        "instruction": instruction or None,
    }


@dataclass
class Line:
    """One numbered line of an email: the words, the Why, and the conditions it answers."""

    body: str
    why: str | None = None
    codes: list[str] = field(default_factory=list)


def _library_item(
    condition: Condition, item: ConditionItem
) -> tuple[ConditionType | None, LibraryItem | None]:
    library_type = load_library().get(condition.canonical_type_id)
    if library_type is None:
        return None, None
    return library_type, next((each for each in library_type.items if each.key == item.key), None)


def _item_line(condition: Condition, item: ConditionItem, letter: LetterFacts) -> str:
    _, library_item = _library_item(condition, item)
    line = None
    if library_item is not None and library_item.email:
        line = fill(library_item.email, _values(condition, item, letter))
    line = line or _plain_line(condition, item, letter)
    # "(needed before funding)" (S3-05's 1947): a prior-to-funding item asked early says so.
    if _before_funding(condition, [item]) and line.endswith("."):
        line = f"{line[:-1]} (needed before funding)."
    return line


def _statement_line(items: list[ConditionItem]) -> str | None:
    """S3-04 item 1: the shared statements need as one line, from the items' specifics."""
    banks = {(item.specifics or {}).get("account_bank") for item in items}
    last4s = {(item.specifics or {}).get("account_last4") for item in items}
    if len(banks) != 1 or len(last4s) != 1:
        return None
    bank, last4 = next(iter(banks)), next(iter(last4s))
    if (
        not bank
        or not last4
        or not all("bank_statement" in (item.documents or []) for item in items)
    ):
        return None
    months = [str(m) for m in ((item.specifics or {}).get("month") for item in items) if m]
    phrase = months_phrase(months)
    noun = "statements" if len(set(months)) != 1 else "statement"
    what = f"Your {bank} {noun} ending {last4}" + (f" for {phrase}" if phrase else "")
    return (
        f"<strong>{html.escape(what, quote=False)}</strong> — all pages, downloaded as PDFs from "
        f"{html.escape(bank, quote=False)}'s website (not screenshots)."
    )


def _join(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])}, and {words[-1]}" if len(words) > 2 else " and ".join(words)


def _why(pairs: list[tuple[Condition, ConditionItem]], letter: LetterFacts) -> str | None:
    """The grey Why: line. An item's own sentence when every item has one; else the types' phrases."""
    own = []
    for condition, item in pairs:
        _, library_item = _library_item(condition, item)
        sentence = (
            fill(library_item.why, _values(condition, item, letter))
            if library_item is not None and library_item.why
            else None
        )
        own.append(sentence)
    if own and all(own):
        return own[0]
    phrases: list[str] = []
    seen: set[UUID] = set()
    for condition, item in pairs:
        if condition.id in seen:
            continue
        seen.add(condition.id)
        library_type, _ = _library_item(condition, item)
        phrase = (
            fill(library_type.why, _values(condition, item, letter))
            if library_type is not None and library_type.why
            else None
        )
        if phrase:
            phrases.append(phrase)
    return f"the lender needs to see {_join(phrases)}." if phrases else None


def borrower_lines(pairs: list[tuple[Condition, ConditionItem]], letter: LetterFacts) -> list[Line]:
    """One line per NEED (§4a change 2): items sharing a need are asked for once."""
    groups: dict[Any, list[tuple[Condition, ConditionItem]]] = {}
    for condition, item in pairs:
        groups.setdefault(item.need_id or item.id, []).append((condition, item))
    lines: list[Line] = []
    for members in groups.values():
        items = [item for _, item in members]
        body = (_statement_line(items) if len(members) > 1 else None) or _item_line(
            members[0][0], members[0][1], letter
        )
        codes = list(dict.fromkeys(condition.lender_code or "—" for condition, _ in members))
        lines.append(Line(body=body, why=_why(members, letter), codes=codes))
    return _one_line_per_wording(lines)


def party_lines(pairs: list[tuple[Condition, ConditionItem]], letter: LetterFacts) -> list[Line]:
    lines: list[Line] = []
    for condition, item in pairs:
        body = _item_line(condition, item, letter)
        # THE INSURANCE EMAIL CARRIES THE CLAUSE, exactly as the letter prints it (README S3-05).
        if item.performer is Performer.INSURANCE and letter.mortgagee_clause:
            body += f"<br>Mortgagee clause: {html.escape(letter.mortgagee_clause, quote=False)}"
        lines.append(Line(body=body, codes=[condition.lender_code or "—"]))
    return _one_line_per_wording(lines)


def lender_lines(pairs: list[tuple[Condition, ConditionItem]], letter: LetterFacts) -> list[Line]:
    """LP-950 — the lender email's lines are REQUESTS: the lender is asked to act, never told what
    it needs. An appraiser's item (routed to the lender, LP-942) is an order; anything else the lender
    holds is asked for. The detail is the library's acceptable form, else the lender's own words."""
    from app.services.condition_reading import GENERIC_ACCEPTABLE, GENERIC_NAME

    lines: list[Line] = []
    for condition, item in pairs:
        _, library_item = _library_item(condition, item)
        name = (library_item.name if library_item else item.name) or ""
        if name == GENERIC_NAME:
            name = ""
        acceptable = (library_item.acceptable if library_item else item.acceptable) or ""
        if acceptable.rstrip(".") == GENERIC_ACCEPTABLE.rstrip("."):
            acceptable = ""
        performers = [Performer(p) for p in item.performers] or [item.performer]
        verb = "Please order" if Performer.APPRAISER in performers else "Please provide"
        what = name[:1].lower() + name[1:] if name else ""
        words = lender_words(condition, letter)
        detail = acceptable.rstrip(".") if acceptable else (f"“{words}”" if words else "")
        if detail and acceptable:
            detail = detail[:1].lower() + detail[1:]
        head = f"{verb} the {what}" if what else verb
        body = f"<strong>{html.escape(head, quote=False)}</strong>"
        if detail:
            body += f" — {html.escape(detail, quote=False)}"
        lines.append(Line(body=f"{body}.", codes=[condition.lender_code or "—"]))
    return _one_line_per_wording(lines)


def _one_line_per_wording(lines: list[Line]) -> list[Line]:
    """LP-950 — two lines with the same words become one, carrying both codes.

    A condition read without a type can split into several generic items, and each quotes the lender's
    whole condition; the staging trial's 7086 printed the same paragraph twice in one email. The first
    line keeps its place and its Why; a later identical body only adds its codes.
    """
    kept: dict[str, Line] = {}
    for line in lines:
        same = kept.get(line.body)
        if same is None:
            kept[line.body] = Line(body=line.body, why=line.why, codes=list(line.codes))
            continue
        same.codes.extend(code for code in line.codes if code not in same.codes)
    return list(kept.values())


def _ol(lines: list[Line]) -> str:
    rows = []
    for line in lines:
        why = f"<br><em>Why: {line.why}</em>" if line.why else ""
        rows.append(f"<li>{line.body}{why}</li>")
    return f"<ol>{''.join(rows)}</ol>"


def _signature(signer: str, company: str) -> str:
    return f"<p>Thank you,<br>{html.escape(signer, quote=False)} · {html.escape(company, quote=False)}</p>"


def render_borrower(
    *,
    first_name: str | None,
    lines: list[Line],
    due: date | None,
    upload_url: str | None,
    signer: str,
    company: str,
) -> tuple[str, str]:
    """S3-04. `(subject, html)`."""
    count = len(lines)
    subject = f"Documents needed for your loan — {count} item{'s' if count != 1 else ''}"
    greeting = f"Hi {html.escape(first_name, quote=False)}," if first_name else "Hello,"
    by = f" by <strong>{long_date(due)}</strong>" if due else ""
    upload = (
        f'<p>Upload them here: <a href="{html.escape(upload_url)}">Secure upload link for your '
        "loan</a> (it lists exactly what we need).</p>"
        if upload_url
        else ""
    )
    body = (
        f"<p>{greeting}</p>"
        "<p>The lender approved your loan with a few conditions. To keep your closing on track, "
        f"please send the items below{by}.</p>"
        f"{_ol(lines)}{upload}{_signature(signer, company)}"
    )
    return subject, body


def _file_name(letter: LetterFacts, *, with_lender: bool) -> str:
    parts = [letter.surname or "Your loan"]
    if letter.loan_number:
        parts.append(
            f"{letter.lender_short} loan {letter.loan_number}"
            if with_lender
            else letter.loan_number
        )
    return " · ".join(parts)


def render_party(
    *,
    greeting_name: str | None,
    lines: list[Line],
    letter: LetterFacts,
    signer: str,
    company: str,
) -> tuple[str, str]:
    """S3-05 (and the LO's, insurance's …). `(subject, html)`."""
    subject = " ".join(p for p in (letter.surname, letter.loan_number) if p) or "Your loan"
    subject = f"{subject} — items for closing"
    greeting = f"Hi {html.escape(greeting_name, quote=False)}," if greeting_name else "Hello,"
    where = f" ({html.escape(letter.property_line, quote=False)})" if letter.property_line else ""
    body = (
        f"<p>{greeting}</p>"
        f"<p>For <strong>{html.escape(_file_name(letter, with_lender=True), quote=False)}</strong>"
        f"{where}, the lender needs the following:</p>"
        f"{_ol(lines)}{_signature(signer, company)}"
    )
    return subject, body


def render_lender(
    *,
    greeting_name: str | None,
    lines: list[Line],
    letter: LetterFacts,
    signer: str,
    company: str,
    request: str | None,
) -> tuple[str, str]:
    """LP-950 — the email TO the lender (LP-942's draft): requests, never "the lender needs".

    `request` names the one thing asked for when there is one ("final inspection"); the subject says
    it, so the lender's inbox shows what is wanted. Several requests read "N requests".
    """
    head = " ".join(p for p in (letter.surname, letter.loan_number) if p) or "Our loan"
    count = len(lines)
    what = (
        f"{request} request"
        if request and count == 1
        else f"{count} request" + ("" if count == 1 else "s")
    )
    subject = f"{head} — {what}"
    greeting = f"Hi {html.escape(greeting_name, quote=False)}," if greeting_name else "Hello,"
    where = f" ({html.escape(letter.property_line, quote=False)})" if letter.property_line else ""
    loan = html.escape(_file_name(letter, with_lender=False), quote=False)
    asking = "Could you help with this" if len(lines) == 1 else "Could you help with these"
    body = (
        f"<p>{greeting}</p>"
        f"<p>For <strong>{loan}</strong>{where}. {asking}?</p>"
        f"{_ol(lines)}{_signature(signer, company)}"
    )
    return subject, body


def render_question(
    *,
    condition: Condition,
    short: str,
    greeting_name: str | None,
    letter: LetterFacts,
    signer: str,
    company: str,
) -> tuple[str, str]:
    """S3-06. The date push-back states both dates; any other question states the reading."""
    code = html.escape(condition.lender_code or "this condition", quote=False)
    subject = " ".join(p for p in (letter.surname, letter.loan_number) if p) or "Your loan"
    subject = f"{subject} — condition {condition.lender_code or ''}".rstrip()
    greeting = f"Hi {html.escape(greeting_name, quote=False)}," if greeting_name else "Hello,"
    about = html.escape(short[:1].lower() + short[1:], quote=False) if short else ""
    opening = (
        f"<p>Question on <strong>{html.escape(_file_name(letter, with_lender=False), quote=False)}"
        f"</strong>, condition <strong>{code}</strong>" + (f" ({about})" if about else "") + ".</p>"
    )
    push_back = (condition.reading or {}).get("push_back") or {}
    mncb = _iso_date(push_back.get("must_not_close_before"))
    starts = _iso_date(push_back.get("policy_starts"))
    if condition.next_step is PlanOption.PUSH_BACK and mncb and starts:
        middle = (
            f"<p>The approval shows <strong>Must Not Close Before {us_date(mncb)}</strong>, and the "
            f"HOI policy provided is effective <strong>{us_date(starts)}</strong>. Since closing "
            'cannot be before the policy starts, the "current policy if closing is earlier" part '
            "should not apply.</p>"
            f"<p>Could you clear {code}, or let me know what else you need?</p>"
        )
    else:
        summary = html.escape(
            mask_accounts(
                str((condition.reading or {}).get("summary") or ""), keep=letter.loan_number
            ),
            quote=False,
        )
        middle = (f"<p>{summary}</p>" if summary else "") + (
            f"<p>Could you let me know what you need to clear {code}?</p>"
        )
    return subject, f"<p>{greeting}</p>{opening}{middle}{_signature(signer, company)}"


def _iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------- #
# Building and keeping the round's drafts
# --------------------------------------------------------------------------------------------- #


def recipient_key(item: AskShape) -> DraftRecipient | None:
    """The email an ask item goes into — `condition_plan.recipient_for`, as a stored value."""
    from app.services.condition_plan import recipient_for

    found = recipient_for(item)
    return _RECIPIENT_KEY.get(found[0]) if found else None


def first_asked_owner(
    items: Sequence[Any], gone: Callable[[Any], DraftRecipient | None]
) -> OwnerHint | None:
    """S3-12's rule: the condition waits on the recipient of its FIRST ask, in item order, whose
    email has gone (`gone` says which recipient's email that was, or None). Dropped items do not
    count. ONE function, called by the move (`_wait_on_first_asked`, with the emails really sent) and
    by the prediction (`waiting_on_when_sent`, with the named email treated as sent) — LP-947 review.

    THE NOT_NEEDED SKIP IS DEAD FOR ONE CALLER AND LOAD-BEARING FOR THE OTHER. The move's items come
    from `_condition_items`, which already leaves dropped items out; the prediction's come from the
    payload (`_items_by_condition`), which keeps them. Removing the skip because it looks dead from
    the move breaks the prediction (`test_a_dropped_ask_decides_nothing_even_if_its_email_went`).
    """
    for item in items:
        if item.status is ConditionItemStatus.NOT_NEEDED or item.option not in _ASKS:
            continue
        recipient = gone(item)
        if recipient is not None:
            return WAITING_ON[recipient]
    return None


def waiting_on_when_sent(
    next_step: PlanOption | None, items: Sequence[AskItemShape]
) -> OwnerHint | None:
    """LP-947 — who the condition will be Waiting on when its NEXT email is marked sent, which S3-01's
    "Becomes Waiting on Borrower when the borrower email is marked sent" line renders.

    The email the sentence names is the first OPEN ask's (the client's `askRecipients(…)[0]`). The
    prediction is the move's own rule (`first_asked_owner`) with that email treated as sent, beside
    any already sent, so the two cannot drift: it is the rule, run one send ahead. A question to the
    underwriter waits on the lender. `None` when nothing will be sent.
    """
    if next_step in _QUESTIONS:
        return WAITING_ON[DraftRecipient.UNDERWRITER]
    # `recipient_key` is None for anything that is not an ask (her task, already in the file).
    named = next(
        (key for item in items if item.status in _OPEN_ASK and (key := recipient_key(item))), None
    )
    if named is None:
        return None

    def gone(item: AskItemShape) -> DraftRecipient | None:
        key = recipient_key(item)
        already = item.draft is not None and item.draft.status == "sent"
        return key if key == named or already else None

    return first_asked_owner(items, gone)


async def letter_facts(
    db: AsyncSession, *, loan_file: LoanFile, round_: ConditionRound | None
) -> LetterFacts:
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    header = (round_.header if round_ is not None else None) or {}
    surname, number = letter_title(round_.raw_text if round_ is not None else None)
    prop = (
        await db.execute(select(Property).where(Property.loan_file_id == loan_file.id).limit(1))
    ).scalar_one_or_none()
    property_line = None
    if prop is not None and prop.address_line:
        property_line = ", ".join(p for p in (prop.address_line, prop.city, prop.state) if p)
    from app.services.condition_reading import _must_not_close_before

    short = (lender.canonical_lender_key or "").upper() if lender is not None else ""
    return LetterFacts(
        surname=surname,
        loan_number=number,
        lender_short=short or (lender.name if lender is not None else "Lender"),
        property_line=property_line,
        mortgagee_clause=header.get("mortgagee_clause")
        or (lender.mortgagee_clause if lender is not None else None),
        must_not_close_before=_must_not_close_before(round_) if round_ is not None else None,
        underwriter=_underwriter(header),
    )


async def _address(
    db: AsyncSession, *, loan_file: LoanFile, recipient: DraftRecipient, letter: LetterFacts
) -> tuple[str | None, str | None]:
    """`(email, display name)` for a recipient, from what the file already knows. Code only."""
    from app.services.party_requests import party_addresses

    if recipient is DraftRecipient.LO:
        return loan_file.loan_officer_email, loan_file.loan_officer_name
    if recipient is DraftRecipient.BORROWER:
        from app.services.email_draft import primary_borrower

        borrower: Borrower | None = await primary_borrower(db, loan_file_id=loan_file.id)
        known = (await party_addresses(db, loan_file=loan_file)).get(ParticipantRole.BORROWER)
        name = borrower.full_name if borrower is not None else None
        email = (borrower.email if borrower is not None else None) or (known[0] if known else None)
        return email, name
    if recipient is DraftRecipient.UNDERWRITER:
        return await _underwriter_address(db, loan_file=loan_file, letter=letter)
    if recipient is DraftRecipient.LENDER:
        return await _lender_address(db, loan_file=loan_file)
    known = (await party_addresses(db, loan_file=loan_file)).get(PARTICIPANT_ROLE[recipient])
    return (known[0], known[1]) if known else (None, None)


async def _lender_address(
    db: AsyncSession, *, loan_file: LoanFile
) -> tuple[str | None, str | None]:
    """LP-942 — the lender's own contacts: the account executive first, then any active contact, then
    the lender's contact email, then an address she typed for it before. Code only."""
    from app.services.party_requests import party_addresses

    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    if lender is not None:
        contacts = list(
            (
                await db.execute(
                    select(LenderContact).where(
                        LenderContact.lender_id == lender.id,
                        LenderContact.is_active.is_(True),
                        LenderContact.email.is_not(None),
                    )
                )
            ).scalars()
        )
        contacts.sort(key=lambda c: c.role is not LenderContactRole.ACCOUNT_EXECUTIVE)
        if contacts:
            return contacts[0].email, contacts[0].name
        if lender.contact_email:
            return lender.contact_email, lender.name
    known = (await party_addresses(db, loan_file=loan_file)).get(ParticipantRole.UNDERWRITER)
    return (known[0], known[1]) if known else (None, None)


async def _underwriter_address(
    db: AsyncSession, *, loan_file: LoanFile, letter: LetterFacts
) -> tuple[str | None, str | None]:
    """The letter's underwriter, addressed from the lender's contacts (S3-06: "Lena Brennan (UW II)")."""
    named = letter.underwriter
    display = f"{named[0]} ({named[1]})" if named else None
    contacts: list[LenderContact] = []
    if loan_file.lender_id:
        contacts = list(
            (
                await db.execute(
                    select(LenderContact).where(
                        LenderContact.lender_id == loan_file.lender_id,
                        LenderContact.is_active.is_(True),
                        LenderContact.role == LenderContactRole.UNDERWRITER,
                    )
                )
            ).scalars()
        )
    if named:
        for contact in contacts:
            if contact.name and contact.name.strip().lower() == named[0].lower() and contact.email:
                return contact.email, display
    if loan_file.underwriter_contact_id:
        assigned = await db.get(LenderContact, loan_file.underwriter_contact_id)
        if assigned is not None and assigned.email:
            return assigned.email, display or assigned.name
    lender = await db.get(Lender, loan_file.lender_id) if loan_file.lender_id else None
    return (lender.contact_email if lender is not None else None), display


def _to_line(email: str | None, name: str | None) -> str:
    if email and name:
        return f"{name} <{email}>"
    return email or ""


async def _signer(
    db: AsyncSession, *, loan_file: LoanFile, actor_user_id: UUID | None
) -> tuple[str, str]:
    company = await db.get(Company, loan_file.company_id)
    user = await db.get(User, actor_user_id) if actor_user_id else None
    name = f"{user.first_name} {user.last_name}".strip() if user is not None else ""
    return name or "Your processor", company.name if company is not None else ""


async def _open_draft(
    db: AsyncSession, *, loan_file_id: UUID, recipient: DraftRecipient, condition_id: UUID | None
) -> ConditionDraft | None:
    rows = await db.execute(
        select(ConditionDraft)
        .join(Communication, Communication.id == ConditionDraft.communication_id)
        .where(
            ConditionDraft.loan_file_id == loan_file_id,
            ConditionDraft.recipient == recipient,
            ConditionDraft.condition_id.is_(None)
            if condition_id is None
            else ConditionDraft.condition_id == condition_id,
            Communication.status == CommunicationStatus.DRAFT,
            Communication.deleted_at.is_(None),
        )
        .order_by(ConditionDraft.created_at)
        .limit(1)
    )
    return rows.scalar_one_or_none()


async def _new_draft(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    round_: ConditionRound,
    recipient: DraftRecipient,
    condition_id: UUID | None,
    actor_user_id: UUID | None,
) -> ConditionDraft:
    message = Communication(
        loan_file_id=loan_file.id,
        direction=CommunicationDirection.OUTBOUND,
        channel=CommunicationChannel.EMAIL,
        status=CommunicationStatus.DRAFT,
        recipient="",
        subject="",
        body="",
        body_format=BodyFormat.HTML,
        template_key=TEMPLATE_QUESTION if condition_id else TEMPLATE_ASK,
        template_version=TEMPLATE_VERSION,
        initiated_by_user_id=actor_user_id,
    )
    db.add(message)
    await db.flush()
    draft = ConditionDraft(
        company_id=loan_file.company_id,
        loan_file_id=loan_file.id,
        communication_id=message.id,
        round_id=round_.id,
        recipient=recipient,
        condition_id=condition_id,
    )
    db.add(draft)
    await db.flush()
    return draft


def _drafted_event(
    condition: Condition, draft: ConditionDraft, actor_user_id: UUID | None
) -> ConditionEvent:
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        round_id=draft.round_id,
        kind=ConditionEventKind.CONDITION_DRAFTED,
        actor_user_id=actor_user_id,
        detail={
            "recipient": draft.recipient.value,
            "communication_id": str(draft.communication_id),
        },
    )


async def sync_round_drafts(
    db: AsyncSession, *, round_: ConditionRound, actor_user_id: UUID | None
) -> list[ConditionDraft]:
    """Make the round's drafts match its confirmed plan. Idempotent. Flushes; the caller commits.

    Every open ask item of the round sits in the unsent draft for its recipient (made if there is none);
    an item no longer asked leaves its draft; each push-back / ask-the-underwriter condition has its
    question. An unsent draft left with nothing in it is deleted. Every open draft is then re-rendered.
    """
    loan_file = await db.get(LoanFile, round_.loan_file_id)
    assert loan_file is not None
    conditions = list(
        (
            await db.execute(
                select(Condition)
                .where(Condition.last_seen_round_id == round_.id, Condition.deleted_at.is_(None))
                .order_by(Condition.sequence)
            )
        ).scalars()
    )
    by_id = {condition.id: condition for condition in conditions}
    items = list(
        (
            await db.execute(
                select(ConditionItem)
                .join(Condition, Condition.id == ConditionItem.condition_id)
                .where(
                    ConditionItem.condition_id.in_(by_id),
                    ConditionItem.deleted_at.is_(None),
                )
                # SHEET ORDER, so the borrower's draft is made before the title company's.
                .order_by(Condition.sequence, ConditionItem.sequence)
            )
        ).scalars()
    )
    touched: dict[UUID, ConditionDraft] = {}
    #: Drafts whose membership changed this sync. A POLISHED draft is re-rendered only if it is here
    #: (the polish is hers; an unrelated plan edit must not wipe it).
    changed: set[UUID] = set()

    for item in items:
        condition = by_id[item.condition_id]
        wanted = (
            recipient_key(item)
            if item.option in _ASKS
            and item.status is ConditionItemStatus.OPEN
            and _open_condition(condition)
            else None
        )
        current = await db.get(ConditionDraft, item.draft_id) if item.draft_id else None
        if current is not None and not await _is_unsent(db, current):
            continue  # already asked in a sent email: that record stands
        if wanted is None:
            if current is not None:
                item.draft_id = None
                touched[current.id] = current
                changed.add(current.id)
            continue
        if current is not None and current.recipient is wanted:
            touched[current.id] = current
            continue
        draft = await _open_draft(
            db, loan_file_id=loan_file.id, recipient=wanted, condition_id=None
        ) or await _new_draft(
            db,
            loan_file=loan_file,
            round_=round_,
            recipient=wanted,
            condition_id=None,
            actor_user_id=actor_user_id,
        )
        if current is not None:
            touched[current.id] = current
            changed.add(current.id)
        item.draft_id = draft.id
        touched[draft.id] = draft
        changed.add(draft.id)
        db.add(_drafted_event(condition, draft, actor_user_id))

    for condition in conditions:
        asks = condition.next_step in _QUESTIONS and _open_condition(condition)
        existing = await _open_draft(
            db,
            loan_file_id=loan_file.id,
            recipient=DraftRecipient.UNDERWRITER,
            condition_id=condition.id,
        )
        if asks and existing is None and not await _question_sent(db, condition):
            draft = await _new_draft(
                db,
                loan_file=loan_file,
                round_=round_,
                recipient=DraftRecipient.UNDERWRITER,
                condition_id=condition.id,
                actor_user_id=actor_user_id,
            )
            touched[draft.id] = draft
            changed.add(draft.id)
            db.add(_drafted_event(condition, draft, actor_user_id))
        elif existing is not None:
            touched[existing.id] = existing
            if not asks:
                await _discard(db, loan_file=loan_file, draft=existing)
                touched.pop(existing.id)
    await db.flush()

    letter = await letter_facts(db, loan_file=loan_file, round_=round_)
    for draft in list(touched.values()):
        if not await _is_unsent(db, draft):
            continue
        if draft.condition_id is None and not await _draft_items(db, draft):
            await _discard(db, loan_file=loan_file, draft=draft)
            continue
        if draft.polished_at is not None and draft.id not in changed:
            continue
        await render(
            db, loan_file=loan_file, draft=draft, letter=letter, actor_user_id=actor_user_id
        )
    await db.flush()
    logger.info(
        "condition_drafts_synced",
        loan_file_id=str(loan_file.id),
        round_id=str(round_.id),
        drafts=len(touched),
    )
    return list(touched.values())


def _open_condition(condition: Condition) -> bool:
    return not condition.info_only and condition.lender_status in (
        ConditionLenderStatus.OPEN,
        ConditionLenderStatus.NOT_CLEARED,
    )


async def _is_unsent(db: AsyncSession, draft: ConditionDraft) -> bool:
    message = await db.get(Communication, draft.communication_id)
    return (
        message is not None
        and message.deleted_at is None
        and message.status is CommunicationStatus.DRAFT
    )


async def _question_sent(db: AsyncSession, condition: Condition) -> bool:
    row = await db.execute(
        select(ConditionDraft.id)
        .join(Communication, Communication.id == ConditionDraft.communication_id)
        .where(
            ConditionDraft.condition_id == condition.id,
            Communication.status == CommunicationStatus.SENT,
        )
        .limit(1)
    )
    return row.first() is not None


async def _draft_items(db: AsyncSession, draft: ConditionDraft) -> list[ConditionItem]:
    return list(
        (
            await db.execute(
                select(ConditionItem)
                .join(Condition, Condition.id == ConditionItem.condition_id)
                .where(ConditionItem.draft_id == draft.id, ConditionItem.deleted_at.is_(None))
                .order_by(Condition.sequence, ConditionItem.sequence)
            )
        ).scalars()
    )


async def _discard(db: AsyncSession, *, loan_file: LoanFile, draft: ConditionDraft) -> None:
    """Soft-delete an unsent draft (Phase 4's delete), revoke its upload link, free its items."""
    from app.services.email_draft import _revoke_link_in_url

    message = await db.get(Communication, draft.communication_id)
    if message is not None and message.status is CommunicationStatus.DRAFT:
        if message.upload_link_url:
            await _revoke_link_in_url(db, loan_file=loan_file, url=message.upload_link_url)
        message.deleted_at = datetime.now(UTC)
    for item in await _draft_items(db, draft):
        item.draft_id = None
    await db.flush()


async def render(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    draft: ConditionDraft,
    letter: LetterFacts,
    actor_user_id: UUID | None,
) -> Communication:
    """Write the draft's To, Subject and body from its items (or its question). Unsent drafts only."""
    message = await db.get(Communication, draft.communication_id)
    assert message is not None
    # REBUILT FROM THE LIBRARY, SO ANY POLISH IS GONE: the mark must not claim an AI wrote this.
    draft.polished_at = None
    signer, company = await _signer(db, loan_file=loan_file, actor_user_id=actor_user_id)
    email, name = await _address(db, loan_file=loan_file, recipient=draft.recipient, letter=letter)
    message.recipient = _to_line(email, name)

    if draft.condition_id is not None:
        condition = await db.get(Condition, draft.condition_id)
        assert condition is not None
        library_type = load_library().get(condition.canonical_type_id)
        short = (library_type.short or library_type.name) if library_type else ""
        greeting = _first_word(letter.underwriter[0]) if letter.underwriter else None
        message.subject, message.body = render_question(
            condition=condition,
            short=short,
            greeting_name=greeting,
            letter=letter,
            signer=signer,
            company=company,
        )
        message.body = sanitise_html(message.body or "")
        return message

    items = await _draft_items(db, draft)
    conditions = {
        condition.id: condition
        for condition in (
            await db.execute(
                select(Condition).where(Condition.id.in_({i.condition_id for i in items}))
            )
        ).scalars()
    }
    pairs = [(conditions[item.condition_id], item) for item in items]
    await _link_needs(db, message=message, items=items)
    if draft.recipient is DraftRecipient.BORROWER:
        if not message.upload_link_url:
            from app.services.upload_links import mint_upload_link

            minted = await mint_upload_link(
                db, loan_file=loan_file, purpose="Documents for your loan's conditions"
            )
            message.upload_link_url = minted.url
        dues = [item.due_date for item in items if item.due_date]
        borrower_name = name.split()[0] if name else None
        message.subject, message.body = render_borrower(
            first_name=borrower_name,
            lines=borrower_lines(pairs, letter),
            due=min(dues) if dues else None,
            upload_url=message.upload_link_url,
            signer=signer,
            company=company,
        )
    elif draft.recipient is DraftRecipient.LENDER:
        lines = lender_lines(pairs, letter)
        request = None
        if len(pairs) == 1:
            condition, item = pairs[0]
            _, library_item = _library_item(condition, item)
            named = library_item.name if library_item else item.name
            from app.services.condition_reading import GENERIC_NAME

            if named and named != GENERIC_NAME:
                request = named[:1].lower() + named[1:]
        message.subject, message.body = render_lender(
            greeting_name=_first_word(name) if name else None,
            lines=lines,
            letter=letter,
            signer=signer,
            company=company,
            request=request,
        )
    else:
        greeting = _first_word(name) if name and draft.recipient is DraftRecipient.LO else None
        message.subject, message.body = render_party(
            greeting_name=greeting,
            lines=party_lines(pairs, letter),
            letter=letter,
            signer=signer,
            company=company,
        )
    # THROUGH PHASE 4'S ALLOW-LIST BEFORE IT IS STORED. The words are escaped as they are built; this
    # is the second line, and the same one every other HTML body in `communications` passes.
    message.body = sanitise_html(message.body or "")
    return message


async def _link_needs(
    db: AsyncSession, *, message: Communication, items: list[ConditionItem]
) -> None:
    """Phase 4's needs membership, so the send starts each need's reminder clock (`requested_at`)."""
    wanted = {item.need_id for item in items if item.need_id}
    have = set(
        (
            await db.execute(
                select(CommunicationNeedsItem.needs_item_id).where(
                    CommunicationNeedsItem.communication_id == message.id
                )
            )
        ).scalars()
    )
    for need_id in wanted - have:
        db.add(CommunicationNeedsItem(communication_id=message.id, needs_item_id=need_id))
    for need_id in have - wanted:
        row = await db.get(CommunicationNeedsItem, (message.id, need_id))
        if row is not None:
            await db.delete(row)
    await db.flush()


# --------------------------------------------------------------------------------------------- #
# Her actions: mark as sent, delete, give an address
# --------------------------------------------------------------------------------------------- #


async def mark_sent(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    draft: ConditionDraft,
    actor_user_id: UUID,
) -> Communication:
    """She sent it from her own mail. Phase 4 records the send; our status moves to Waiting (§4a 10).

    FORWARD ONLY, FROM TO DO. A condition already Waiting (6637, once the borrower email went) stays
    as it is when the title email is marked sent; the lender's track is never touched.
    """
    from app.services.email_send import send_draft

    message = await db.get(Communication, draft.communication_id)
    if message is None or message.deleted_at is not None:
        raise DraftRefused("This draft was deleted.")
    if message.status is not CommunicationStatus.DRAFT:
        raise DraftRefused("This email was already marked sent.")
    address = _address_of(message.recipient)
    if not address:
        raise DraftRefused("Add an email address for this draft before marking it sent.")
    sent = await send_draft(
        db,
        loan_file=loan_file,
        draft_id=message.id,
        recipient=address,
        body=message.body or "",
        approver_user_id=actor_user_id,
        subject=message.subject,
    )
    now = datetime.now(UTC)
    if draft.condition_id is not None:
        conditions = [await db.get(Condition, draft.condition_id)]
    else:
        items = await _draft_items(db, draft)
        for item in items:
            if item.status is ConditionItemStatus.OPEN:
                item.status = ConditionItemStatus.REQUESTED
        ids = list(dict.fromkeys(item.condition_id for item in items))
        conditions = [await db.get(Condition, condition_id) for condition_id in ids]
    await db.flush()
    moved = 0
    for condition in conditions:
        if condition is None or not _open_condition(condition):
            continue
        if await _wait_on_first_asked(
            db, condition=condition, draft=draft, now=now, actor_user_id=actor_user_id
        ):
            moved += 1
    await _name_the_send(db, loan_file=loan_file, draft=draft, message=sent)
    await db.flush()
    logger.info(
        "condition_draft_marked_sent",
        loan_file_id=str(loan_file.id),
        recipient=draft.recipient.value,
        moved=moved,
    )
    return sent


async def _wait_on_first_asked(
    db: AsyncSession,
    *,
    condition: Condition,
    draft: ConditionDraft,
    now: datetime,
    actor_user_id: UUID,
) -> bool:
    """Move a condition to Waiting on whoever holds its FIRST asked item (S3-12). Returns if it moved.

    NOT "WHOEVER WAS EMAILED FIRST". 0132's disclosure is the LO's and its wire instructions the title
    company's; S3-12 reads "Waiting on LO" because the disclosure comes first, whichever email she
    happened to mark sent first. So the owner is the recipient of the condition's first live ask item
    whose email has gone. A condition at To do moves to Waiting; one the SENDS already put at Waiting
    follows to the right owner. One she moved herself, or moved past Waiting, is left alone.
    """
    target: OwnerHint | None
    if draft.condition_id is not None:
        target = WAITING_ON[draft.recipient]
    else:
        items = await _condition_items(db, condition)
        gone: dict[UUID, DraftRecipient] = {}
        for item in items:
            if item.option not in _ASKS or item.draft_id is None:
                continue
            owner_draft = await db.get(ConditionDraft, item.draft_id)
            if owner_draft is not None and not await _is_unsent(db, owner_draft):
                gone[item.id] = owner_draft.recipient
        target = first_asked_owner(items, lambda item: gone.get(item.id))
        if target is None:
            return False

    from app.services.condition_status import _event as status_event

    if target is None:
        return False
    target_owner: OwnerHint = target
    if condition.prep_status is ConditionPrepStatus.TO_DO:
        detail: dict[str, Any] = {
            "prep_status_from": ConditionPrepStatus.TO_DO.value,
            "prep_status_to": ConditionPrepStatus.WAITING.value,
        }
        condition.prep_status = ConditionPrepStatus.WAITING
        condition.prep_status_changed_at = now
    elif (
        condition.prep_status is ConditionPrepStatus.WAITING
        and condition.waiting_on is not target_owner
        and await _last_move_was_a_send(db, condition)
    ):
        detail = {
            "prep_status_from": ConditionPrepStatus.WAITING.value,
            "prep_status_to": ConditionPrepStatus.WAITING.value,
        }
    else:
        return False
    condition.waiting_on = target_owner
    detail.update(
        {"waiting_on": target_owner.value, "by": "email", "recipient": draft.recipient.value}
    )
    db.add(
        status_event(
            condition, ConditionEventKind.CONDITION_PREP_MOVED, detail, actor_user_id=actor_user_id
        )
    )
    return True


async def _condition_items(db: AsyncSession, condition: Condition) -> list[ConditionItem]:
    return list(
        (
            await db.execute(
                select(ConditionItem)
                .where(
                    ConditionItem.condition_id == condition.id,
                    ConditionItem.deleted_at.is_(None),
                    ConditionItem.status != ConditionItemStatus.NOT_NEEDED,
                )
                .order_by(ConditionItem.sequence)
            )
        ).scalars()
    )


async def _last_move_was_a_send(db: AsyncSession, condition: Condition) -> bool:
    last = (
        await db.execute(
            select(ConditionEvent.detail)
            .where(
                ConditionEvent.condition_id == condition.id,
                ConditionEvent.kind == ConditionEventKind.CONDITION_PREP_MOVED,
            )
            .order_by(ConditionEvent.occurred_at.desc(), ConditionEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return bool(last and last.get("by") == "email")


async def _name_the_send(
    db: AsyncSession, *, loan_file: LoanFile, draft: ConditionDraft, message: Communication
) -> None:
    """Phase 4's activity line says "Sent a document request for 0 item(s)" for a question; ours names
    the email instead ("Borrower email marked sent", "Question on 6178 marked sent")."""
    from app.models.activity_log import ActivityLog, ActivityType

    await db.flush()
    rows = (
        await db.execute(
            select(ActivityLog).where(
                ActivityLog.loan_file_id == loan_file.id,
                ActivityLog.activity_type == ActivityType.COMMUNICATION_SENT,
            )
        )
    ).scalars()
    if draft.condition_id is not None:
        condition = await db.get(Condition, draft.condition_id)
        summary = f"Question on {condition.lender_code if condition else ''} marked sent"
    else:
        summary = f"{SHORT_LABEL[draft.recipient]} email marked sent"
    for row in rows:
        if (row.detail or {}).get("communication_id") == str(message.id):
            row.summary = summary


def _address_of(to_line: str | None) -> str | None:
    """`Alex Rivera <alex@example.com>` → `alex@example.com`; a bare address as is."""
    if not to_line:
        return None
    match = re.search(r"<([^<>@\s]+@[^<>\s]+)>", to_line)
    if match:
        return match.group(1)
    return to_line.strip() if "@" in to_line else None


async def delete(db: AsyncSession, *, loan_file: LoanFile, draft: ConditionDraft) -> None:
    """Delete draft (S3-04). The items go back to waiting for a draft; nothing else moves."""
    if not await _is_unsent(db, draft):
        raise DraftRefused("Only an unsent draft can be deleted.")
    await _discard(db, loan_file=loan_file, draft=draft)


async def set_address(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    draft: ConditionDraft,
    email: str,
    name: str | None,
    actor_user_id: UUID,
) -> None:
    """A missing address, asked once and remembered: saved on the file, then every draft re-rendered."""
    from app.services.party_requests import add_participant

    if draft.recipient is DraftRecipient.LO:
        loan_file.loan_officer_email = email
        if name:
            loan_file.loan_officer_name = name
    elif draft.recipient is DraftRecipient.BORROWER:
        from app.services.email_draft import primary_borrower

        borrower = await primary_borrower(db, loan_file_id=loan_file.id)
        if borrower is not None and not borrower.email:
            borrower.email = email
        else:
            await add_participant(
                db, loan_file=loan_file, role=ParticipantRole.BORROWER, email=email, name=name
            )
    else:
        await add_participant(
            db, loan_file=loan_file, role=PARTICIPANT_ROLE[draft.recipient], email=email, name=name
        )
    await db.flush()
    round_ = await db.get(ConditionRound, draft.round_id) if draft.round_id else None
    letter = await letter_facts(db, loan_file=loan_file, round_=round_)
    for other in await open_condition_drafts(db, loan_file_id=loan_file.id):
        if other.recipient is not draft.recipient:
            continue
        if other.polished_at is not None:
            # Her polished words stay; only the address line is new.
            known, shown = await _address(
                db, loan_file=loan_file, recipient=other.recipient, letter=letter
            )
            message = await db.get(Communication, other.communication_id)
            if message is not None:
                message.recipient = _to_line(known, shown)
            continue
        await render(
            db, loan_file=loan_file, draft=other, letter=letter, actor_user_id=actor_user_id
        )
    await db.flush()


async def open_condition_drafts(db: AsyncSession, *, loan_file_id: UUID) -> list[ConditionDraft]:
    return list(
        (
            await db.execute(
                select(ConditionDraft)
                .join(Communication, Communication.id == ConditionDraft.communication_id)
                .where(
                    ConditionDraft.loan_file_id == loan_file_id,
                    Communication.status == CommunicationStatus.DRAFT,
                    Communication.deleted_at.is_(None),
                )
                .order_by(ConditionDraft.created_at)
            )
        ).scalars()
    )


async def resync_file(db: AsyncSession, *, loan_file_id: UUID, actor_user_id: UUID | None) -> None:
    """After a plan edit: re-sync every round of the file whose plan is confirmed."""
    rounds = (
        await db.execute(
            select(ConditionRound).where(
                ConditionRound.loan_file_id == loan_file_id,
                ConditionRound.plan_confirmed_at.is_not(None),
                ConditionRound.deleted_at.is_(None),
            )
        )
    ).scalars()
    for round_ in rounds:
        await sync_round_drafts(db, round_=round_, actor_user_id=actor_user_id)


# --------------------------------------------------------------------------------------------- #
# Read side: the dialog and the list's tails
# --------------------------------------------------------------------------------------------- #


async def draft_needs_title(db: AsyncSession, need_id: UUID) -> str | None:
    need = await db.get(NeedsItem, need_id)
    return need.title if need is not None else None


def item_words(condition: Condition, item: ConditionItem) -> str:
    """An item as a sentence names it (LP-948a): a library item by its library label, else its library
    name; any other item (a re-ask, a part, one she added) by its own name. NEVER its key.

    A key is an internal handle (`reask_3f2a9b1c`, and since LP-946 a part's `source.employer`), and
    the draft dialog is read by her and quoted to the people she emails.
    """
    library_type = load_library().get(condition.canonical_type_id)
    # A part (LP-946) is `<library key>.<performer>`; no library key has a dot (checked: 0 of 52).
    base = item.key.split(".", 1)[0]
    library_item = (
        next((each for each in library_type.items if each.key == base), None)
        if library_type
        else None
    )
    if library_item is not None:
        # The LIBRARY's wording, not the item's: an item's name can carry its figure ("Source of the
        # $2,850.00"), which a side-column label does not repeat.
        return in_sentence(library_item.label or library_item.name)
    return in_sentence(item.name)


def condition_label(condition: Condition, items: list[ConditionItem]) -> str:
    """How an email's side column names a condition (S3-04, S3-05).

    The type's short name when the email carries all of the condition's live items; one item's own
    label when it carries just that one; else "Short: part and part". "(prior to funding)" is added to a
    prior-to-funding condition, as S3-05 prints 1947.
    """
    library_type = load_library().get(condition.canonical_type_id)
    short = (library_type.short or library_type.name) if library_type else None
    label: str
    if items and library_type is not None:
        live_keys = {item.key for item in library_type.items}
        carried = [item.key for item in items]
        if len(items) == 1 and set(carried) != live_keys:
            library_item = next((i for i in library_type.items if i.key == items[0].key), None)
            label = (library_item.label if library_item else None) or items[0].name
        elif set(carried) >= live_keys or short is None:
            label = short or items[0].name
        else:
            parts = [item_words(condition, item) for item in items]
            label = f"{short}: {_join(parts)}"
    else:
        label = short or (items[0].name if items else (condition.lender_code or ""))
    if _before_funding(condition, items):
        label = f"{label} (prior to funding)"
    return label


def _before_funding(condition: Condition, items: list[ConditionItem]) -> bool:
    """A prior-to-funding condition asked for early says so — when it collects something. 6378's
    instruction to title collects nothing, so it carries no "(prior to funding)" (S3-05)."""
    return condition.bucket_kind is BucketKind.PRIOR_TO_FUNDING and any(
        item.documents for item in items
    )


async def draft_view(
    db: AsyncSession, *, loan_file: LoanFile, draft: ConditionDraft, actor_user_id: UUID | None
) -> dict[str, Any]:
    """Everything the dialog shows (S3-04 to S3-06), as plain data for `ConditionDraftPublic`."""
    message = await db.get(Communication, draft.communication_id)
    assert message is not None
    round_ = await db.get(ConditionRound, draft.round_id) if draft.round_id else None
    letter = await letter_facts(db, loan_file=loan_file, round_=round_)
    number = round_.round_number if round_ is not None else None

    in_this_email: list[dict[str, Any]] = []
    asked_once: list[dict[str, Any]] = []
    why_facts: list[dict[str, str]] = []
    if draft.condition_id is not None:
        condition = await db.get(Condition, draft.condition_id)
        assert condition is not None
        title = f"{TITLE[draft.recipient]} · {condition.lender_code or ''}".rstrip(" ·")
        in_this_email.append(
            {
                "condition_id": condition.id,
                "code": condition.lender_code,
                "label": condition_label(condition, []),
            }
        )
        push_back = (condition.reading or {}).get("push_back") or {}
        mncb = _iso_date(push_back.get("must_not_close_before"))
        starts = _iso_date(push_back.get("policy_starts"))
        if mncb and starts:
            why_facts = [
                {
                    "label": f"Letter, round {number}:" if number else "Letter:",
                    "value": f"Must Not Close Before {us_date(mncb)}",
                },
                {
                    "label": "Condition text: policy",
                    "value": f"not effective until {us_date(starts)}",
                },
            ]
    else:
        title = f"{TITLE[draft.recipient]}" + (f" · round {number}" if number else "")
        items = await _draft_items(db, draft)
        by_condition: dict[UUID, list[ConditionItem]] = {}
        for item in items:
            by_condition.setdefault(item.condition_id, []).append(item)
        conditions = {
            c.id: c
            for c in (
                await db.execute(select(Condition).where(Condition.id.in_(by_condition)))
            ).scalars()
        }
        for condition_id in sorted(by_condition, key=lambda cid: conditions[cid].sequence):
            condition = conditions[condition_id]
            in_this_email.append(
                {
                    "condition_id": condition.id,
                    "code": condition.lender_code,
                    "label": condition_label(condition, by_condition[condition_id]),
                }
            )
        shared: dict[UUID, list[ConditionItem]] = {}
        for item in items:
            if item.need_id:
                shared.setdefault(item.need_id, []).append(item)
        for members in shared.values():
            codes = list(
                dict.fromkeys(
                    conditions[m.condition_id].lender_code or "—"
                    for m in sorted(members, key=lambda m: conditions[m.condition_id].sequence)
                )
            )
            if len(codes) < 2:
                continue
            months = sorted(
                {
                    str((m.specifics or {}).get("month"))
                    for m in members
                    if (m.specifics or {}).get("month")
                }
            )
            names = [_MONTHS[int(month.split("-")[1]) - 1] for month in months if "-" in month]
            what = (
                f"{_join(names).replace(', and', ' and')} statements"
                if names
                else (await draft_needs_title(db, members[0].need_id) or "same document")  # type: ignore[arg-type]
            )
            asked_once.append({"what": what, "codes": codes})

    others: list[dict[str, Any]] = []
    signer_first = None
    if actor_user_id is not None:
        user = await db.get(User, actor_user_id)
        signer_first = user.first_name if user is not None else None
    siblings = (
        await db.execute(
            select(ConditionDraft)
            .join(Communication, Communication.id == ConditionDraft.communication_id)
            .where(
                ConditionDraft.loan_file_id == loan_file.id,
                ConditionDraft.round_id == draft.round_id,
                ConditionDraft.id != draft.id,
                # THE ROUND'S EMAILS, NOT ITS QUESTIONS: S3-05 lists the borrower's and the LO's.
                ConditionDraft.condition_id.is_(None),
                Communication.deleted_at.is_(None),
            )
            .order_by(ConditionDraft.created_at)
        )
    ).scalars()
    for other in siblings:
        label = SHORT_LABEL[other.recipient]
        if other.recipient is DraftRecipient.LO and signer_first:
            label = f"LO ({signer_first} → loan officer)"
        if other.condition_id is not None:
            condition = await db.get(Condition, other.condition_id)
            summary = f"{condition.lender_code if condition else ''} question".strip()
        else:
            other_items = await _draft_items(db, other)
            ids = list(dict.fromkeys(item.condition_id for item in other_items))
            if len(ids) == 1:
                condition = await db.get(Condition, ids[0])
                first = item_words(condition, other_items[0]) if condition else ""
                summary = f"{condition.lender_code if condition else ''} {first}".strip()
            else:
                summary = f"{len(ids)} conditions"
        others.append(
            {"draft_id": other.id, "recipient": other.recipient, "label": label, "summary": summary}
        )

    email, _ = await _address(db, loan_file=loan_file, recipient=draft.recipient, letter=letter)
    clause = (
        letter.mortgagee_clause
        if draft.recipient in (DraftRecipient.TITLE_ATTORNEY, DraftRecipient.INSURANCE)
        else None
    )
    becomes = f"Waiting on {_waiting_word(WAITING_ON[draft.recipient])}"
    return {
        "id": draft.id,
        "communication_id": message.id,
        "recipient": draft.recipient,
        "round_number": number,
        "title": title,
        "status": "sent" if message.status is CommunicationStatus.SENT else "draft",
        "sent_at": message.sent_at,
        "to": message.recipient or "",
        "needs_address": not email,
        "subject": message.subject or "",
        "body_html": message.body or "",
        "in_this_email": in_this_email,
        "asked_once": asked_once,
        "other_drafts": others,
        "mortgagee_clause": clause,
        "why_facts": why_facts,
        "becomes": becomes,
        "polished_at": draft.polished_at,
        "due_date": min(
            (item.due_date for item in await _draft_items(db, draft) if item.due_date),
            default=None,
        ),
    }


def _waiting_word(owner: OwnerHint) -> str:
    return {
        OwnerHint.BORROWER: "Borrower",
        OwnerHint.TITLE: "Title",
        OwnerHint.BROKER: "LO",
        OwnerHint.INSURANCE: "Insurance",
        OwnerHint.LENDER: "Lender",
    }.get(owner, "someone")


async def drafts_for_file(db: AsyncSession, *, loan_file_id: UUID) -> list[dict[str, Any]]:
    """Every condition draft on the file, sent or not, for the "Drafts for round 1" line and the tails."""
    rows = (
        await db.execute(
            select(ConditionDraft, Communication, ConditionRound.round_number)
            .join(Communication, Communication.id == ConditionDraft.communication_id)
            .outerjoin(ConditionRound, ConditionRound.id == ConditionDraft.round_id)
            .where(ConditionDraft.loan_file_id == loan_file_id, Communication.deleted_at.is_(None))
            .order_by(ConditionDraft.created_at)
        )
    ).tuples()
    out: list[dict[str, Any]] = []
    for draft, message, number in rows:
        if draft.condition_id is not None:
            condition = await db.get(Condition, draft.condition_id)
            codes = [condition.lender_code or "—"] if condition else []
        else:
            items = await _draft_items(db, draft)
            ids = list(dict.fromkeys(item.condition_id for item in items))
            found = {
                c.id: c
                for c in (
                    await db.execute(select(Condition).where(Condition.id.in_(ids)))
                ).scalars()
            }
            codes = [found[i].lender_code or "—" for i in ids if i in found]
        out.append(
            {
                "id": draft.id,
                "recipient": draft.recipient,
                "label": SHORT_LABEL[draft.recipient]
                if draft.condition_id is None
                else f"Question {codes[0] if codes else ''}".strip(),
                "round_number": number,
                "status": "sent" if message.status is CommunicationStatus.SENT else "draft",
                "sent_at": message.sent_at,
                "codes": codes,
            }
        )
    # The order the plan names them (S3-02: Borrower · Title/attorney · LO), then questions.
    rank = {recipient: index for index, recipient in enumerate(DraftRecipient)}
    out.sort(key=lambda row: (row["round_number"] or 0, rank[row["recipient"]]))
    return out


async def draft_tails(db: AsyncSession, draft_ids: set[UUID]) -> dict[UUID, Any]:
    """`{draft id: DraftTailPublic}` for live drafts: "draft", or "sent" with the send date (ET)."""
    from zoneinfo import ZoneInfo

    from app.schemas.condition import DraftTailPublic

    if not draft_ids:
        return {}
    eastern = ZoneInfo("America/New_York")
    rows = (
        await db.execute(
            select(ConditionDraft.id, Communication.status, Communication.sent_at)
            .join(Communication, Communication.id == ConditionDraft.communication_id)
            .where(ConditionDraft.id.in_(draft_ids), Communication.deleted_at.is_(None))
        )
    ).tuples()
    out: dict[UUID, Any] = {}
    for draft_id, status, sent_at in rows:
        sent = status is CommunicationStatus.SENT
        out[draft_id] = DraftTailPublic(
            id=draft_id,
            status="sent" if sent else "draft",
            sent_on=sent_at.astimezone(eastern).date() if sent and sent_at else None,
        )
    return out


async def question_tails_for_file(db: AsyncSession, *, loan_file_id: UUID) -> dict[UUID, Any]:
    """`{condition id: DraftTailPublic}` — each condition's newest live question to the underwriter."""
    rows = (
        await db.execute(
            select(ConditionDraft.id, ConditionDraft.condition_id)
            .where(
                ConditionDraft.loan_file_id == loan_file_id,
                ConditionDraft.condition_id.is_not(None),
            )
            .order_by(ConditionDraft.created_at)
        )
    ).tuples()
    by_condition = {condition_id: draft_id for draft_id, condition_id in rows}
    tails = await draft_tails(db, set(by_condition.values()))
    return {
        condition_id: tails[draft_id]
        for condition_id, draft_id in by_condition.items()
        if draft_id in tails and condition_id is not None
    }


async def set_due_date(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    draft: ConditionDraft,
    due: date,
    actor_user_id: UUID,
) -> None:
    """The draft's due date, as she edits it in the dialog (§8: "editable in the draft").

    STORED ON THE ITEMS, which is where the date already lives (LP-920) and what a reminder reads, and
    each change is Phase 4.5's own plan-change event; then the draft is re-rendered from them.
    """
    if not await _is_unsent(db, draft):
        raise DraftRefused("A sent email's due date is the one she sent.")
    for item in await _draft_items(db, draft):
        if item.due_date != due:
            before = item.due_date
            item.due_date = due
            condition = await db.get(Condition, item.condition_id)
            if condition is not None:
                db.add(
                    ConditionEvent(
                        company_id=condition.company_id,
                        loan_file_id=condition.loan_file_id,
                        condition_id=condition.id,
                        round_id=draft.round_id,
                        kind=ConditionEventKind.CONDITION_PLAN_CHANGED,
                        actor_user_id=actor_user_id,
                        detail={
                            "change": "item",
                            "item_key": item.key,
                            "due_date": {
                                "from": before.isoformat() if before else None,
                                "to": due.isoformat(),
                            },
                        },
                    )
                )
    await db.flush()
    round_ = await db.get(ConditionRound, draft.round_id) if draft.round_id else None
    letter = await letter_facts(db, loan_file=loan_file, round_=round_)
    await render(db, loan_file=loan_file, draft=draft, letter=letter, actor_user_id=actor_user_id)
    await db.flush()


async def propose_polish(db: AsyncSession, *, loan_file: LoanFile, draft: ConditionDraft) -> Any:
    """ "Polish with AI": the model's version and the fact warnings. Nothing is stored."""
    from app.ai.condition_polish import polish_draft

    if not await _is_unsent(db, draft):
        raise DraftRefused("A sent email cannot be polished.")
    message = await db.get(Communication, draft.communication_id)
    assert message is not None
    return await polish_draft(message.body or "")


async def use_polish(
    db: AsyncSession,
    *,
    loan_file: LoanFile,
    draft: ConditionDraft,
    body_html: str,
    warnings_accepted: int,
    actor_user_id: UUID,
) -> None:
    """ "Use this": the polished body replaces the draft's, sanitised; each condition gets an event."""
    from app.conditions.email_facts import plain

    if not await _is_unsent(db, draft):
        raise DraftRefused("A sent email cannot be changed.")
    cleaned = sanitise_html(body_html or "")
    if not plain(cleaned):
        raise DraftRefused("That email is empty — keep your draft instead.")
    message = await db.get(Communication, draft.communication_id)
    assert message is not None
    message.body = cleaned
    draft.polished_at = datetime.now(UTC)
    if draft.condition_id is not None:
        condition_ids = [draft.condition_id]
    else:
        condition_ids = list(dict.fromkeys(i.condition_id for i in await _draft_items(db, draft)))
    for condition_id in condition_ids:
        condition = await db.get(Condition, condition_id)
        if condition is None:
            continue
        db.add(
            ConditionEvent(
                company_id=condition.company_id,
                loan_file_id=condition.loan_file_id,
                condition_id=condition.id,
                round_id=draft.round_id,
                kind=ConditionEventKind.CONDITION_DRAFT_POLISHED,
                actor_user_id=actor_user_id,
                detail={"recipient": draft.recipient.value, "warnings_accepted": warnings_accepted},
            )
        )
    await db.flush()
    logger.info(
        "condition_draft_polish_used",
        loan_file_id=str(loan_file.id),
        warnings_accepted=warnings_accepted,
    )
