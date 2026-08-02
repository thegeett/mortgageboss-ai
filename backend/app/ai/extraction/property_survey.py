"""Property Survey extraction — GENERATED from a schema spec by the LP-434 generator.

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
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
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

_PROMPT_PATH = "extraction/property_survey.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class PropertySurveyExtraction(BaseModel):
    """A property survey in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    survey_type: TypedField[str] = Field(default_factory=TypedField)
    survey_date: TypedField[date] = Field(default_factory=TypedField)
    fieldwork_date: TypedField[date] = Field(default_factory=TypedField)
    surveyor_name: TypedField[str] = Field(default_factory=TypedField)
    surveyor_firm: TypedField[str] = Field(default_factory=TypedField)
    surveyor_license_number: TypedField[str] = Field(default_factory=TypedField)
    surveyor_license_state: TypedField[str] = Field(default_factory=TypedField)
    client_name: TypedField[str] = Field(default_factory=TypedField)
    client_name_2: TypedField[str] = Field(default_factory=TypedField)
    client_count: TypedField[int] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    parcel_or_apn: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    record_owner: TypedField[str] = Field(default_factory=TypedField)
    project_or_job_number: TypedField[str] = Field(default_factory=TypedField)
    area_or_land_quantity: TypedField[str] = Field(default_factory=TypedField)
    flood_zone: TypedField[str] = Field(default_factory=TypedField)
    flood_map_panel: TypedField[str] = Field(default_factory=TypedField)
    surveyor_certification_text: TypedField[str] = Field(default_factory=TypedField)
    surveyor_signature_date: TypedField[date] = Field(default_factory=TypedField)
    seal_present: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PropertySurveyExtractionResult(BaseModel):
    """A property survey extraction plus its outcome (mirrors the other extractor results)."""

    data: PropertySurveyExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PropertySurveyExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PropertySurveyExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("survey_type", coerce_str),
    ("survey_date", coerce_date),
    ("fieldwork_date", coerce_date),
    ("surveyor_name", coerce_str),
    ("surveyor_firm", coerce_str),
    ("surveyor_license_number", coerce_str),
    ("surveyor_license_state", coerce_str),
    ("client_name", coerce_str),
    ("client_name_2", coerce_str),
    ("client_count", coerce_int),
    ("property_address", coerce_str),
    ("parcel_or_apn", coerce_str),
    ("legal_description", coerce_str),
    ("record_owner", coerce_str),
    ("project_or_job_number", coerce_str),
    ("area_or_land_quantity", coerce_str),
    ("flood_zone", coerce_str),
    ("flood_map_panel", coerce_str),
    ("surveyor_certification_text", coerce_str),
    ("surveyor_signature_date", coerce_date),
    ("seal_present", coerce_str),
    ("loan_number", coerce_str),
)


def _parse_property_survey_json(text: str) -> PropertySurveyExtractionResult | None:
    """Defensively parse a model response into a property survey result. Never raises."""
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
        data = PropertySurveyExtraction.model_validate(
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
    return PropertySurveyExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_property_survey(
    content: bytes, media_type: str
) -> PropertySurveyExtractionResult:
    """Extract property survey values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PropertySurveyExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PropertySurveyExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="property_survey",
    )
    if call.text is None:
        return PropertySurveyExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_property_survey_json(call.text)
    if result is None:
        logger.warning("property_survey_extraction_parse_failed")  # no raw response logged
        return PropertySurveyExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "property_survey_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
