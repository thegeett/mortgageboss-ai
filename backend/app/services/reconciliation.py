"""The reconciliation read model (LP-UI-017).

The product's thesis, as data: *a loan file is two columns that have to agree*.
For one file, this returns the fields that have a **stated** value (the 1003 /
MISMO application) and a **found** value (what an extraction actually read out of
a document), with per-row agreement and the provenance behind the found side.

Nothing here is new information. Stated financials, extractions with their
`SourceLocation`, and the documents all exist; what did not exist was the join.
This module is that join and nothing more — **deterministic, no AI in this path**.

**It does not invent a second definition of "differs".** The rule engine already
decides when a stated and a documented number disagree, and a ledger that
disagreed with the findings beside it would be worse than no ledger. Income
reuses the engine's 10% variance (`app/verification/cross_source/rules.py`,
`_VARIANCE_10`); employer comparison reuses `normalize_name` from
`app/services/borrower_name_matching.py` for tokenising. Where this module needed
a rule the engine does not have — company-suffix matching, exact equality for a
valuation, presence for the insurance gap — ADR-391 records it.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.borrower import Borrower
from app.models.document import Document
from app.models.helpers import only_active
from app.models.loan_file import LoanFile
from app.models.property import Property
from app.models.stated_financials import StatedAsset
from app.services.borrower_name_matching import normalize_name
from app.verification.cross_source.rules import XSRC_INCOME_STATED_VS_DOCUMENTED

# The engine's income variance, READ OFF THE RULE rather than restated. An
# earlier version of this line declared `Decimal("10")` under a comment claiming
# it was imported, which is the drift it was written to prevent wearing the
# label of the fix: two mechanisms answering one question, guaranteed to agree
# only until someone edits one of them.
#
# Taken from the rule rather than from `_VARIANCE_10` directly, so it follows
# whatever threshold that rule actually carries.
#
# KNOWN GAP: LP-80 makes this threshold overlay-overrideable per lender by
# rule_id, and this read model does not resolve overlays — so for a file under a
# lender that has widened or narrowed the variance, the ledger uses the default
# where the engine uses the overlay. Narrower than restating the literal, and
# recorded rather than hidden.
_INCOME_THRESHOLD = XSRC_INCOME_STATED_VS_DOCUMENTED.threshold
INCOME_VARIANCE_PERCENT = _INCOME_THRESHOLD.value if _INCOME_THRESHOLD else Decimal("10")


class Agreement(StrEnum):
    """What the two columns say about one field.

    Four states, and the distinction between the last two is the point: a value
    the application claimed and no document supports is a *gap to chase*, while a
    value a document shows and the application never mentioned is a *disclosure
    problem*. Collapsing them into "mismatch" loses which one a processor is
    looking at.
    """

    MATCH = "match"
    DIFFERS = "differs"
    #: Stated, but no document supports it.
    MISSING = "missing"
    #: Found in a document, but the application never stated it.
    NOT_STATED = "not_stated"


class RowSource(BaseModel):
    """Where the found value came from — the audit anchor for one row."""

    document_id: UUID
    filename: str
    page: int | None = None
    snippet: str | None = None


class ReconciliationRow(BaseModel):
    """One field, both columns, and why they do or do not agree."""

    field_key: str
    label: str
    stated_value: str | None
    found_value: str | None
    agreement: Agreement
    source: RowSource | None = None
    #: Why this row has no `source`. Never null when `source` is null — the
    #: ticket's "every row carries provenance or an explicit reason it has none".
    source_note: str | None = None


# --------------------------------------------------------------------------- #
# the documents side
# --------------------------------------------------------------------------- #


class _FoundField(BaseModel):
    """A typed-core extraction field plus the document it was read from."""

    value: str
    source: RowSource


def _found_fields(documents: list[Document]) -> dict[str, list[_FoundField]]:
    """Every typed-core field across the file's current extractions, by key.

    A key can appear in several documents (two pay stubs both report
    `gross_pay`), so the value is a list and the caller decides which to use.
    """
    out: dict[str, list[_FoundField]] = {}
    for document in documents:
        extraction = document.current_extraction
        if extraction is None:
            continue
        for key, node in (extraction.extracted_data or {}).items():
            if not isinstance(node, dict) or node.get("value") is None:
                continue
            raw_location = node.get("source")
            location: dict[str, Any] = raw_location if isinstance(raw_location, dict) else {}
            out.setdefault(key, []).append(
                _FoundField(
                    value=str(node["value"]),
                    source=RowSource(
                        document_id=document.id,
                        filename=document.original_filename,
                        page=location.get("page"),
                        snippet=location.get("snippet"),
                    ),
                )
            )
    return out


def _w2_covers_a_partial_year(
    borrowers: list[Borrower], found: dict[str, list[_FoundField]]
) -> int | None:
    """The W-2 tax year during which employment began, if the data says one did.

    Conservative and coarse on purpose: it compares every extracted `tax_year`
    against every stated employment `start_date`, without pairing a W-2 to the
    employer it belongs to — which nothing in the extraction records. A false
    positive costs an honest "cannot compare"; a false negative costs a wrong
    number presented as a discrepancy, and those are not symmetric.

    Returns None when nothing says the year is partial, including when the
    application states no start date — the absence of evidence is not evidence,
    and flagging every W-2 as uncheckable would empty the row.
    """
    years = set()
    for field in found.get("tax_year", []):
        try:
            years.add(int(Decimal(field.value)))
        except (InvalidOperation, ValueError):
            continue
    if not years:
        return None
    for borrower in borrowers:
        for employer in getattr(borrower, "stated_employers", []):
            start = getattr(employer, "start_date", None)
            if start is not None and int(start.year) in years:
                return int(start.year)
    return None


def _first(found: dict[str, list[_FoundField]], *keys: str) -> _FoundField | None:
    """The first populated field among `keys`, in the order given.

    Order is the caller's preference between synonyms — a W-2's `box_1_wages`
    and a pay stub's `gross_pay` answer the same question with different
    authority, and the caller says which it trusts.
    """
    for key in keys:
        for candidate in found.get(key, []):
            return candidate
    return None


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #


def _decimal(raw: str | Decimal | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return None


def money_agreement(stated: Decimal | None, found: Decimal | None) -> Agreement:
    """Exact-to-the-cent comparison, for values that have no tolerance.

    A valuation or a balance is a number both sides copied from the same place;
    if they differ at all, someone transcribed one of them. ADR-391.
    """
    if stated is None and found is None:
        return Agreement.MISSING
    if stated is None:
        return Agreement.NOT_STATED
    if found is None:
        return Agreement.MISSING
    return Agreement.MATCH if stated == found else Agreement.DIFFERS


def income_agreement(stated: Decimal | None, found: Decimal | None) -> Agreement:
    """Income agrees within the engine's 10% variance.

    Not a tolerance invented here: it is the threshold the deterministic
    cross-source rule already applies, so the ledger and the finding cannot
    disagree about the same two numbers.
    """
    if stated is None and found is None:
        return Agreement.MISSING
    if stated is None:
        return Agreement.NOT_STATED
    if found is None:
        return Agreement.MISSING
    if found == 0:
        return Agreement.MATCH if stated == 0 else Agreement.DIFFERS
    # QUANTIZED to 0.1 before comparing, exactly as `_check_income_variance`
    # does. Importing the threshold is not enough on its own: with a raw
    # comparison here a variance of 10.04% is `satisfied` to the engine (which
    # rounds it to 10.0) and `differs` to this row — the same two numbers, one
    # screen, two answers, which is the whole thing this module promises not to
    # do. The rounding is part of the rule, not a display concern.
    variance = (abs(stated - found) / found * Decimal(100)).quantize(Decimal("0.1"))
    return Agreement.MATCH if variance <= INCOME_VARIANCE_PERCENT else Agreement.DIFFERS


#: Legal-form and trading tokens that carry no identity. "Cascade Robotics Inc."
#: and "Cascade Robotics" are one employer; "Ambio, Inc." and "Ambio, DBA Ambio,
#: Inc" are one employer written two ways by two systems.
_COMPANY_NOISE = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "llp",
        "ltd",
        "limited",
        "co",
        "corp",
        "corporation",
        "company",
        "na",
        "n",
        "a",
        "dba",
        "the",
        "and",
        "of",
        "plc",
        "pllc",
        "pc",
        "lp",
    }
)


def _company_tokens(raw: str) -> frozenset[str]:
    """A company name reduced to the tokens that identify it."""
    return frozenset(normalize_name(raw)) - _COMPANY_NOISE


def name_agreement(stated: str | None, found: str | None) -> Agreement:
    """Employer names agree when their identifying tokens do.

    `normalize_name` is reused for tokenising, casing and accents — but it is a
    PERSON-name normaliser and stops there: measured, `normalize_name("Cascade
    Robotics Inc.") != normalize_name("Cascade Robotics")`, and using it alone
    reported the same employer as a disagreement on real seed data.

    So the legal-form tokens are dropped and the smaller set must be contained in
    the larger — "Ambio" is "Ambio DBA Ambio Inc", and "Bank of America" is still
    not "Wells Fargo". Subset rather than equality because the two sources
    genuinely carry different amounts of the name, and requiring equality would
    make the fuller spelling a defect. ADR-391 records this as new — the engine
    has no employer matcher to reuse.
    """
    if not stated and not found:
        return Agreement.MISSING
    if not stated:
        return Agreement.NOT_STATED
    if not found:
        return Agreement.MISSING
    a, b = _company_tokens(stated), _company_tokens(found)
    if not a or not b:
        # Nothing identifying survived — do not claim agreement from emptiness.
        return Agreement.DIFFERS
    return Agreement.MATCH if a <= b or b <= a else Agreement.DIFFERS


def _money_text(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:,.2f}"


# --------------------------------------------------------------------------- #
# the read model
# --------------------------------------------------------------------------- #


async def reconcile_loan_file(db: AsyncSession, loan_file: LoanFile) -> list[ReconciliationRow]:
    """The reconciliation ledger for one file.

    Tenant scoping is the caller's: every route reaches this through
    `get_loan_file(db, company_id=…)`, which is the same gate the rest of the
    file's endpoints use, so a file id from another company never arrives here.
    """
    documents = await _current_documents(db, loan_file.id)
    found = _found_fields(documents)
    borrowers = await _borrowers(db, loan_file.id)
    property_ = await _property(db, loan_file.id)
    assets = await _assets(db, loan_file.id)

    rows: list[ReconciliationRow] = [
        _income_row(borrowers, found),
        _employer_row(borrowers, found),
        _assets_row(assets, found),
        _valuation_row(property_, found),
        _insurance_row(found),
    ]
    return rows


def _income_row(
    borrowers: list[Borrower], found: dict[str, list[_FoundField]]
) -> ReconciliationRow:
    """Stated monthly income against a DOCUMENTED MONTHLY figure — never a raw one.

    The subtlety that makes this row correct: a pay stub's `gross_pay` is one PAY
    PERIOD, and converting it to monthly requires knowing the frequency. ADR-328
    is explicit that assuming one is "a silent 12x miscalculation", and the
    tag layer is closed to unknown frequency for exactly this reason.

    So a W-2's annual wages are used first — annual by definition, so `/12`
    assumes nothing — and a pay stub is NOT silently treated as monthly. Where
    only a pay-period figure exists the row reports it and says it cannot be
    compared, rather than claiming a disagreement that is really a unit error.
    """
    stated = Decimal(0)
    counted = 0
    for borrower in borrowers:
        for item in borrower.stated_income_items:
            if getattr(item, "employment_income", False) and item.monthly_amount is not None:
                stated += Decimal(item.monthly_amount)
                counted += 1
    stated_total = stated if counted else None

    annual = _first(found, "wages_tips_other_comp", "box_1_wages")
    partial_year = _w2_covers_a_partial_year(borrowers, found)
    if annual is not None and partial_year is not None:
        # A W-2 is annual BY DEFINITION only when the borrower worked the whole
        # year. For a mid-year hire box 1 covers part of one, and `/12`
        # understates monthly income — the same unit error this row exists to
        # avoid, one level down: it would report `differs` against a correctly
        # stated income and send a processor after a discrepancy that is an
        # artefact of the division.
        #
        # How much of a year it covers, and how to annualise it, is underwriting
        # judgement (YTD-plus-W-2 averaging, and which months count) and is NOT
        # decided here. This declines to compute and says why.
        return ReconciliationRow(
            field_key="base_monthly_income",
            label="Base monthly income",
            stated_value=_money_text(stated_total),
            found_value=None,
            agreement=Agreement.MISSING,
            source=annual.source,
            source_note=(
                f"The W-2 covers {partial_year}, and the application states employment "
                f"beginning during that year — so its wages are a partial year and "
                "dividing by 12 would understate monthly income. Annualising a "
                "partial year is an underwriting judgement, not a conversion."
            ),
        )
    if annual is not None:
        found_monthly = _decimal(annual.value)
        if found_monthly is not None:
            found_monthly = (found_monthly / 12).quantize(Decimal("0.01"))
        return _row(
            "base_monthly_income",
            "Base monthly income",
            _money_text(stated_total),
            _money_text(found_monthly),
            income_agreement(stated_total, found_monthly),
            annual,
            no_source_note="No W-2 has been extracted for this file.",
        )

    # A pay stub alone: show what the document says, and say why it is not a
    # comparison. `missing` is the honest agreement — there is no documented
    # MONTHLY income to compare against, which is different from disagreeing.
    period = _first(found, "gross_pay", "gross_pay_current")
    if period is not None:
        return ReconciliationRow(
            field_key="base_monthly_income",
            label="Base monthly income",
            stated_value=_money_text(stated_total),
            found_value=None,
            agreement=Agreement.MISSING,
            source=period.source,
            source_note=(
                "A pay stub shows "
                f"{period.value} for one pay period. Converting that to monthly "
                "needs the pay frequency, which no extracted document states "
                "(ADR-328) — a W-2 would settle it."
            ),
        )

    return _row(
        "base_monthly_income",
        "Base monthly income",
        _money_text(stated_total),
        None,
        income_agreement(stated_total, None),
        None,
        no_source_note="No pay stub or W-2 has been extracted for this file.",
    )


def _employer_row(
    borrowers: list[Borrower], found: dict[str, list[_FoundField]]
) -> ReconciliationRow:
    stated_name: str | None = None
    for borrower in borrowers:
        for employer in borrower.stated_employers:
            if employer.employer_name:
                stated_name = employer.employer_name
                break
        if stated_name:
            break

    hit = _first(found, "employer_name", "employer")
    return _row(
        "employer",
        "Employer",
        stated_name,
        hit.value if hit else None,
        name_agreement(stated_name, hit.value if hit else None),
        hit,
        no_source_note="No document naming an employer has been extracted.",
    )


#: MISMO `AssetType` values that a BANK STATEMENT can evidence. A retirement
#: fund or a gift of cash is a real asset and is not a checking balance; a
#: statement for one says nothing about either.
_DEPOSITORY_ASSET_TYPES = {"checkingaccount", "savingsaccount", "moneymarketfund"}


def _is_depository(asset: StatedAsset) -> bool:
    return (asset.asset_type or "").strip().lower().replace(" ", "") in _DEPOSITORY_ASSET_TYPES


def _assets_row(
    assets: list[StatedAsset], found: dict[str, list[_FoundField]]
) -> ReconciliationRow:
    """A stated DEPOSITORY balance against one bank statement's ending balance.

    The subtlety is the same one the income row is about, and it was got wrong
    here first: the previous version summed EVERY `StatedAsset` — checking,
    savings, retirement, gift funds — and compared the total to a single
    statement's ending balance. For any borrower with more than one account that
    differs by construction, and the row reported it as a discrepancy on a
    compliance screen. The stated side was not the quantity the label named.

    So: only depository assets, which are the ones a bank statement can evidence
    at all; and where the shapes cannot line up — several stated accounts, one
    statement — the row says it cannot be compared and why, rather than
    subtracting two numbers that are not about the same thing. ADR-328's rule,
    applied to assets: a confident wrong answer is worse than an honest gap.
    """
    depository = [a for a in assets if _is_depository(a) and a.value is not None]
    non_depository = [a for a in assets if not _is_depository(a) and a.value is not None]

    hit = _first(found, "ending_balance", "current_balance")
    found_amount = _decimal(hit.value) if hit else None

    # More than one account on the application, one statement in the file. Which
    # account the statement is for is not something this join knows, so any
    # comparison it made would be a guess presented as a finding.
    if len(depository) > 1:
        stated_total = sum(
            (Decimal(a.value) for a in depository if a.value is not None), Decimal(0)
        )
        return ReconciliationRow(
            field_key="checking_balance",
            label="Checking balance",
            stated_value=_money_text(stated_total),
            found_value=_money_text(found_amount),
            agreement=Agreement.MISSING,
            source=hit.source if hit else None,
            source_note=(
                f"The application states {len(depository)} depository accounts totalling "
                f"{_money_text(stated_total)}. One bank statement is on file, and which "
                "account it belongs to is not recorded — so these two figures are not "
                "comparable. A statement per account would settle it."
            ),
        )

    stated_value = Decimal(depository[0].value) if depository and depository[0].value else None
    note = None
    if stated_value is None and non_depository:
        # Assets exist, but none a bank statement speaks to. Saying "no stated
        # value" would read as an omission on the application, which it is not.
        note = (
            f"The application states {len(non_depository)} asset(s), none of them a "
            "depository account — a bank statement does not evidence those."
        )

    return _row(
        "checking_balance",
        "Checking balance",
        _money_text(stated_value),
        _money_text(found_amount),
        money_agreement(stated_value, found_amount),
        hit,
        no_source_note=note or "No bank statement has been extracted for this file.",
    )


def _valuation_row(
    property_: Property | None, found: dict[str, list[_FoundField]]
) -> ReconciliationRow:
    stated_value = None
    if property_ is not None:
        stated_value = _decimal(
            property_.valuation_amount or property_.estimated_value or property_.purchase_price
        )

    hit = _first(found, "appraised_value", "opinion_of_value")
    found_amount = _decimal(hit.value) if hit else None
    return _row(
        "appraised_value",
        "Appraised value",
        _money_text(stated_value),
        _money_text(found_amount),
        money_agreement(stated_value, found_amount),
        hit,
        no_source_note="No appraisal has been extracted for this file.",
    )


def _insurance_row(found: dict[str, list[_FoundField]]) -> ReconciliationRow:
    """The insurance gap.

    Deliberately a row even when both sides are empty. Homeowner's insurance is
    required at closing and the application does not state it, so its absence is
    the finding — a ledger that only listed fields it had data for would omit
    exactly the row a processor needs to act on.
    """
    hit = _first(found, "coverage_amount", "dwelling_coverage")
    return _row(
        "homeowners_insurance",
        "Homeowner's insurance",
        None,
        hit.value if hit else None,
        Agreement.NOT_STATED if hit else Agreement.MISSING,
        hit,
        no_source_note="Not stated on the application, and no declaration page has been received.",
    )


def _row(
    field_key: str,
    label: str,
    stated_value: str | None,
    found_value: str | None,
    agreement: Agreement,
    hit: _FoundField | None,
    *,
    no_source_note: str,
) -> ReconciliationRow:
    """Assemble one row, guaranteeing provenance OR a reason for its absence."""
    return ReconciliationRow(
        field_key=field_key,
        label=label,
        stated_value=stated_value,
        found_value=found_value,
        agreement=agreement,
        source=hit.source if hit else None,
        source_note=None if hit else no_source_note,
    )


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #


async def _current_documents(db: AsyncSession, loan_file_id: UUID) -> list[Document]:
    stmt = only_active(
        select(Document)
        .where(Document.loan_file_id == loan_file_id, Document.is_current.is_(True))
        .options(selectinload(Document.extractions)),
        Document,
        # NEWEST FIRST. `_first()` takes the head of each key's list, so with two
        # pay stubs or two W-2s ascending order handed a processor the OLDEST
        # one — not arbitrary, systematically the stalest evidence on the file.
    ).order_by(Document.created_at.desc(), Document.id.desc())
    return list((await db.execute(stmt)).scalars().all())


async def _borrowers(db: AsyncSession, loan_file_id: UUID) -> list[Borrower]:
    stmt = only_active(
        select(Borrower)
        .where(Borrower.loan_file_id == loan_file_id)
        .options(
            selectinload(Borrower.stated_income_items),
            selectinload(Borrower.stated_employers),
        )
        .order_by(Borrower.borrower_position),
        Borrower,
    )
    return list((await db.execute(stmt)).scalars().all())


async def _property(db: AsyncSession, loan_file_id: UUID) -> Property | None:
    stmt = only_active(select(Property).where(Property.loan_file_id == loan_file_id), Property)
    return (await db.execute(stmt)).scalars().first()


async def _assets(db: AsyncSession, loan_file_id: UUID) -> list[StatedAsset]:
    stmt = only_active(
        select(StatedAsset).where(StatedAsset.loan_file_id == loan_file_id), StatedAsset
    )
    return list((await db.execute(stmt)).scalars().all())
