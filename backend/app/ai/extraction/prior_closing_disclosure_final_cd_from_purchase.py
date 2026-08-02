"""Prior Closing Disclosure Final Cd From Purchase extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/prior_closing_disclosure_final_cd_from_purchase.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class PriorClosingDisclosureFinalCdFromPurchaseExtraction(BaseModel):
    """A prior closing disclosure final cd from purchase in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    borrower_names_raw: TypedField[str] = Field(default_factory=TypedField)
    seller_name: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    lender_name: TypedField[str] = Field(default_factory=TypedField)
    settlement_agent_name: TypedField[str] = Field(default_factory=TypedField)
    settlement_file_number: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)
    closing_date: TypedField[date] = Field(default_factory=TypedField)
    disbursement_date: TypedField[date] = Field(default_factory=TypedField)
    cd_delivery_or_received_date: TypedField[date] = Field(default_factory=TypedField)
    final_or_corrected_indicator: TypedField[str] = Field(default_factory=TypedField)
    loan_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    sale_price: TypedField[Decimal] = Field(default_factory=TypedField)
    loan_purpose: TypedField[str] = Field(default_factory=TypedField)
    interest_rate: TypedField[str] = Field(default_factory=TypedField)
    apr: TypedField[str] = Field(default_factory=TypedField)
    monthly_principal_and_interest: TypedField[Decimal] = Field(default_factory=TypedField)
    total_closing_costs: TypedField[Decimal] = Field(default_factory=TypedField)
    cash_to_close: TypedField[Decimal] = Field(default_factory=TypedField)
    lender_credits: TypedField[Decimal] = Field(default_factory=TypedField)
    seller_credits: TypedField[Decimal] = Field(default_factory=TypedField)
    deposit_or_earnest_money: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PriorClosingDisclosureFinalCdFromPurchaseExtractionResult(BaseModel):
    """A prior closing disclosure final cd from purchase extraction plus its outcome (mirrors the other extractor results)."""

    data: PriorClosingDisclosureFinalCdFromPurchaseExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PriorClosingDisclosureFinalCdFromPurchaseExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PriorClosingDisclosureFinalCdFromPurchaseExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("borrower_names_raw", coerce_str),
    ("seller_name", coerce_str),
    ("property_address", coerce_str),
    ("lender_name", coerce_str),
    ("settlement_agent_name", coerce_str),
    ("settlement_file_number", coerce_str),
    ("loan_number", coerce_str),
    ("closing_date", coerce_date),
    ("disbursement_date", coerce_date),
    ("cd_delivery_or_received_date", coerce_date),
    ("final_or_corrected_indicator", coerce_str),
    ("loan_amount", coerce_decimal),
    ("sale_price", coerce_decimal),
    ("loan_purpose", coerce_str),
    ("interest_rate", coerce_str),
    ("apr", coerce_str),
    ("monthly_principal_and_interest", coerce_decimal),
    ("total_closing_costs", coerce_decimal),
    ("cash_to_close", coerce_decimal),
    ("lender_credits", coerce_decimal),
    ("seller_credits", coerce_decimal),
    ("deposit_or_earnest_money", coerce_decimal),
)


def _parse_prior_closing_disclosure_final_cd_from_purchase_json(
    text: str,
) -> PriorClosingDisclosureFinalCdFromPurchaseExtractionResult | None:
    """Defensively parse a model response into a prior closing disclosure final cd from purchase result. Never raises."""
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
        data = PriorClosingDisclosureFinalCdFromPurchaseExtraction.model_validate(
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
    return PriorClosingDisclosureFinalCdFromPurchaseExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_prior_closing_disclosure_final_cd_from_purchase(
    content: bytes, media_type: str
) -> PriorClosingDisclosureFinalCdFromPurchaseExtractionResult:
    """Extract prior closing disclosure final cd from purchase values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PriorClosingDisclosureFinalCdFromPurchaseExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PriorClosingDisclosureFinalCdFromPurchaseExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="prior_closing_disclosure_final_cd_from_purchase",
    )
    if call.text is None:
        return PriorClosingDisclosureFinalCdFromPurchaseExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_prior_closing_disclosure_final_cd_from_purchase_json(call.text)
    if result is None:
        logger.warning(
            "prior_closing_disclosure_final_cd_from_purchase_extraction_parse_failed"
        )  # no raw response logged
        return PriorClosingDisclosureFinalCdFromPurchaseExtractionResult.failed(
            "could not parse extraction"
        )

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "prior_closing_disclosure_final_cd_from_purchase_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
