"""Flood Certification extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/flood_certification.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7). Tune per the sizing
# rule; the test_extraction_budget_sizing CI guard enforces consistency.
_MAX_TOKENS = 4096


class FloodCertificationExtraction(BaseModel):
    """A flood certification in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    flood_zone: TypedField[str] = Field(default_factory=TypedField)
    special_flood_hazard_area_indicator: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    property_description_or_parcel: TypedField[str] = Field(default_factory=TypedField)
    federal_flood_insurance_available: TypedField[str] = Field(default_factory=TypedField)
    coastal_barrier_or_opa_indicator: TypedField[str] = Field(default_factory=TypedField)
    nfip_community_name: TypedField[str] = Field(default_factory=TypedField)
    nfip_community_number: TypedField[str] = Field(default_factory=TypedField)
    county: TypedField[str] = Field(default_factory=TypedField)
    map_panel_number: TypedField[str] = Field(default_factory=TypedField)
    map_panel_suffix: TypedField[str] = Field(default_factory=TypedField)
    map_effective_or_revised_date: TypedField[date] = Field(default_factory=TypedField)
    determination_date: TypedField[date] = Field(default_factory=TypedField)
    determination_company_name: TypedField[str] = Field(default_factory=TypedField)
    determination_identifier: TypedField[str] = Field(default_factory=TypedField)
    determination_method_or_source: TypedField[str] = Field(default_factory=TypedField)
    lender_name_and_address: TypedField[str] = Field(default_factory=TypedField)
    lender_id_or_loan_number: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    life_of_loan_tracking_indicator: TypedField[str] = Field(default_factory=TypedField)
    form_number: TypedField[str] = Field(default_factory=TypedField)
    comments_or_manual_review: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class FloodCertificationExtractionResult(BaseModel):
    """A flood certification extraction plus its outcome (mirrors the other extractor results)."""

    data: FloodCertificationExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "FloodCertificationExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=FloodCertificationExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("flood_zone", coerce_str),
    ("special_flood_hazard_area_indicator", coerce_str),
    ("property_address", coerce_str),
    ("property_description_or_parcel", coerce_str),
    ("federal_flood_insurance_available", coerce_str),
    ("coastal_barrier_or_opa_indicator", coerce_str),
    ("nfip_community_name", coerce_str),
    ("nfip_community_number", coerce_str),
    ("county", coerce_str),
    ("map_panel_number", coerce_str),
    ("map_panel_suffix", coerce_str),
    ("map_effective_or_revised_date", coerce_date),
    ("determination_date", coerce_date),
    ("determination_company_name", coerce_str),
    ("determination_identifier", coerce_str),
    ("determination_method_or_source", coerce_str),
    ("lender_name_and_address", coerce_str),
    ("lender_id_or_loan_number", coerce_str),
    ("borrower_name", coerce_str),
    ("life_of_loan_tracking_indicator", coerce_str),
    ("form_number", coerce_str),
    ("comments_or_manual_review", coerce_str),
)


def _parse_flood_certification_json(text: str) -> FloodCertificationExtractionResult | None:
    """Defensively parse a model response into a flood certification result. Never raises."""
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
        data = FloodCertificationExtraction.model_validate(
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
    return FloodCertificationExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_flood_certification(
    content: bytes, media_type: str
) -> FloodCertificationExtractionResult:
    """Extract flood certification values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return FloodCertificationExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return FloodCertificationExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="flood_certification",
    )
    if call.text is None:
        return FloodCertificationExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_flood_certification_json(call.text)
    if result is None:
        logger.warning("flood_certification_extraction_parse_failed")  # no raw response logged
        return FloodCertificationExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "flood_certification_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
