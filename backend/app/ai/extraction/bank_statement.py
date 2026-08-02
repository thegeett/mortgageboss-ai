"""Bank statement extraction (LP-39c) — the hardest of the three Phase 1 types.

A pay stub / W-2 are flat (typed core + catch-all). A bank statement's key content
is a **list of transactions** (often dozens, across multiple pages) plus balances,
so the schema extends the LP-39a shape with a **first-class typed transactions
list** (ADR-061 — transactions live in the extraction JSON as structured rows):

    typed core (account/balance fields) + transactions[] + grouped catch-all

Mirrors the pay stub / W-2 modules and reuses the shared parser
(:mod:`app.ai.extraction.parsing`). Keeps all the shape guarantees: full-document
Opus reading, honest nulls / **no hallucinated transactions**, tolerant coercion
(a single bad field/row → ``None``, never failing the whole extraction), defensive
parsing, graceful failure (never raises), metadata-only logging.

**Hard parts (deliberate):** the transaction table spans pages (Option A — send the
whole document; the per-request page/size/token concern from the LP-37 revision is
most acute here), and a long list = long JSON, so ``max_tokens`` is generous and a
**truncated/malformed** response fails gracefully (``.failed()``), never crashing.

**Account number (ADR-149).** ``account_number_masked`` is captured masked, **never
logged**, and **displayed masked** (last-4) — the LP-39b SSN pattern, generalized.
"""

import datetime
import json
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
    coerce_decimal,
    coerce_int,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
    source_payload,
)
from app.ai.extraction.shape import CatchAllSection, SourceLocation, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus
from app.services.pdf_utils import pdf_page_count

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/bank_statement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bank statements can have long, multi-page transaction lists → generous cap so the
# list isn't truncated. A truncated/malformed response still fails gracefully.
_MAX_TOKENS = 8192


class Transaction(BaseModel):
    """One structured transaction row (ADR-061). Money as ``Decimal``, date as ``date``."""

    date: datetime.date | None = None
    description: str | None = None
    amount: Decimal | None = None
    transaction_type: str | None = None  # deposit / withdrawal / fee / interest / ...
    running_balance: Decimal | None = None
    source: SourceLocation | None = None


class BankStatementExtraction(BaseModel):
    """A bank statement: typed core + a typed transactions list + grouped catch-all.

    **Typed core** — account/balance fields (identity + assets/reserves + recency),
    each a :class:`TypedField` with source. **V1 starter — refine with Priya; grows
    in Phase 3.** **Transactions** — the decision-relevant list (deposits, ending
    balance, fees) as structured rows. **Catch-all** — everything else.

    ``account_number_masked`` is **sensitive** — never logged; masked in display.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    account_holder_name: TypedField[str] = Field(default_factory=TypedField)
    bank_name: TypedField[str] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    account_type: TypedField[str] = Field(default_factory=TypedField)  # checking / savings
    statement_period_start: TypedField[datetime.date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[datetime.date] = Field(default_factory=TypedField)
    beginning_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    ending_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    total_deposits: TypedField[Decimal] = Field(default_factory=TypedField)
    total_withdrawals: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- LP-446 diff (002 spec) — the exists_today:false additions ----------- #
    # account_owner_name_2 / account_owner_count unblock AS-6's joint-account blindness (the co-holder gap).
    account_holder_names_raw: TypedField[str] = Field(default_factory=TypedField)
    account_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    account_owner_count: TypedField[int] = Field(default_factory=TypedField)
    account_holder_address: TypedField[str] = Field(default_factory=TypedField)
    account_status: TypedField[str] = Field(default_factory=TypedField)
    available_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    average_daily_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    nsf_fee_count: TypedField[int] = Field(default_factory=TypedField)
    nsf_fee_total: TypedField[Decimal] = Field(default_factory=TypedField)
    fees_total: TypedField[Decimal] = Field(default_factory=TypedField)
    minimum_balance_requirement: TypedField[Decimal] = Field(default_factory=TypedField)
    holds_or_pledges: TypedField[str] = Field(default_factory=TypedField)
    interest_paid: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Transactions (the structurally-new part, ADR-061) ------------------ #
    transactions: list[Transaction] = Field(default_factory=list)

    # --- Page completeness (LP-381, AS-9) ----------------------------------- #
    # page_count_declared: the "of N" the statement PRINTS ("Page 1 of 5") — a MODEL read (null if not printed).
    # page_count_present: the DETERMINISTIC actual page total, set from the PDF post-extraction (NOT the model).
    page_count_declared: TypedField[int] = Field(default_factory=TypedField)
    page_count_present: TypedField[int] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BankStatementExtractionResult(BaseModel):
    """A bank statement extraction plus its outcome (mirrors the other result types)."""

    data: BankStatementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BankStatementExtractionResult":
        """The graceful fallback: empty data, ``FAILED``, zero confidence."""
        return cls(
            data=BankStatementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


# Typed-core fields + the coercer for each (transactions + everything else handled separately).
_CORE_SPEC: CoreSpec = (
    ("account_holder_name", coerce_str),
    ("bank_name", coerce_str),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("statement_period_start", coerce_date),
    ("statement_period_end", coerce_date),
    ("beginning_balance", coerce_decimal),
    ("ending_balance", coerce_decimal),
    ("total_deposits", coerce_decimal),
    ("total_withdrawals", coerce_decimal),
    # LP-446 diff additions
    ("account_holder_names_raw", coerce_str),
    ("account_owner_name_2", coerce_str),
    ("account_owner_count", coerce_int),
    ("account_holder_address", coerce_str),
    ("account_status", coerce_str),
    ("available_balance", coerce_decimal),
    ("average_daily_balance", coerce_decimal),
    ("nsf_fee_count", coerce_int),
    ("nsf_fee_total", coerce_decimal),
    ("fees_total", coerce_decimal),
    ("minimum_balance_requirement", coerce_decimal),
    ("holds_or_pledges", coerce_str),
    ("interest_paid", coerce_decimal),
    (
        "page_count_declared",
        coerce_int,
    ),  # LP-381 — the printed "of N"; page_count_present is set separately
)


def _parse_transactions(raw: Any) -> list[dict[str, Any]]:
    """Coerce the transactions list (date/amount/running_balance typed; source kept).

    **No hallucination**: only the rows the model returned are kept. A row's bad
    field → ``None`` (the row is kept), and a fully-empty row is dropped. Non-dict
    entries are skipped. Strings stay as-is.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row = {
            "date": coerce_date(entry.get("date")),
            "description": coerce_str(entry.get("description")),
            "amount": coerce_decimal(entry.get("amount")),
            "transaction_type": coerce_str(entry.get("transaction_type")),
            "running_balance": coerce_decimal(entry.get("running_balance")),
            "source": source_payload(entry),
        }
        # Drop a fully-empty row (junk) — keep any row with at least one read value.
        if any(row[k] is not None for k in ("date", "description", "amount", "running_balance")):
            rows.append(row)
    return rows


def _parse_bank_statement_json(text: str) -> BankStatementExtractionResult | None:
    """Defensively parse a model response into the result. Never raises.

    Reads ``typed_core`` + ``transactions`` + ``additional_sections`` via the shared
    helpers. Status is derived from the typed core **and** the transactions (either
    counts as content). A truncated/malformed response → ``None`` (the caller fails
    gracefully). Returns ``None`` only when no JSON object can be parsed.
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    transactions = _parse_transactions(payload.get("transactions"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = BankStatementExtraction.model_validate(
            {**core_payload, "transactions": transactions, "additional_sections": sections}
        )
    except ValidationError:
        return None

    # Transactions count as extracted content (a statement may be mostly its list).
    status = derive_status(non_null + len(transactions), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return BankStatementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_bank_statement(content: bytes, media_type: str) -> BankStatementExtractionResult:
    """Extract a bank statement (incl. its transactions) from bytes. Never raises.

    Mirrors the other extractors: empty/unsupported → ``failed`` without an API
    call; otherwise loads the prompt, sends the full document to the Opus-class
    model, and parses defensively (a truncated long transaction list → ``failed``).
    The bytes/base64, raw response, extracted values, transactions, and the
    **account number** are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BankStatementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BankStatementExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="bank_statement",
    )
    if call.text is None:
        return BankStatementExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_bank_statement_json(call.text)
    if result is None:
        logger.warning("bank_statement_extraction_parse_failed")  # truncated/malformed
        return BankStatementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # LP-381 (AS-9): page_count_present is the DETERMINISTIC page total — computed from the PDF, never a model
    # read (a model can miscount, and completeness must not be fabricated). Absent for non-PDF statements →
    # AS-9 honestly couldnt_checks. page_count_declared (the printed "of N") is the model's job, above.
    present = (
        await pdf_page_count(content) if media_type.lower().strip() == "application/pdf" else None
    )
    if present is not None:
        result.data.page_count_present = TypedField(value=present)

    # Metadata only: status, confidence, COUNTS — never values/account number/transactions.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "bank_statement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        transaction_count=len(result.data.transactions),
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
