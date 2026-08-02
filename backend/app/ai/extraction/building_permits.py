"""Building Permits extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/building_permits.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class BuildingPermitsExtraction(BaseModel):
    """A building permits in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuing_jurisdiction_or_department: TypedField[str] = Field(default_factory=TypedField)
    permit_number: TypedField[str] = Field(default_factory=TypedField)
    parent_job_or_plan_number: TypedField[str] = Field(default_factory=TypedField)
    permit_type: TypedField[str] = Field(default_factory=TypedField)
    permit_status: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    parcel_or_tax_map_number: TypedField[str] = Field(default_factory=TypedField)
    owner_name: TypedField[str] = Field(default_factory=TypedField)
    owner_address: TypedField[str] = Field(default_factory=TypedField)
    structure_type: TypedField[str] = Field(default_factory=TypedField)
    type_of_work: TypedField[str] = Field(default_factory=TypedField)
    project_description: TypedField[str] = Field(default_factory=TypedField)
    estimated_construction_cost: TypedField[Decimal] = Field(default_factory=TypedField)
    occupancy_or_use_classification: TypedField[str] = Field(default_factory=TypedField)
    application_date: TypedField[date] = Field(default_factory=TypedField)
    issue_date: TypedField[date] = Field(default_factory=TypedField)
    final_or_close_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_date: TypedField[date] = Field(default_factory=TypedField)
    applicant_name: TypedField[str] = Field(default_factory=TypedField)
    contractor_company: TypedField[str] = Field(default_factory=TypedField)
    owner_as_contractor_indicator: TypedField[str] = Field(default_factory=TypedField)
    account_case_reference_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BuildingPermitsExtractionResult(BaseModel):
    """A building permits extraction plus its outcome (mirrors the other extractor results)."""

    data: BuildingPermitsExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BuildingPermitsExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BuildingPermitsExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuing_jurisdiction_or_department", coerce_str),
    ("permit_number", coerce_str),
    ("parent_job_or_plan_number", coerce_str),
    ("permit_type", coerce_str),
    ("permit_status", coerce_str),
    ("property_address", coerce_str),
    ("parcel_or_tax_map_number", coerce_str),
    ("owner_name", coerce_str),
    ("owner_address", coerce_str),
    ("structure_type", coerce_str),
    ("type_of_work", coerce_str),
    ("project_description", coerce_str),
    ("estimated_construction_cost", coerce_decimal),
    ("occupancy_or_use_classification", coerce_str),
    ("application_date", coerce_date),
    ("issue_date", coerce_date),
    ("final_or_close_date", coerce_date),
    ("expiration_date", coerce_date),
    ("applicant_name", coerce_str),
    ("contractor_company", coerce_str),
    ("owner_as_contractor_indicator", coerce_str),
    ("account_case_reference_number", coerce_str),
)


def _parse_building_permits_json(text: str) -> BuildingPermitsExtractionResult | None:
    """Defensively parse a model response into a building permits result. Never raises."""
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
        data = BuildingPermitsExtraction.model_validate(
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
    return BuildingPermitsExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_building_permits(
    content: bytes, media_type: str
) -> BuildingPermitsExtractionResult:
    """Extract building permits values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BuildingPermitsExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BuildingPermitsExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="building_permits",
    )
    if call.text is None:
        return BuildingPermitsExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_building_permits_json(call.text)
    if result is None:
        logger.warning("building_permits_extraction_parse_failed")  # no raw response logged
        return BuildingPermitsExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "building_permits_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
