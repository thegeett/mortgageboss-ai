"""Application 1003 extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/application_1003.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class Application1003Extraction(BaseModel):
    """A application 1003 in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    borrower_legal_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    borrower_count: TypedField[int] = Field(default_factory=TypedField)
    social_security_number: TypedField[str] = Field(default_factory=TypedField)
    social_security_number_2: TypedField[str] = Field(default_factory=TypedField)
    date_of_birth: TypedField[date] = Field(default_factory=TypedField)
    date_of_birth_2: TypedField[date] = Field(default_factory=TypedField)
    marital_status: TypedField[str] = Field(default_factory=TypedField)
    citizenship_residency_status: TypedField[str] = Field(default_factory=TypedField)
    current_address: TypedField[str] = Field(default_factory=TypedField)
    current_address_type: TypedField[str] = Field(default_factory=TypedField)
    mailing_address: TypedField[str] = Field(default_factory=TypedField)
    current_address_duration_months: TypedField[int] = Field(default_factory=TypedField)
    current_housing_status: TypedField[str] = Field(default_factory=TypedField)
    stated_monthly_income_total: TypedField[Decimal] = Field(default_factory=TypedField)
    loan_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    loan_purpose: TypedField[str] = Field(default_factory=TypedField)
    property_value_or_purchase_price: TypedField[Decimal] = Field(default_factory=TypedField)
    lender_loan_number: TypedField[str] = Field(default_factory=TypedField)
    universal_loan_identifier: TypedField[str] = Field(default_factory=TypedField)
    subject_property_address: TypedField[str] = Field(default_factory=TypedField)
    number_of_units: TypedField[int] = Field(default_factory=TypedField)
    property_type: TypedField[str] = Field(default_factory=TypedField)
    occupancy_intent: TypedField[str] = Field(default_factory=TypedField)
    estate_type: TypedField[str] = Field(default_factory=TypedField)
    manufactured_home_indicator: TypedField[str] = Field(default_factory=TypedField)
    mixed_use_indicator: TypedField[str] = Field(default_factory=TypedField)
    declaration_borrowed_down_payment: TypedField[str] = Field(default_factory=TypedField)
    declaration_primary_residence: TypedField[str] = Field(default_factory=TypedField)
    declaration_other_mortgage_application: TypedField[str] = Field(default_factory=TypedField)
    demographic_section_present: TypedField[str] = Field(default_factory=TypedField)
    application_signed_date: TypedField[date] = Field(default_factory=TypedField)
    application_taken_date: TypedField[date] = Field(default_factory=TypedField)
    is_signed: TypedField[str] = Field(default_factory=TypedField)
    form_version: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class Application1003ExtractionResult(BaseModel):
    """A application 1003 extraction plus its outcome (mirrors the other extractor results)."""

    data: Application1003Extraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "Application1003ExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=Application1003Extraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("borrower_legal_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("borrower_count", coerce_int),
    ("social_security_number", coerce_str),
    ("social_security_number_2", coerce_str),
    ("date_of_birth", coerce_date),
    ("date_of_birth_2", coerce_date),
    ("marital_status", coerce_str),
    ("citizenship_residency_status", coerce_str),
    ("current_address", coerce_str),
    ("current_address_type", coerce_str),
    ("mailing_address", coerce_str),
    ("current_address_duration_months", coerce_int),
    ("current_housing_status", coerce_str),
    ("stated_monthly_income_total", coerce_decimal),
    ("loan_amount", coerce_decimal),
    ("loan_purpose", coerce_str),
    ("property_value_or_purchase_price", coerce_decimal),
    ("lender_loan_number", coerce_str),
    ("universal_loan_identifier", coerce_str),
    ("subject_property_address", coerce_str),
    ("number_of_units", coerce_int),
    ("property_type", coerce_str),
    ("occupancy_intent", coerce_str),
    ("estate_type", coerce_str),
    ("manufactured_home_indicator", coerce_str),
    ("mixed_use_indicator", coerce_str),
    ("declaration_borrowed_down_payment", coerce_str),
    ("declaration_primary_residence", coerce_str),
    ("declaration_other_mortgage_application", coerce_str),
    ("demographic_section_present", coerce_str),
    ("application_signed_date", coerce_date),
    ("application_taken_date", coerce_date),
    ("is_signed", coerce_str),
    ("form_version", coerce_str),
)


def _parse_application_1003_json(text: str) -> Application1003ExtractionResult | None:
    """Defensively parse a model response into a application 1003 result. Never raises."""
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
        data = Application1003Extraction.model_validate(
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
    return Application1003ExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_application_1003(
    content: bytes, media_type: str
) -> Application1003ExtractionResult:
    """Extract application 1003 values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return Application1003ExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return Application1003ExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="application_1003",
    )
    if call.text is None:
        return Application1003ExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_application_1003_json(call.text)
    if result is None:
        logger.warning("application_1003_extraction_parse_failed")  # no raw response logged
        return Application1003ExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "application_1003_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
