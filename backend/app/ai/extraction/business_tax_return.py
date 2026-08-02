"""Business Tax Return extraction — GENERATED from a schema spec by the LP-434 generator.

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
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/business_tax_return.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class BusinessTaxReturnExtraction(BaseModel):
    """A business tax return in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    return_form_type: TypedField[str] = Field(default_factory=TypedField)
    tax_period_start: TypedField[date] = Field(default_factory=TypedField)
    tax_period_end: TypedField[date] = Field(default_factory=TypedField)
    business_legal_name: TypedField[str] = Field(default_factory=TypedField)
    ein: TypedField[str] = Field(default_factory=TypedField)
    business_address: TypedField[str] = Field(default_factory=TypedField)
    entity_type: TypedField[str] = Field(default_factory=TypedField)
    accounting_method: TypedField[str] = Field(default_factory=TypedField)
    initial_final_or_amended_return: TypedField[str] = Field(default_factory=TypedField)
    date_business_started_or_incorporated: TypedField[date] = Field(default_factory=TypedField)
    principal_business_activity: TypedField[str] = Field(default_factory=TypedField)
    naics_or_activity_code: TypedField[str] = Field(default_factory=TypedField)
    gross_receipts_or_sales: TypedField[Decimal] = Field(default_factory=TypedField)
    gross_profit: TypedField[Decimal] = Field(default_factory=TypedField)
    ordinary_or_taxable_income: TypedField[Decimal] = Field(default_factory=TypedField)
    depreciation_and_amortization: TypedField[Decimal] = Field(default_factory=TypedField)
    depletion: TypedField[Decimal] = Field(default_factory=TypedField)
    guaranteed_payments: TypedField[Decimal] = Field(default_factory=TypedField)
    distributions_or_dividends: TypedField[Decimal] = Field(default_factory=TypedField)
    retained_earnings_or_capital: TypedField[Decimal] = Field(default_factory=TypedField)
    authorized_signer_name_title: TypedField[str] = Field(default_factory=TypedField)
    signature_date: TypedField[date] = Field(default_factory=TypedField)
    paid_preparer_name: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BusinessTaxReturnExtractionResult(BaseModel):
    """A business tax return extraction plus its outcome (mirrors the other extractor results)."""

    data: BusinessTaxReturnExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BusinessTaxReturnExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BusinessTaxReturnExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("return_form_type", coerce_str),
    ("tax_period_start", coerce_date),
    ("tax_period_end", coerce_date),
    ("business_legal_name", coerce_str),
    ("ein", coerce_str),
    ("business_address", coerce_str),
    ("entity_type", coerce_str),
    ("accounting_method", coerce_str),
    ("initial_final_or_amended_return", coerce_str),
    ("date_business_started_or_incorporated", coerce_date),
    ("principal_business_activity", coerce_str),
    ("naics_or_activity_code", coerce_str),
    ("gross_receipts_or_sales", coerce_decimal),
    ("gross_profit", coerce_decimal),
    ("ordinary_or_taxable_income", coerce_decimal),
    ("depreciation_and_amortization", coerce_decimal),
    ("depletion", coerce_decimal),
    ("guaranteed_payments", coerce_decimal),
    ("distributions_or_dividends", coerce_decimal),
    ("retained_earnings_or_capital", coerce_decimal),
    ("authorized_signer_name_title", coerce_str),
    ("signature_date", coerce_date),
    ("paid_preparer_name", coerce_str),
)


def _parse_business_tax_return_json(text: str) -> BusinessTaxReturnExtractionResult | None:
    """Defensively parse a model response into a business tax return result. Never raises."""
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
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = BusinessTaxReturnExtraction.model_validate(
            {**core_payload, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return BusinessTaxReturnExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_business_tax_return(
    content: bytes, media_type: str
) -> BusinessTaxReturnExtractionResult:
    """Extract business tax return values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BusinessTaxReturnExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BusinessTaxReturnExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="business_tax_return",
    )
    if call.text is None:
        return BusinessTaxReturnExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_business_tax_return_json(call.text)
    if result is None:
        logger.warning("business_tax_return_extraction_parse_failed")  # no raw response logged
        return BusinessTaxReturnExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "business_tax_return_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
