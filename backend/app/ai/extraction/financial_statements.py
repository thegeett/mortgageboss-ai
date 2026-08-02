"""Financial Statements extraction — GENERATED from a schema spec by the LP-434 generator.

The LP-39a shape: a typed core (each field a ``TypedField`` with source) + a grouped
catch-all (``additional_sections``). Honest nulls, graceful ``.failed()``, and
metadata-only logging — a verbatim mirror of the hand-written flat extractors
(``property_tax_bill`` is the reference).

**GENERATED STARTER — accuracy is UNVALIDATED.** The field set comes from the spec and
the prompt is a scaffold; both need a human pass and Priya's review of real extractions
before they are trusted (guide §11). Structurally correct and mechanically tested is not
the same as tuned.
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

_PROMPT_PATH = "extraction/financial_statements.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class FinancialStatementsExtraction(BaseModel):
    """A financial statements in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    statement_type: TypedField[str] = Field(default_factory=TypedField)
    statement_as_of_date: TypedField[date] = Field(default_factory=TypedField)
    subject_name: TypedField[str] = Field(default_factory=TypedField)
    subject_name_2: TypedField[str] = Field(default_factory=TypedField)
    subject_count: TypedField[int] = Field(default_factory=TypedField)
    subject_names_raw: TypedField[str] = Field(default_factory=TypedField)
    prepared_by: TypedField[str] = Field(default_factory=TypedField)
    accounting_basis: TypedField[str] = Field(default_factory=TypedField)
    joint_with_spouse_indicator: TypedField[str] = Field(default_factory=TypedField)
    total_assets: TypedField[Decimal] = Field(default_factory=TypedField)
    liquid_assets_total: TypedField[Decimal] = Field(default_factory=TypedField)
    total_liabilities: TypedField[Decimal] = Field(default_factory=TypedField)
    net_worth: TypedField[Decimal] = Field(default_factory=TypedField)
    certification_of_accuracy: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    asset_line_items: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class FinancialStatementsExtractionResult(BaseModel):
    """A financial statements extraction plus its outcome (mirrors the other extractor results)."""

    data: FinancialStatementsExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "FinancialStatementsExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=FinancialStatementsExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("statement_type", coerce_str),
    ("statement_as_of_date", coerce_date),
    ("subject_name", coerce_str),
    ("subject_name_2", coerce_str),
    ("subject_count", coerce_int),
    ("subject_names_raw", coerce_str),
    ("prepared_by", coerce_str),
    ("accounting_basis", coerce_str),
    ("joint_with_spouse_indicator", coerce_str),
    ("total_assets", coerce_decimal),
    ("liquid_assets_total", coerce_decimal),
    ("total_liabilities", coerce_decimal),
    ("net_worth", coerce_decimal),
    ("certification_of_accuracy", coerce_str),
)


_ASSET_LINE_ITEMS_ROW: CoreSpec = (
    ("category", coerce_str),
    ("description", coerce_str),
    ("value", coerce_decimal),
    ("source", coerce_str),
)


def _parse_asset_line_items(raw: Any) -> list[dict[str, Any]]:
    """Coerce the asset_line_items rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _ASSET_LINE_ITEMS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _ASSET_LINE_ITEMS_ROW):
            rows.append(row)
    return rows


def _parse_financial_statements_json(text: str) -> FinancialStatementsExtractionResult | None:
    """Defensively parse a model response into a financial statements result. Never raises."""
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
    asset_line_items = _parse_asset_line_items(payload.get("asset_line_items"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = FinancialStatementsExtraction.model_validate(
            {**core_payload, "asset_line_items": asset_line_items, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(asset_line_items), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return FinancialStatementsExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_financial_statements(
    content: bytes, media_type: str
) -> FinancialStatementsExtractionResult:
    """Extract financial statements values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return FinancialStatementsExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return FinancialStatementsExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="financial_statements",
    )
    if call.text is None:
        return FinancialStatementsExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_financial_statements_json(call.text)
    if result is None:
        logger.warning("financial_statements_extraction_parse_failed")  # no raw response logged
        return FinancialStatementsExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "financial_statements_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.asset_line_items),
    )
    return result
