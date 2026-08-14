"""Form 1098 extraction — GENERATED from a schema spec by the LP-434 generator.

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
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/form_1098.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class Form1098Extraction(BaseModel):
    """A form 1098 in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_address: TypedField[str] = Field(default_factory=TypedField)
    borrower_tin_masked: TypedField[str] = Field(default_factory=TypedField)
    lender_name: TypedField[str] = Field(default_factory=TypedField)
    lender_address: TypedField[str] = Field(default_factory=TypedField)
    lender_tin: TypedField[str] = Field(default_factory=TypedField)
    lender_phone: TypedField[str] = Field(default_factory=TypedField)
    account_number: TypedField[str] = Field(default_factory=TypedField)
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    mortgage_interest_received: TypedField[Decimal] = Field(default_factory=TypedField)
    outstanding_mortgage_principal: TypedField[Decimal] = Field(default_factory=TypedField)
    mortgage_origination_date: TypedField[date] = Field(default_factory=TypedField)
    refund_of_overpaid_interest: TypedField[Decimal] = Field(default_factory=TypedField)
    mortgage_insurance_premiums: TypedField[Decimal] = Field(default_factory=TypedField)
    points_paid_on_purchase: TypedField[Decimal] = Field(default_factory=TypedField)
    property_address_same_as_borrower_indicator: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    number_of_properties: TypedField[int] = Field(default_factory=TypedField)
    other_information: TypedField[str] = Field(default_factory=TypedField)
    mortgage_acquisition_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class Form1098ExtractionResult(BaseModel):
    """A form 1098 extraction plus its outcome (mirrors the other extractor results)."""

    data: Form1098Extraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "Form1098ExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=Form1098Extraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("borrower_name", coerce_str),
    ("borrower_address", coerce_str),
    ("borrower_tin_masked", coerce_str),
    ("lender_name", coerce_str),
    ("lender_address", coerce_str),
    ("lender_tin", coerce_str),
    ("lender_phone", coerce_str),
    ("account_number", coerce_str),
    ("tax_year", coerce_int),
    ("mortgage_interest_received", coerce_decimal),
    ("outstanding_mortgage_principal", coerce_decimal),
    ("mortgage_origination_date", coerce_date),
    ("refund_of_overpaid_interest", coerce_decimal),
    ("mortgage_insurance_premiums", coerce_decimal),
    ("points_paid_on_purchase", coerce_decimal),
    ("property_address_same_as_borrower_indicator", coerce_str),
    ("property_address", coerce_str),
    ("number_of_properties", coerce_int),
    ("other_information", coerce_str),
    ("mortgage_acquisition_date", coerce_date),
)


def _parse_form_1098_json(text: str) -> Form1098ExtractionResult | None:
    """Defensively parse a model response into a form 1098 result. Never raises."""
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
        data = Form1098Extraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return Form1098ExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_form_1098(content: bytes, media_type: str) -> Form1098ExtractionResult:
    """Extract form 1098 values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return Form1098ExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return Form1098ExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="form_1098",
    )
    if call.text is None:
        return Form1098ExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_form_1098_json(call.text)
    if result is None:
        logger.warning("form_1098_extraction_parse_failed")  # no raw response logged
        return Form1098ExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "form_1098_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
