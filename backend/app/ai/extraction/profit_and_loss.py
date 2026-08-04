"""Profit & Loss extraction (LP-60) — Tier 1 income/employment, the LP-39a shape.

A Profit & Loss (P&L) / income statement reports a self-employed borrower's
business income over a period. The **key figure is net profit** — the
self-employment income Phase 3 qualifies on. The typed core captures the business,
the period, and the revenue/expense/net summary; the individual expense lines land
in the grouped catch-all (a "Major Expenses" section), so the full statement is
preserved and a line can be promoted to the typed core later.

Mirrors :mod:`app.ai.extraction.w2`: typed core + ``additional_sections``, Opus
full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging. Typed core is a **V1 starter — refine with
Priya**; accuracy is validated as real P&Ls flow through (no samples were available
when this was built).
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

_PROMPT_PATH = "extraction/profit_and_loss.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A P&L itemizes an UNBOUNDED list of revenue + expense lines (each expense line item), each with a
# verbatim snippet → a long list = long JSON. 8192 like bank_statement so a detailed statement isn't
# truncated (LP-103). The LP-102 shared guard (model_call) is the backstop for any overflow.
_MAX_TOKENS = 8192


class ProfitAndLossExtraction(BaseModel):
    """A P&L in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the business + period + the revenue/expense/net summary;
    ``net_profit`` is the key self-employment-income figure. **Grouped catch-all**
    — the individual expense lines (a "Major Expenses" section), cost of goods,
    owner draws, etc. — nothing lost.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    business_name: TypedField[str] = Field(default_factory=TypedField)
    period_start: TypedField[date] = Field(default_factory=TypedField)
    period_end: TypedField[date] = Field(default_factory=TypedField)
    total_revenue: TypedField[Decimal] = Field(default_factory=TypedField)
    total_expenses: TypedField[Decimal] = Field(default_factory=TypedField)
    net_profit: TypedField[Decimal] = Field(default_factory=TypedField)  # the KEY figure

    # --- Grouped catch-all — everything else, by section -------------------- #
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    statement_type: TypedField[str] = Field(default_factory=TypedField)
    accounting_basis: TypedField[str] = Field(default_factory=TypedField)
    prepared_by: TypedField[str] = Field(default_factory=TypedField)
    preparer_relationship: TypedField[str] = Field(default_factory=TypedField)
    cpa_review_compilation_or_audit_level: TypedField[str] = Field(default_factory=TypedField)
    total_cost_of_goods_sold: TypedField[Decimal] = Field(default_factory=TypedField)
    gross_profit: TypedField[Decimal] = Field(default_factory=TypedField)
    operating_income: TypedField[Decimal] = Field(default_factory=TypedField)
    total_assets: TypedField[Decimal] = Field(default_factory=TypedField)
    cash_and_cash_equivalents: TypedField[Decimal] = Field(default_factory=TypedField)
    total_liabilities: TypedField[Decimal] = Field(default_factory=TypedField)
    owner_or_shareholder_equity: TypedField[Decimal] = Field(default_factory=TypedField)
    management_certification: TypedField[str] = Field(default_factory=TypedField)
    signer_name_title: TypedField[str] = Field(default_factory=TypedField)
    signature_and_date: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-446 diff — captured nested list(s) (bare rows) --------------------- #
    financial_line_items: list[dict[str, Any]] = Field(default_factory=list)

    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class ProfitAndLossExtractionResult(BaseModel):
    """A P&L extraction plus its outcome (mirrors ``W2ExtractionResult``)."""

    data: ProfitAndLossExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "ProfitAndLossExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=ProfitAndLossExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("business_name", coerce_str),
    ("period_start", coerce_date),
    ("period_end", coerce_date),
    ("total_revenue", coerce_decimal),
    ("total_expenses", coerce_decimal),
    ("net_profit", coerce_decimal),
    # LP-446 diff additions
    ("issuer_name", coerce_str),
    ("statement_type", coerce_str),
    ("accounting_basis", coerce_str),
    ("prepared_by", coerce_str),
    ("preparer_relationship", coerce_str),
    ("cpa_review_compilation_or_audit_level", coerce_str),
    ("total_cost_of_goods_sold", coerce_decimal),
    ("gross_profit", coerce_decimal),
    ("operating_income", coerce_decimal),
    ("total_assets", coerce_decimal),
    ("cash_and_cash_equivalents", coerce_decimal),
    ("total_liabilities", coerce_decimal),
    ("owner_or_shareholder_equity", coerce_decimal),
    ("management_certification", coerce_str),
    ("signer_name_title", coerce_str),
    ("signature_and_date", coerce_str),
)

_FINANCIAL_LINE_ITEMS_ROW: CoreSpec = (
    ("section", coerce_str),
    ("label", coerce_str),
    ("amount", coerce_str),
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


def _parse_pnl_json(text: str) -> ProfitAndLossExtractionResult | None:
    """Defensively parse a model response into a P&L result. Never raises."""
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
    financial_line_items = _parse_rows(
        payload.get("financial_line_items"), _FINANCIAL_LINE_ITEMS_ROW
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = ProfitAndLossExtraction.model_validate(
            {
                **core_payload,
                "financial_line_items": financial_line_items,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(financial_line_items), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return ProfitAndLossExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_profit_and_loss(content: bytes, media_type: str) -> ProfitAndLossExtractionResult:
    """Extract structured P&L values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`. The bytes/base64, raw
    response, and extracted values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return ProfitAndLossExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return ProfitAndLossExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="profit_and_loss",
    )
    if call.text is None:
        return ProfitAndLossExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_pnl_json(call.text)
    if result is None:
        logger.warning("pnl_extraction_parse_failed")  # no raw response logged
        return ProfitAndLossExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — NEVER the values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "pnl_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
