"""Evidence arrives and is checked (LP-923): link a document to the items it answers, check it by code.

WHEN. After every processed document, in the per-file needs update (`tasks/needs._run_needs_update`),
right after the needs engine has linked it. `check_document` is also called directly by tests and the
visual harness.

LINKING (plan §5 LP-923 step 1). A document answers every open item on the file that asks for its type
and, when the item names a statement month, whose month the statement covers. A statement for the
WRONG account is linked anyway, so the right-account check can reject it with the reason. An item that
names no account ("any other account used for closing") takes only statements for an account its
sibling items do not already ask for. One document answers several items (§4a change 2) and is checked
once for each — so a missing page fails every item the statement answers (LP-934 M1).

CHECKS (step 2) are code, each `passed`, `failed` or `not_run` with a plain reason. A check whose inputs
the file does not have is NOT RUN, never passed (README). Every figure is read from the document's
current extraction or the letter; nothing here asks a model.

THE LARGE DEPOSIT (step 3): Fannie Mae B3-4.2-02's 50% of monthly income, by code, against the letter's
Verified Income. It is attached to the condition that proves funds to close (the item that checks
"enough for closing"), and must be sourced when the funds are needed without it.

OUTCOME (step 4). An item whose every check passed is done; a condition whose every live item is done
and whose evidence has no open finding moves to Ready to send (README rule 5). A failed check leaves the
item open with its reason. Nothing is drafted by itself: the re-ask and the explanation request go into
the borrower email when she presses the button (S3-07, S3-08).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrower import Borrower
from app.models.condition import (
    Condition,
    ConditionLenderStatus,
    ConditionPrepStatus,
)
from app.models.condition_event import ConditionEvent, ConditionEventKind
from app.models.condition_evidence import ConditionEvidence, EvidenceStatus
from app.models.condition_item import ConditionItem
from app.models.condition_round import ConditionRound
from app.models.condition_vocabulary import (
    ConditionItemOrigin,
    ConditionItemStatus,
    EvidenceCheck,
    Performer,
    PlanOption,
)
from app.models.document import Document

logger = structlog.get_logger(__name__)

PASSED, FAILED, NOT_RUN = "passed", "failed", "not_run"
#: The screens' en dash ("pages 1 to 5 of 6" is printed with one), written as an escape for the linter.
_DASH = "\u2013"
#: A finding is answered when she says it is explained (or, later, the explanation arrives and passes).
_UNANSWERED = frozenset({"open", "asked"})

#: Fannie Mae B3-4.2-02: a deposit over 50% of the monthly income used to qualify must be sourced.
LARGE_DEPOSIT_SHARE = Decimal("0.50")
LARGE_DEPOSIT_CITATION = "Fannie Mae B3-4.2-02"
#: Deposits the statement itself explains: pay, not a gift or a transfer from an unknown source.
_PAYROLL = re.compile(r"\b(payroll|direct\s*dep(osit)?|salary|dir\s*dep)\b", re.I)

_AWAITING = frozenset(
    {ConditionItemStatus.OPEN, ConditionItemStatus.REQUESTED, ConditionItemStatus.RECEIVED}
)
_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
_MONTH_NAMES = [
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

#: The check's label, as S3-07 and S3-08 print it.
LABEL: dict[str, str] = {
    EvidenceCheck.ALL_PAGES.value: "All pages",
    EvidenceCheck.RIGHT_ACCOUNT.value: "Right account",
    EvidenceCheck.RIGHT_BORROWER.value: "Right borrower",
    EvidenceCheck.RIGHT_PERIOD.value: "Right period",
    EvidenceCheck.INSIDE_LENDER_DATES.value: "Inside the lender's dates",
    EvidenceCheck.AMOUNT_MATCHES.value: "Amount matches",
    EvidenceCheck.COVERS_REQUIRED_FUNDS.value: "Enough for closing",
    EvidenceCheck.SIGNED_AND_DATED.value: "Signed and dated",
    EvidenceCheck.MORTGAGEE_CLAUSE_MATCHES.value: "Mortgagee clause",
    EvidenceCheck.EFFECTIVE_BY_CLOSING.value: "In force by closing",
    EvidenceCheck.INSIDE_VOE_WINDOW.value: "Inside the VOE window",
    EvidenceCheck.NOT_EXPIRED.value: "Not expired",
    "no_large_deposit": "No unexplained large deposit",
}


class EvidenceRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------------------------- #
# What a statement says — read by code from the current extraction
# --------------------------------------------------------------------------------------------- #


def _value(data: dict[str, Any], key: str) -> Any:
    raw = data.get(key)
    return raw.get("value") if isinstance(raw, dict) else raw


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Deposit:
    on: date | None
    amount: Decimal
    description: str


@dataclass(frozen=True)
class Statement:
    """The facts the checks need, from one bank statement's current extraction. Missing = None."""

    bank: str | None
    last4: str | None
    holder: str | None
    start: date | None
    end: date | None
    pages_present: int | None
    pages_declared: int | None
    ending_balance: Decimal | None
    deposits: tuple[Deposit, ...] = ()
    #: Every transaction's absolute amount and date, for "amount matches" (6637's check clearing).
    movements: tuple[tuple[Decimal, date | None], ...] = field(default_factory=tuple)
    #: What the document is, in the check's words: "statement", or "receipt" for an earnest money
    #: receipt, whose one movement is the amount it acknowledges (LP-938 review).
    source: str = "statement"


#: LP-938 — THE DOCUMENT TYPES WHOSE OWN STATED AMOUNT IS THE MONEY THEY EVIDENCE, and nothing else. A
#: receipt acknowledges the deposit, a gift letter states the gift, a deposit slip records the deposit;
#: each has no transactions, so "Amount matches" reads this amount as its one movement: `(amount field,
#: date fields in order, what the failure calls it)`. A purchase agreement ALSO extracts
#: `earnest_money_amount`, and is deliberately absent: a contract's stated deposit is a STATED figure,
#: and letting it satisfy a check that confirms receipt would defeat stated-versus-verified (CLAUDE.md).
#: Keyed by type rather than by field so no library edit can make it pass (LP-938 follow-up review).
OWN_AMOUNT: dict[str, tuple[str, tuple[str, ...], str]] = {
    "earnest_money_receipt": (
        "earnest_money_amount",
        ("funds_received_date", "receipt_date"),
        "receipt",
    ),
    "gift_letter": ("gift_amount", ("gift_date_or_expected_transfer_date",), "gift letter"),
    "bank_deposit_slip": ("deposit_total", ("deposit_date",), "deposit slip"),
}


def statement_from(data: dict[str, Any] | None, document_type: str | None = None) -> Statement:
    data = data or {}
    masked = str(_value(data, "account_number_masked") or "")
    digits = re.sub(r"\D", "", masked)
    deposits: list[Deposit] = []
    movements: list[tuple[Decimal, date | None]] = []
    for row in data.get("transactions") or []:
        if not isinstance(row, dict):
            continue
        amount = _decimal(row.get("amount"))
        if amount is None:
            continue
        on = _date(row.get("date"))
        movements.append((abs(amount), on))
        kind = str(row.get("transaction_type") or "").lower()
        if amount > 0 and kind in ("deposit", "credit", ""):
            deposits.append(
                Deposit(on=on, amount=amount, description=str(row.get("description") or ""))
            )
    # A RECEIPT, A GIFT LETTER OR A DEPOSIT SLIP HAS NO TRANSACTIONS, AND ITS AMOUNT IS THE POINT (LP-938
    # review and follow-up). Without this each one's own amount was extracted and never read, "Amount
    # matches" was not run, and the item stopped at Received. Only `OWN_AMOUNT`'s types, and only when
    # the caller says which type this is: the check does, every other caller wants statement facts.
    source = "statement"
    own = OWN_AMOUNT.get(document_type or "")
    if not movements and own is not None:
        amount_field, date_fields, source = own
        stated = _decimal(_value(data, amount_field))
        if stated is not None:
            on = next((d for f in date_fields if (d := _date(_value(data, f))) is not None), None)
            movements.append((abs(stated), on))
    return Statement(
        bank=_value(data, "bank_name"),
        last4=digits[-4:] if len(digits) >= 4 else None,
        holder=_value(data, "account_holder_name"),
        start=_date(_value(data, "statement_period_start")),
        end=_date(_value(data, "statement_period_end")),
        pages_present=_int(_value(data, "page_count_present")),
        pages_declared=_int(_value(data, "page_count_declared")),
        ending_balance=_decimal(_value(data, "ending_balance")),
        deposits=tuple(deposits),
        movements=tuple(movements),
        source=source,
    )


def _extraction_data(document: Document) -> dict[str, Any] | None:
    extraction = document.current_extraction
    return extraction.extracted_data if extraction is not None else None


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def _us(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def _period(statement: Statement) -> str:
    """`Aug 1-31, 2026`, `Jul 1 - Aug 31, 2026`."""
    start, end = statement.start, statement.end
    if start is None or end is None:
        return "the period on the statement"
    if (start.year, start.month) == (end.year, end.month):
        return f"{_MONTHS[start.month - 1]} {start.day}{_DASH}{end.day}, {end.year}"
    return f"{_MONTHS[start.month - 1]} {start.day} {_DASH} {_MONTHS[end.month - 1]} {end.day}, {end.year}"


def _months_covered(statement: Statement) -> set[str]:
    if statement.start is None or statement.end is None:
        return set()
    out: set[str] = set()
    year, month = statement.start.year, statement.start.month
    while (year, month) <= (statement.end.year, statement.end.month):
        out.add(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


# --------------------------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------------------------- #


@dataclass
class Context:
    """Everything a check reads besides the statement itself."""

    item_last4: str | None
    item_month: str | None
    item_amount: Decimal | None
    borrowers: list[tuple[str, str]]
    asset_expiry: date | None
    today: date
    required_funds: Decimal | None
    verified_funds: Decimal | None
    #: The month before the asked one is already in the file, for the same account (6132's wording).
    previous_month_in_file: bool


def run_check(check: str, statement: Statement, ctx: Context) -> dict[str, str]:
    """One check → `{"check", "result", "reason"}`. Pure, so a test can state the inputs."""
    result, reason = _run(check, statement, ctx)
    return {"check": check, "result": result, "reason": reason}


def _run(check: str, s: Statement, ctx: Context) -> tuple[str, str]:
    if check == EvidenceCheck.ALL_PAGES.value:
        if s.pages_present is None or s.pages_declared is None:
            return NOT_RUN, "the statement does not say how many pages it has"
        if s.pages_present >= s.pages_declared:
            return PASSED, f"{s.pages_declared} of {s.pages_declared} pages"
        first_missing = s.pages_present + 1
        missing = (
            f"page {first_missing} is missing"
            if first_missing == s.pages_declared
            else f"pages {first_missing}{_DASH}{s.pages_declared} are missing"
        )
        return FAILED, f"pages 1{_DASH}{s.pages_present} of {s.pages_declared} — {missing}"

    if check == EvidenceCheck.RIGHT_ACCOUNT.value:
        if s.last4 is None or ctx.item_last4 is None:
            return NOT_RUN, "no account ending to compare"
        bank = f"{s.bank} " if s.bank else ""
        if s.last4 == ctx.item_last4:
            return PASSED, f"{bank}ending {s.last4}, matches the condition"
        return FAILED, f"{bank}ending {s.last4} — the condition asks for ending {ctx.item_last4}"

    if check == EvidenceCheck.RIGHT_BORROWER.value:
        if not s.holder or not ctx.borrowers:
            return NOT_RUN, "no account holder name to compare"
        holder = s.holder.lower()
        if any(first.lower() in holder and last.lower() in holder for first, last in ctx.borrowers):
            return PASSED, s.holder
        return FAILED, f"the statement is in the name of {s.holder}"

    if check == EvidenceCheck.RIGHT_PERIOD.value:
        if ctx.item_month is None:
            return (
                (NOT_RUN, "the condition names no month")
                if s.start is None
                else (PASSED, _period(s))
            )
        covered = _months_covered(s)
        if not covered:
            return NOT_RUN, "the statement's period could not be read"
        if ctx.item_month in covered:
            year, month = (int(p) for p in ctx.item_month.split("-"))
            if ctx.previous_month_in_file:
                before = _MONTH_NAMES[(month - 2) % 12]
                return PASSED, f"{_period(s)} — the month right after {before}, already in the file"
            return PASSED, f"{_period(s)} — the month asked for"
        year, month = (int(p) for p in ctx.item_month.split("-"))
        return FAILED, f"{_period(s)} — the condition asks for {_MONTH_NAMES[month - 1]} {year}"

    if check == EvidenceCheck.INSIDE_LENDER_DATES.value:
        if ctx.asset_expiry is None:
            return NOT_RUN, "the letter gives no asset-document expiry"
        if s.end is None:
            return NOT_RUN, "the statement date could not be read"
        tail = f"statement date {_us(s.end)}; asset documents expire {_us(ctx.asset_expiry)}"
        if s.end <= ctx.asset_expiry and ctx.today <= ctx.asset_expiry:
            return PASSED, tail
        return FAILED, f"{tail} — outside the lender's dates"

    if check == EvidenceCheck.AMOUNT_MATCHES.value:
        if ctx.item_amount is None:
            return NOT_RUN, "the condition names no amount"
        if not s.movements:
            return NOT_RUN, "no amount could be read on this document"
        for amount, on in s.movements:
            if amount == ctx.item_amount:
                when = f" on {_us(on)}" if on else ""
                return PASSED, f"{_money(amount)}{when}"
        return FAILED, f"no {_money(ctx.item_amount)} on this {s.source}"

    if check == EvidenceCheck.COVERS_REQUIRED_FUNDS.value:
        if ctx.required_funds is None or ctx.verified_funds is None:
            return NOT_RUN, "the required or verified funds could not be read"
        tail = (
            f"verified {_money(ctx.verified_funds)} against {_money(ctx.required_funds)} required"
        )
        return (PASSED, tail) if ctx.verified_funds >= ctx.required_funds else (FAILED, tail)

    return NOT_RUN, "not checked by code yet — accept it if it is right"


def large_deposits(
    statement: Statement,
    *,
    monthly_income: Decimal | None,
    required: Decimal | None,
    verified: Decimal | None,
) -> list[dict[str, Any]]:
    """B3-4.2-02 by code: deposits over 50% of monthly income that are not pay. Pure."""
    if monthly_income is None:
        return []
    threshold = (monthly_income * LARGE_DEPOSIT_SHARE).quantize(Decimal("0.01"))
    out: list[dict[str, Any]] = []
    for deposit in statement.deposits:
        if deposit.amount <= threshold or _PAYROLL.search(deposit.description):
            continue
        without = verified - deposit.amount if verified is not None else None
        needed = bool(required is not None and without is not None and without < required)
        out.append(
            {
                "kind": "large_deposit",
                "citation": LARGE_DEPOSIT_CITATION,
                "date": deposit.on.isoformat() if deposit.on else None,
                "amount": str(deposit.amount),
                "description": deposit.description,
                "income": str(monthly_income),
                "threshold": str(threshold),
                "assets_without": str(without) if without is not None else None,
                "required": str(required) if required is not None else None,
                "needed": needed,
                "status": "open",
            }
        )
    return out


def deposit_check(findings: list[dict[str, Any]]) -> dict[str, str]:
    """S3-08's "No unexplained large deposit" row, from the findings: it fails while one is open."""
    # ASKED IS STILL UNEXPLAINED: "7086 stays Waiting on Borrower until this is answered" (S3-08).
    open_ones = [f for f in findings if f.get("status") in _UNANSWERED and f.get("needed")]
    if not open_ones:
        return {"check": "no_large_deposit", "result": PASSED, "reason": "none needing a source"}
    first = open_ones[0]
    on = _date(first.get("date"))
    what = (first.get("description") or "deposit").lower()
    return {
        "check": "no_large_deposit",
        "result": FAILED,
        "reason": f"{_us(on) + ' ' if on else ''}{what} {_money(Decimal(first['amount']))}",
    }


# --------------------------------------------------------------------------------------------- #
# Linking and checking a document
# --------------------------------------------------------------------------------------------- #


def _last4(item: ConditionItem) -> str | None:
    value = (item.specifics or {}).get("account_last4")
    return str(value) if value else None


def _month(item: ConditionItem) -> str | None:
    value = (item.specifics or {}).get("month")
    return str(value) if value else None


def _item_amount(item: ConditionItem, condition: Condition) -> Decimal | None:
    for candidate in (item.specifics or {}).get("amounts") or []:
        if (value := _decimal(candidate)) is not None:
            return value
    for read in (condition.reading or {}).get("items") or []:
        for candidate in ((read or {}).get("specifics") or {}).get("amounts") or []:
            if (value := _decimal(candidate)) is not None:
                return value
    # The lender's own words, as LP-922's emails fall back to them: "in the amount of $2,850.00".
    from app.conditions.facts import money_in

    found = money_in(condition.verbatim_text or "")
    return found[0] if found else None


def _open_condition(condition: Condition) -> bool:
    return (
        condition.deleted_at is None
        and not condition.info_only
        and condition.lender_status
        in (ConditionLenderStatus.OPEN, ConditionLenderStatus.NOT_CLEARED)
    )


async def _document(db: AsyncSession, document_id: UUID) -> Document | None:
    return (
        await db.execute(
            select(Document)
            .options(selectinload(Document.extractions))
            .where(Document.id == document_id)
        )
    ).scalar_one_or_none()


def _takes(
    item: ConditionItem, siblings: list[ConditionItem], document: Document, s: Statement
) -> bool:
    """Whether this document answers this item (step 1)."""
    if item.deleted_at is not None or item.status not in _AWAITING:
        return False
    if item.option in (PlanOption.LENDER_DOING_IT, PlanOption.INFORMATION_ONLY):
        return False
    if document.document_type not in (item.documents or []):
        return False
    month = _month(item)
    covered = _months_covered(s)
    if month and covered and month not in covered:
        return False
    # "Any other account": not a statement its siblings already ask for.
    return not (
        _last4(item) is None
        and s.last4 is not None
        and any(_last4(other) == s.last4 for other in siblings if other.id != item.id)
    )


async def _borrowers(db: AsyncSession, loan_file_id: UUID) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            select(Borrower.first_name, Borrower.last_name).where(
                Borrower.loan_file_id == loan_file_id, Borrower.deleted_at.is_(None)
            )
        )
    ).tuples()
    return [(first, last) for first, last in rows if first and last]


async def _round(db: AsyncSession, condition: Condition) -> ConditionRound | None:
    return (
        await db.get(ConditionRound, condition.last_seen_round_id)
        if condition.last_seen_round_id
        else None
    )


def _monthly_income(round_: ConditionRound | None) -> Decimal | None:
    """The letter's Verified Income (UWM prints the monthly figure), read by code."""
    facts = ((round_.header if round_ is not None else None) or {}).get("loan_facts") or {}
    raw = str(facts.get("Verified Income") or "")
    return _decimal(raw.replace("$", "").replace(",", "")) if raw else None


def _asset_expiry(round_: ConditionRound | None) -> date | None:
    return _date(((round_.expiry_dates if round_ is not None else None) or {}).get("asset"))


async def _statements_for_item(
    db: AsyncSession, item: ConditionItem, extra: tuple[Document, Statement] | None
) -> list[tuple[Document, Statement]]:
    rows = (
        await db.execute(select(ConditionEvidence).where(ConditionEvidence.item_id == item.id))
    ).scalars()
    out: list[tuple[Document, Statement]] = []
    seen: set[UUID] = set()
    for row in rows:
        if not counts_as_evidence(row):
            continue
        document = await _document(db, row.document_id)
        if document is not None and document.deleted_at is None:
            out.append((document, statement_from(_extraction_data(document))))
            seen.add(document.id)
    if extra is not None and extra[0].id not in seen:
        out.append(extra)
    return out


def _verified(statements: list[tuple[Document, Statement]]) -> Decimal | None:
    """The latest ending balance per account, summed — what these statements verify."""
    latest: dict[str, tuple[date, Decimal]] = {}
    for _, s in statements:
        if s.ending_balance is None:
            continue
        key = s.last4 or "?"
        when = s.end or date.min
        if key not in latest or when > latest[key][0]:
            latest[key] = (when, s.ending_balance)
    return sum((balance for _, balance in latest.values()), Decimal("0")) if latest else None


async def _previous_month_in_file(
    db: AsyncSession, loan_file_id: UUID, month: str | None, last4: str | None, exclude: UUID
) -> bool:
    if not month or not last4:
        return False
    year, number = (int(p) for p in month.split("-"))
    before = f"{year - 1:04d}-12" if number == 1 else f"{year:04d}-{number - 1:02d}"
    documents = (
        await db.execute(
            select(Document)
            .options(selectinload(Document.extractions))
            .where(
                Document.loan_file_id == loan_file_id,
                Document.document_type == "bank_statement",
                Document.deleted_at.is_(None),
                Document.id != exclude,
            )
        )
    ).scalars()
    for document in documents:
        s = statement_from(_extraction_data(document))
        if s.last4 == last4 and before in _months_covered(s):
            return True
    return False


async def check_document(
    db: AsyncSession, *, document_id: UUID, today: date | None = None
) -> list[ConditionEvidence]:
    """Link one arrived document to the items it answers and check it for each. Flushes; caller commits."""
    document = await _document(db, document_id)
    if document is None or document.deleted_at is not None or not document.document_type:
        return []
    today = today or datetime.now(UTC).date()
    statement = statement_from(_extraction_data(document), document.document_type)
    items = list(
        (
            await db.execute(
                select(ConditionItem)
                .where(
                    ConditionItem.loan_file_id == document.loan_file_id,
                    ConditionItem.deleted_at.is_(None),
                )
                .order_by(ConditionItem.sequence)
            )
        ).scalars()
    )
    by_condition: dict[UUID, list[ConditionItem]] = {}
    for item in items:
        by_condition.setdefault(item.condition_id, []).append(item)
    borrowers = await _borrowers(db, document.loan_file_id)
    touched: list[ConditionEvidence] = []
    conditions_touched: dict[UUID, Condition] = {}

    for item in items:
        condition = await db.get(Condition, item.condition_id)
        if condition is None or not _open_condition(condition):
            continue
        if not _takes(item, by_condition[item.condition_id], document, statement):
            continue
        evidence = await _evidence_row(db, item=item, document=document, condition=condition)
        await _check(
            db,
            evidence=evidence,
            item=item,
            condition=condition,
            document=document,
            statement=statement,
            borrowers=borrowers,
            today=today,
        )
        touched.append(evidence)
        conditions_touched[condition.id] = condition

    for condition in conditions_touched.values():
        rows = [e for e in touched if e.condition_id == condition.id]
        db.add(
            _event(
                condition,
                ConditionEventKind.CONDITION_EVIDENCE_CHECKED,
                {
                    "document_id": str(document.id),
                    "items": len(rows),
                    "failed": sum(_failed(e) for e in rows),
                    "findings": sum(len(e.findings or []) for e in rows),
                },
                actor_user_id=None,
            )
        )
        await _settle(db, condition=condition, actor_user_id=None)
    await db.flush()
    logger.info(
        "condition_evidence_checked",
        loan_file_id=str(document.loan_file_id),
        document_id=str(document.id),
        linked=len(touched),
    )
    return touched


async def _evidence_row(
    db: AsyncSession, *, item: ConditionItem, document: Document, condition: Condition
) -> ConditionEvidence:
    existing = (
        await db.execute(
            select(ConditionEvidence).where(
                ConditionEvidence.item_id == item.id, ConditionEvidence.document_id == document.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = ConditionEvidence(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        item_id=item.id,
        document_id=document.id,
        checks=[],
        findings=[],
    )
    db.add(row)
    await db.flush()
    return row


async def _check(
    db: AsyncSession,
    *,
    evidence: ConditionEvidence,
    item: ConditionItem,
    condition: Condition,
    document: Document,
    statement: Statement,
    borrowers: list[tuple[str, str]],
    today: date,
) -> None:
    round_ = await _round(db, condition)
    names = [str(check) for check in (item.checks or [])]
    required = _decimal(
        ((condition.reading or {}).get("figures") or {}).get("shortfall", {}).get("required")
    )
    verified = None
    if EvidenceCheck.COVERS_REQUIRED_FUNDS.value in names:
        verified = _verified(await _statements_for_item(db, item, (document, statement)))
    ctx = Context(
        item_last4=_last4(item) or _condition_last4(condition),
        item_month=_month(item),
        item_amount=_item_amount(item, condition),
        borrowers=borrowers,
        asset_expiry=_asset_expiry(round_),
        today=today,
        required_funds=required,
        verified_funds=verified,
        previous_month_in_file=await _previous_month_in_file(
            db, condition.loan_file_id, _month(item), statement.last4, document.id
        ),
    )
    results = [run_check(name, statement, ctx) for name in names]
    if EvidenceCheck.COVERS_REQUIRED_FUNDS.value in names:
        # THE FINDINGS KEEP HER ANSWERS: a re-check never reopens a deposit she explained or asked about.
        answered = {(f.get("date"), f.get("amount")): f for f in (evidence.findings or [])}
        fresh = large_deposits(
            statement, monthly_income=_monthly_income(round_), required=required, verified=verified
        )
        evidence.findings = [answered.get((f["date"], f["amount"]), f) for f in fresh]
    # THE DEPOSIT IS A FINDING, NOT A CHECK (LP-934 on S3-08): it is not stored among the item's
    # checks, so it can never count as "Failed a check" — the sheet derives its row from `findings`.
    evidence.checks = results
    if item.status in (ConditionItemStatus.OPEN, ConditionItemStatus.REQUESTED):
        item.status = ConditionItemStatus.RECEIVED
    if _item_passes(item, [evidence]):
        item.status = ConditionItemStatus.DONE


def _condition_last4(condition: Condition) -> str | None:
    for read in (condition.reading or {}).get("items") or []:
        value = ((read or {}).get("specifics") or {}).get("account_last4")
        if value:
            return str(value)
    return None


def counts_as_evidence(row: ConditionEvidence) -> bool:
    """Whether this document is evidence for its item: accepted by her, or failing none of its own checks.

    A REJECTED STATEMENT VERIFIES NOTHING (Stage 3B acceptance). Every statement checked against an
    item used to count, so a ··4471 upload that failed "right account" added its balance to 7086's
    "verified $83,828.84", in the check and in the figures check. "Covers required funds" is the one
    check that does not reject: it is the sum across the item's statements, so a real July statement
    short of the total on its own is still July's evidence. The funds sum, the figures check and the
    package all ask this one question.
    """
    if row.status is EvidenceStatus.ACCEPTED:
        return True
    return not any(
        check.get("result") == FAILED
        and check.get("check") != EvidenceCheck.COVERS_REQUIRED_FUNDS.value
        for check in row.checks or []
    )


def _passes_alone(row: ConditionEvidence) -> bool:
    """Accepted by her, or failing no check at all."""
    if row.status is EvidenceStatus.ACCEPTED:
        return True
    return not any(check.get("result") == FAILED for check in row.checks or [])


def superseded_by(
    row: ConditionEvidence, item: ConditionItem | None, rows: list[ConditionEvidence]
) -> ConditionEvidence | None:
    """The document that replaced this failed one, or None while the failure still counts (LP-937).

    A failed row is superseded once its item is DONE and another row for the same item, arriving no
    earlier, passes. THE PYTHON HALF OF ONE RULE: `conditions.has_failed_check()` is the SQL half, and
    `test_superseded_failures.py` asserts the two agree.
    """
    if not _failed(row) or item is None or item.status is not ConditionItemStatus.DONE:
        return None
    for other in rows:
        if (
            other.id != row.id
            and other.item_id == row.item_id
            and other.created_at >= row.created_at
            and _passes_alone(other)
        ):
            return other
    return None


def _failed(evidence: ConditionEvidence) -> bool:
    if evidence.status is EvidenceStatus.ACCEPTED:
        return False
    return any(check.get("result") == FAILED for check in evidence.checks or [])


def _open_finding(evidence: ConditionEvidence) -> bool:
    return any(f.get("status") in _UNANSWERED and f.get("needed") for f in evidence.findings or [])


def _item_passes(item: ConditionItem, evidence: list[ConditionEvidence]) -> bool:
    """Done when some evidence for it is accepted, or every check on it passed and nothing is open."""
    for row in evidence:
        if row.status is EvidenceStatus.ACCEPTED:
            return True
        results = [c.get("result") for c in row.checks or []]
        if results and all(r == PASSED for r in results) and not _open_finding(row):
            return True
    return False


async def _settle(db: AsyncSession, *, condition: Condition, actor_user_id: UUID | None) -> bool:
    """Ready to send once every live item is done and no evidence finding is open (README rule 5)."""
    items = [
        i
        for i in (
            await db.execute(
                select(ConditionItem).where(
                    ConditionItem.condition_id == condition.id, ConditionItem.deleted_at.is_(None)
                )
            )
        ).scalars()
        if i.status is not ConditionItemStatus.NOT_NEEDED
    ]
    evidence = list(
        (
            await db.execute(
                select(ConditionEvidence).where(ConditionEvidence.condition_id == condition.id)
            )
        ).scalars()
    )
    if not items or any(i.status is not ConditionItemStatus.DONE for i in items):
        return False
    # Only findings on documents that ARE evidence hold it: a rejected statement (the wrong account, a
    # page missing) is not submitted, so a deposit only it shows is not one the lender will see
    # (Stage 3B acceptance: the ··4471 upload held 7086 at Waiting with nothing left to answer).
    held = any(_open_finding(e) for e in evidence if counts_as_evidence(e))
    if held or condition.next_step is not None:
        return False
    if condition.prep_status not in (ConditionPrepStatus.TO_DO, ConditionPrepStatus.WAITING):
        return False
    before = condition.prep_status
    condition.prep_status = ConditionPrepStatus.READY
    condition.prep_status_changed_at = datetime.now(UTC)
    condition.waiting_on = None
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PREP_MOVED,
            {
                "prep_status_from": before.value,
                "prep_status_to": ConditionPrepStatus.READY.value,
                "by": "evidence",
            },
            actor_user_id=actor_user_id,
        )
    )
    return True


def _event(
    condition: Condition,
    kind: ConditionEventKind,
    detail: dict[str, Any],
    *,
    actor_user_id: UUID | None,
) -> ConditionEvent:
    return ConditionEvent(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        round_id=condition.last_seen_round_id,
        kind=kind,
        actor_user_id=actor_user_id,
        detail=detail,
    )


# --------------------------------------------------------------------------------------------- #
# Her actions (S3-07, S3-08)
# --------------------------------------------------------------------------------------------- #


async def _scoped_evidence(
    db: AsyncSession, condition: Condition, evidence_id: UUID
) -> ConditionEvidence:
    row = await db.get(ConditionEvidence, evidence_id)
    if row is None or row.condition_id != condition.id:
        raise EvidenceRefused("No such evidence on this condition.")
    return row


async def accept_anyway(
    db: AsyncSession, *, condition: Condition, evidence_id: UUID, reason: str, actor_user_id: UUID
) -> None:
    """ "Accept anyway…": a failed check accepted with her reason, kept in the history."""
    reason = (reason or "").strip()
    if not reason:
        raise EvidenceRefused("Say why you are accepting it — the reason is kept in the history.")
    evidence = await _scoped_evidence(db, condition, evidence_id)
    evidence.status = EvidenceStatus.ACCEPTED
    evidence.accepted_reason = reason[:1000]
    evidence.accepted_by_user_id = actor_user_id
    item = await db.get(ConditionItem, evidence.item_id)
    if item is not None and item.status is not ConditionItemStatus.NOT_NEEDED:
        item.status = ConditionItemStatus.DONE
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_EVIDENCE_ACCEPTED,
            {
                "document_id": str(evidence.document_id),
                "failed": [c["check"] for c in evidence.checks or [] if c.get("result") == FAILED],
                "reason": evidence.accepted_reason,
            },
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    await _settle(db, condition=condition, actor_user_id=actor_user_id)
    await db.flush()


async def reask(
    db: AsyncSession, *, condition: Condition, evidence_id: UUID, actor_user_id: UUID
) -> ConditionItem:
    """ "Add 'please send page 6' to the borrower email": an item asking for what failed."""
    evidence = await _scoped_evidence(db, condition, evidence_id)
    failed = [c for c in evidence.checks or [] if c.get("result") == FAILED]
    if not failed:
        raise EvidenceRefused("Nothing failed on this document.")
    document = await _document(db, evidence.document_id)
    statement = statement_from(_extraction_data(document) if document else None)
    name = reask_name(failed[0]["check"], statement)
    item = await _add_ask(
        db,
        condition=condition,
        key=f"reask_{str(evidence.id)[:8]}",
        name=name,
        acceptable=failed[0].get("reason") or "",
        source=await db.get(ConditionItem, evidence.item_id),
        actor_user_id=actor_user_id,
    )
    return item


def reask_name(check: str, statement: Statement) -> str:
    """S3-07's "please send page 6", as an item's name."""
    what = f"{statement.bank} ··{statement.last4}" if statement.bank and statement.last4 else "the"
    month = (
        f" {_MONTH_NAMES[statement.end.month - 1]} {statement.end.year}" if statement.end else ""
    )
    if (
        check == EvidenceCheck.ALL_PAGES.value
        and statement.pages_present
        and statement.pages_declared
    ):
        first = statement.pages_present + 1
        pages = (
            f"Page {first}"
            if first == statement.pages_declared
            else f"Pages {first}{_DASH}{statement.pages_declared}"
        )
        return f"{pages} of the {what}{month} statement"
    return f"A corrected {what}{month} statement"[:200]


async def answer_finding(
    db: AsyncSession,
    *,
    condition: Condition,
    evidence_id: UUID,
    index: int,
    answer: str,
    reason: str | None,
    actor_user_id: UUID,
) -> ConditionItem | None:
    """S3-08: "Ask the borrower to explain it" (`ask`) or "It's already explained…" (`explained`)."""
    evidence = await _scoped_evidence(db, condition, evidence_id)
    findings = [dict(f) for f in evidence.findings or []]
    if not 0 <= index < len(findings):
        raise EvidenceRefused("No such finding.")
    finding = findings[index]
    item: ConditionItem | None = None
    if answer == "explained":
        text = (reason or "").strip()
        if not text:
            raise EvidenceRefused("Say how it is explained — the reason is kept in the history.")
        finding["status"] = "explained"
        finding["reason"] = text[:1000]
    elif answer == "ask":
        finding["status"] = "asked"
        on = _date(finding.get("date"))
        amount = _money(Decimal(finding["amount"]))
        item = await _add_ask(
            db,
            condition=condition,
            key=f"deposit_{str(evidence.id)[:8]}_{index}",
            name=f"Letter explaining the {amount} deposit{' on ' + _us(on) if on else ''}"[:200],
            acceptable="A signed and dated letter saying where the money came from, with proof "
            "(for example the statement of the account it came from)",
            source=None,
            actor_user_id=actor_user_id,
        )
    else:
        raise EvidenceRefused("Unknown answer.")
    findings[index] = finding
    evidence.findings = findings
    also = await _answer_the_same_deposit_elsewhere(db, condition, evidence, finding)
    detail: dict[str, Any] = {
        "document_id": str(evidence.document_id),
        "answer": answer,
        "kind": finding.get("kind"),
    }
    if also:
        detail["also_answered_on"] = also
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_FINDING_ANSWERED,
            detail,
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    item_row = await db.get(ConditionItem, evidence.item_id)
    if item_row is not None and _item_passes(item_row, [evidence]):
        item_row.status = ConditionItemStatus.DONE
    await _settle(db, condition=condition, actor_user_id=actor_user_id)
    await db.flush()
    return item


async def _answer_the_same_deposit_elsewhere(
    db: AsyncSession, condition: Condition, answered: ConditionEvidence, finding: dict[str, Any]
) -> list[str]:
    """Her answer is about the DEPOSIT, not the upload: the same deposit (the same account, date and
    amount) on this condition's other statements gets the same answer. Returns their document ids.

    Stage 3B acceptance found the gap: a 5-page August statement (rejected, a page missing) carried the
    08/21 $4,000.00 deposit as an open finding. She explained it on the complete statement, and the copy
    on the rejected one held 7086 at Waiting with nothing left for her to answer.
    """
    if finding.get("kind") != "large_deposit":
        return []
    source = await _document(db, answered.document_id)
    last4 = statement_from(_extraction_data(source)).last4 if source is not None else None
    if not last4:
        return []
    others = (
        await db.execute(
            select(ConditionEvidence).where(
                ConditionEvidence.condition_id == condition.id,
                ConditionEvidence.id != answered.id,
            )
        )
    ).scalars()
    touched: list[str] = []
    for row in others:
        document = await _document(db, row.document_id)
        if document is None or statement_from(_extraction_data(document)).last4 != last4:
            continue
        changed = False
        updated = []
        for other in row.findings or []:
            same = (
                other.get("kind") == "large_deposit"
                and other.get("date") == finding.get("date")
                and other.get("amount") == finding.get("amount")
                and other.get("status") in _UNANSWERED
            )
            if same:
                other = {**other, "status": finding["status"]}
                if "reason" in finding:
                    other["reason"] = finding["reason"]
                changed = True
            updated.append(other)
        if changed:
            row.findings = updated
            touched.append(str(row.document_id))
    return touched


async def _add_ask(
    db: AsyncSession,
    *,
    condition: Condition,
    key: str,
    name: str,
    acceptable: str,
    source: ConditionItem | None,
    actor_user_id: UUID,
) -> ConditionItem:
    """A new borrower item on the condition; the round's drafts pick it up (LP-922's accumulation)."""
    last = (
        await db.execute(
            select(ConditionItem.sequence)
            .where(ConditionItem.condition_id == condition.id)
            .order_by(ConditionItem.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    item = ConditionItem(
        company_id=condition.company_id,
        loan_file_id=condition.loan_file_id,
        condition_id=condition.id,
        round_id=condition.last_seen_round_id,
        key=key[:40],
        name=name[:200],
        acceptable=acceptable,
        performer=Performer.BORROWER,
        performers=[Performer.BORROWER.value],
        option=PlanOption.ASK_BORROWER,
        status=ConditionItemStatus.OPEN,
        origin=ConditionItemOrigin.MANUAL,
        documents=list(source.documents) if source is not None else [],
        checks=[],
        specifics=dict(source.specifics or {}) if source is not None else {},
        sequence=(last or 0) + 1,
    )
    db.add(item)
    db.add(
        _event(
            condition,
            ConditionEventKind.CONDITION_PLAN_CHANGED,
            {"change": "item_added", "option": PlanOption.ASK_BORROWER.value, "why": "evidence"},
            actor_user_id=actor_user_id,
        )
    )
    await db.flush()
    from app.services.condition_drafts import resync_file

    await resync_file(db, loan_file_id=condition.loan_file_id, actor_user_id=actor_user_id)
    return item


# --------------------------------------------------------------------------------------------- #
# Read side
# --------------------------------------------------------------------------------------------- #


async def evidence_public_for_file(
    db: AsyncSession, *, loan_file_id: UUID
) -> dict[UUID, list[Any]]:
    """`{condition id: [ConditionEvidencePublic]}` — the sheet's document cards, checks and findings."""
    from app.schemas.condition import ConditionEvidencePublic

    rows = list(
        (
            await db.execute(
                select(ConditionEvidence)
                .where(ConditionEvidence.loan_file_id == loan_file_id)
                .order_by(ConditionEvidence.created_at)
            )
        ).scalars()
    )
    if not rows:
        return {}
    documents = {
        d.id: d
        for d in (
            await db.execute(
                select(Document)
                .options(selectinload(Document.extractions))
                .where(Document.id.in_({r.document_id for r in rows}))
            )
        ).scalars()
    }
    items = {
        i.id: i
        for i in (
            await db.execute(
                select(ConditionItem).where(ConditionItem.id.in_({r.item_id for r in rows}))
            )
        ).scalars()
    }
    out: dict[UUID, list[Any]] = {}
    for row in rows:
        document = documents.get(row.document_id)
        if document is None or document.deleted_at is not None:
            continue
        statement = statement_from(_extraction_data(document))
        superseded = None
        replaced = False
        replacement = superseded_by(row, items.get(row.item_id), rows)
        if replacement is not None and (by := documents.get(replacement.document_id)) is not None:
            title = document_title(by, statement_from(_extraction_data(by)))
            # A statement short of the total ON ITS OWN is still evidence (it goes in the package), so
            # "replaced" would be untrue of it. "Together with" was untrue too, for two statements of
            # one account: `_verified` takes the account's latest balance, so the later statement met
            # the total by itself (LP-937 review).
            replaced = not counts_as_evidence(row)
            superseded = (
                f"Replaced by {title}"
                if replaced
                else f"Still evidence — enough for closing was met once {title} arrived"
            )
        out.setdefault(row.condition_id, []).append(
            ConditionEvidencePublic.build(
                row,
                document=document,
                statement=statement,
                superseded=superseded,
                replaced=replaced,
            )
        )
    return out


def document_title(document: Document, statement: Statement) -> str:
    """S3-07's "Capital One statement ··9912 · August 2026 · 5 pages"."""
    if document.document_type == "bank_statement" and statement.bank:
        months = sorted(_months_covered(statement))
        names = [f"{_MONTH_NAMES[int(m[5:]) - 1]}" for m in months]
        year = months[-1][:4] if months else ""
        when = (" and ".join(names) + f" {year}") if names else ""
        noun = "statements" if len(months) > 1 else "statement"
        parts = [f"{statement.bank} {noun}" + (f" ··{statement.last4}" if statement.last4 else "")]
        if when.strip():
            parts.append(when.strip())
        if statement.pages_present:
            parts.append(f"{statement.pages_present} pages")
        return " · ".join(parts)
    return document.document_name or document.original_filename
