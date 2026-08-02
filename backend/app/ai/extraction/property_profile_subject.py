"""Property Profile Subject extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/property_profile_subject.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class PropertyProfileSubjectExtraction(BaseModel):
    """A property profile subject in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    data_source: TypedField[str] = Field(default_factory=TypedField)
    report_date: TypedField[date] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    parcel_or_apn: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    owner_name: TypedField[str] = Field(default_factory=TypedField)
    owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    owner_count: TypedField[int] = Field(default_factory=TypedField)
    owner_mailing_address: TypedField[str] = Field(default_factory=TypedField)
    property_type: TypedField[str] = Field(default_factory=TypedField)
    number_of_units: TypedField[int] = Field(default_factory=TypedField)
    year_built: TypedField[int] = Field(default_factory=TypedField)
    gross_living_area: TypedField[str] = Field(default_factory=TypedField)
    occupancy_or_homestead_status: TypedField[str] = Field(default_factory=TypedField)
    total_assessed_value: TypedField[Decimal] = Field(default_factory=TypedField)
    assessment_tax_year: TypedField[int] = Field(default_factory=TypedField)
    annual_tax_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    tax_status: TypedField[str] = Field(default_factory=TypedField)
    automated_or_reported_value: TypedField[Decimal] = Field(default_factory=TypedField)
    valuation_date: TypedField[date] = Field(default_factory=TypedField)
    flood_zone: TypedField[str] = Field(default_factory=TypedField)
    subject_property_indicator: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PropertyProfileSubjectExtractionResult(BaseModel):
    """A property profile subject extraction plus its outcome (mirrors the other extractor results)."""

    data: PropertyProfileSubjectExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PropertyProfileSubjectExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PropertyProfileSubjectExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("issuer_name", coerce_str),
    ("data_source", coerce_str),
    ("report_date", coerce_date),
    ("property_address", coerce_str),
    ("parcel_or_apn", coerce_str),
    ("legal_description", coerce_str),
    ("owner_name", coerce_str),
    ("owner_name_2", coerce_str),
    ("owner_count", coerce_int),
    ("owner_mailing_address", coerce_str),
    ("property_type", coerce_str),
    ("number_of_units", coerce_int),
    ("year_built", coerce_int),
    ("gross_living_area", coerce_str),
    ("occupancy_or_homestead_status", coerce_str),
    ("total_assessed_value", coerce_decimal),
    ("assessment_tax_year", coerce_int),
    ("annual_tax_amount", coerce_decimal),
    ("tax_status", coerce_str),
    ("automated_or_reported_value", coerce_decimal),
    ("valuation_date", coerce_date),
    ("flood_zone", coerce_str),
    ("subject_property_indicator", coerce_str),
    ("loan_number", coerce_str),
)


def _parse_property_profile_subject_json(
    text: str,
) -> PropertyProfileSubjectExtractionResult | None:
    """Defensively parse a model response into a property profile subject result. Never raises."""
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
        data = PropertyProfileSubjectExtraction.model_validate(
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
    return PropertyProfileSubjectExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_property_profile_subject(
    content: bytes, media_type: str
) -> PropertyProfileSubjectExtractionResult:
    """Extract property profile subject values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PropertyProfileSubjectExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PropertyProfileSubjectExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="property_profile_subject",
    )
    if call.text is None:
        return PropertyProfileSubjectExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_property_profile_subject_json(call.text)
    if result is None:
        logger.warning("property_profile_subject_extraction_parse_failed")  # no raw response logged
        return PropertyProfileSubjectExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "property_profile_subject_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
