"""Hoa Certification extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/hoa_certification.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class HoaCertificationExtraction(BaseModel):
    """A hoa certification in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    association_or_project_name: TypedField[str] = Field(default_factory=TypedField)
    project_address: TypedField[str] = Field(default_factory=TypedField)
    unit_address_or_number: TypedField[str] = Field(default_factory=TypedField)
    association_management_company: TypedField[str] = Field(default_factory=TypedField)
    association_contact_phone: TypedField[str] = Field(default_factory=TypedField)
    project_type: TypedField[str] = Field(default_factory=TypedField)
    total_units: TypedField[int] = Field(default_factory=TypedField)
    units_sold_or_conveyed: TypedField[int] = Field(default_factory=TypedField)
    developer_control_status: TypedField[str] = Field(default_factory=TypedField)
    owner_occupied_units: TypedField[int] = Field(default_factory=TypedField)
    investor_owned_units: TypedField[int] = Field(default_factory=TypedField)
    rental_or_short_term_rental_restrictions: TypedField[str] = Field(default_factory=TypedField)
    single_entity_ownership_concentration: TypedField[str] = Field(default_factory=TypedField)
    commercial_space_percentage: TypedField[str] = Field(default_factory=TypedField)
    regular_hoa_dues: TypedField[Decimal] = Field(default_factory=TypedField)
    dues_frequency: TypedField[str] = Field(default_factory=TypedField)
    delinquent_units_percentage: TypedField[str] = Field(default_factory=TypedField)
    annual_budget: TypedField[Decimal] = Field(default_factory=TypedField)
    master_insurance_carrier: TypedField[str] = Field(default_factory=TypedField)
    master_insurance_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    completed_by_name_title: TypedField[str] = Field(default_factory=TypedField)
    completion_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class HoaCertificationExtractionResult(BaseModel):
    """A hoa certification extraction plus its outcome (mirrors the other extractor results)."""

    data: HoaCertificationExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "HoaCertificationExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=HoaCertificationExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("association_or_project_name", coerce_str),
    ("project_address", coerce_str),
    ("unit_address_or_number", coerce_str),
    ("association_management_company", coerce_str),
    ("association_contact_phone", coerce_str),
    ("project_type", coerce_str),
    ("total_units", coerce_int),
    ("units_sold_or_conveyed", coerce_int),
    ("developer_control_status", coerce_str),
    ("owner_occupied_units", coerce_int),
    ("investor_owned_units", coerce_int),
    ("rental_or_short_term_rental_restrictions", coerce_str),
    ("single_entity_ownership_concentration", coerce_str),
    ("commercial_space_percentage", coerce_str),
    ("regular_hoa_dues", coerce_decimal),
    ("dues_frequency", coerce_str),
    ("delinquent_units_percentage", coerce_str),
    ("annual_budget", coerce_decimal),
    ("master_insurance_carrier", coerce_str),
    ("master_insurance_amount", coerce_decimal),
    ("completed_by_name_title", coerce_str),
    ("completion_date", coerce_date),
)


def _parse_hoa_certification_json(text: str) -> HoaCertificationExtractionResult | None:
    """Defensively parse a model response into a hoa certification result. Never raises."""
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
        data = HoaCertificationExtraction.model_validate(
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
    return HoaCertificationExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_hoa_certification(
    content: bytes, media_type: str
) -> HoaCertificationExtractionResult:
    """Extract hoa certification values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return HoaCertificationExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return HoaCertificationExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="hoa_certification",
    )
    if call.text is None:
        return HoaCertificationExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_hoa_certification_json(call.text)
    if result is None:
        logger.warning("hoa_certification_extraction_parse_failed")  # no raw response logged
        return HoaCertificationExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "hoa_certification_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
