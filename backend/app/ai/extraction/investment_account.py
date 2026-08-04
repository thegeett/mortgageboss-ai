"""Investment account extraction (LP-61) — Tier 1 asset, following the LP-39a shape.

A brokerage/investment statement (stocks, bonds, funds) is a non-cash asset toward
**reserves** (the lender-required cushion). The decision figure is the account's
**total market value**; the individual holdings (if itemized) land in the grouped
catch-all — a flat typed core + catch-all, like the W-2, not the bank statement's
first-class transactions list.

Mirrors :mod:`app.ai.extraction.bank_statement` (the closest template — an asset
doc with a masked account number, a statement period, and balances): typed core
(each a ``TypedField`` with source) + ``additional_sections`` catch-all, Opus
full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging.

**Account number (ADR-149).** ``account_number_masked`` is captured masked (last 4),
**never logged**, and displayed masked. Typed core is a **V1 starter — refine with
Priya**; accuracy is validated as real statements flow through (no samples were
available when this was built).
"""

import json
from datetime import date
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
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/investment_account.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A brokerage statement itemizes an UNBOUNDED holdings list (each position: ticker, shares, value),
# each with a verbatim snippet → a long list = long JSON. 4096 truncated on a dense portfolio
# (observed on LF-6T3N — a silently-empty ASSET doc that understates reserves), so 8192 like
# bank_statement (LP-103). The LP-102 shared guard (model_call) is the backstop if one still overflows.
_MAX_TOKENS = 8192


class InvestmentAccountExtraction(BaseModel):
    """An investment statement in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the institution + holder + masked account + period +
    ``total_value`` (the reserves figure). **Grouped catch-all** — the individual
    holdings (ticker/shares/value), cost basis, gain/loss, etc. — nothing lost.

    ``account_number_masked`` is **sensitive** — never logged; masked in display.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    institution_name: TypedField[str] = Field(default_factory=TypedField)
    account_holder: TypedField[str] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    account_type: TypedField[str] = Field(default_factory=TypedField)  # brokerage / 529 / ...
    statement_period_start: TypedField[date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[date] = Field(default_factory=TypedField)
    total_value: TypedField[Decimal] = Field(default_factory=TypedField)  # KEY reserves figure

    # --- Grouped catch-all — everything else (holdings, etc.) --------------- #
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    brokerage_or_custodian_name: TypedField[str] = Field(default_factory=TypedField)
    document_title: TypedField[str] = Field(default_factory=TypedField)
    account_registration_names_raw: TypedField[str] = Field(default_factory=TypedField)
    account_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    account_owner_count: TypedField[int] = Field(default_factory=TypedField)
    statement_date: TypedField[date] = Field(default_factory=TypedField)
    cash_and_cash_equivalents: TypedField[Decimal] = Field(default_factory=TypedField)
    securities_market_value: TypedField[Decimal] = Field(default_factory=TypedField)
    margin_or_securities_backed_loan_balance: TypedField[Decimal] = Field(
        default_factory=TypedField
    )
    net_liquidation_value: TypedField[Decimal] = Field(default_factory=TypedField)
    vested_or_available_value: TypedField[Decimal] = Field(default_factory=TypedField)
    liquidation_restrictions: TypedField[str] = Field(default_factory=TypedField)
    document_status_or_version: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-446 diff — captured nested list(s) (bare rows) --------------------- #
    security_positions: list[dict[str, Any]] = Field(default_factory=list)

    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class InvestmentAccountExtractionResult(BaseModel):
    """An investment-account extraction plus its outcome (mirrors the other results)."""

    data: InvestmentAccountExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "InvestmentAccountExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=InvestmentAccountExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("institution_name", coerce_str),
    ("account_holder", coerce_str),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("statement_period_start", coerce_date),
    ("statement_period_end", coerce_date),
    ("total_value", coerce_decimal),
    # LP-446 diff additions
    ("brokerage_or_custodian_name", coerce_str),
    ("document_title", coerce_str),
    ("account_registration_names_raw", coerce_str),
    ("account_owner_name_2", coerce_str),
    ("account_owner_count", coerce_int),
    ("statement_date", coerce_date),
    ("cash_and_cash_equivalents", coerce_decimal),
    ("securities_market_value", coerce_decimal),
    ("margin_or_securities_backed_loan_balance", coerce_decimal),
    ("net_liquidation_value", coerce_decimal),
    ("vested_or_available_value", coerce_decimal),
    ("liquidation_restrictions", coerce_str),
    ("document_status_or_version", coerce_str),
)

_SECURITY_POSITIONS_ROW: CoreSpec = (
    ("description", coerce_str),
    ("ticker_or_cusip", coerce_str),
    ("quantity", coerce_str),
    ("market_value", coerce_str),
    ("asset_class", coerce_str),
    ("source", coerce_str),
)


def _parse_rows(raw: Any, row_spec: CoreSpec) -> list[dict[str, Any]]:
    """LP-446 — coerce a bare-row list (each declared field coerced, a per-row source kept, empty rows
    dropped). Mirrors bank_statement's transactions parse; row values are read as strings by the snapshot."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {name: coerce(entry.get(name)) for name, coerce in row_spec}
        row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in row_spec):
            rows.append(row)
    return rows


def _parse_investment_json(text: str) -> InvestmentAccountExtractionResult | None:
    """Defensively parse a model response into an investment result. Never raises."""
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
    security_positions = _parse_rows(payload.get("security_positions"), _SECURITY_POSITIONS_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = InvestmentAccountExtraction.model_validate(
            {
                **core_payload,
                "security_positions": security_positions,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(security_positions), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return InvestmentAccountExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_investment_account(
    content: bytes, media_type: str
) -> InvestmentAccountExtractionResult:
    """Extract investment-account values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.bank_statement.extract_bank_statement`. The
    bytes/base64, raw response, extracted values, and the **account number** are
    never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return InvestmentAccountExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return InvestmentAccountExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="investment_account",
    )
    if call.text is None:
        return InvestmentAccountExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_investment_json(call.text)
    if result is None:
        logger.warning("investment_account_extraction_parse_failed")  # no raw response logged
        return InvestmentAccountExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values/account number.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "investment_account_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
