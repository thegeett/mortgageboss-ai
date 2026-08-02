"""Flood Insurance extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/flood_insurance.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class FloodInsuranceExtraction(BaseModel):
    """A flood insurance in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    insurance_carrier_or_nfip_wyo_company: TypedField[str] = Field(default_factory=TypedField)
    named_insureds: TypedField[str] = Field(default_factory=TypedField)
    insured_property_address: TypedField[str] = Field(default_factory=TypedField)
    policy_number: TypedField[str] = Field(default_factory=TypedField)
    policy_form_or_program: TypedField[str] = Field(default_factory=TypedField)
    effective_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_date: TypedField[date] = Field(default_factory=TypedField)
    policy_status: TypedField[str] = Field(default_factory=TypedField)
    flood_zone: TypedField[str] = Field(default_factory=TypedField)
    community_and_map_information: TypedField[str] = Field(default_factory=TypedField)
    building_coverage_limit: TypedField[Decimal] = Field(default_factory=TypedField)
    contents_coverage_limit: TypedField[Decimal] = Field(default_factory=TypedField)
    building_deductible: TypedField[Decimal] = Field(default_factory=TypedField)
    contents_deductible: TypedField[Decimal] = Field(default_factory=TypedField)
    replacement_cost_or_actual_cash_value_basis: TypedField[str] = Field(default_factory=TypedField)
    annual_premium: TypedField[Decimal] = Field(default_factory=TypedField)
    premium_paid_status: TypedField[str] = Field(default_factory=TypedField)
    waiting_period_or_effective_condition: TypedField[str] = Field(default_factory=TypedField)
    lender_loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class FloodInsuranceExtractionResult(BaseModel):
    """A flood insurance extraction plus its outcome (mirrors the other extractor results)."""

    data: FloodInsuranceExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "FloodInsuranceExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=FloodInsuranceExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("insurance_carrier_or_nfip_wyo_company", coerce_str),
    ("named_insureds", coerce_str),
    ("insured_property_address", coerce_str),
    ("policy_number", coerce_str),
    ("policy_form_or_program", coerce_str),
    ("effective_date", coerce_date),
    ("expiration_date", coerce_date),
    ("policy_status", coerce_str),
    ("flood_zone", coerce_str),
    ("community_and_map_information", coerce_str),
    ("building_coverage_limit", coerce_decimal),
    ("contents_coverage_limit", coerce_decimal),
    ("building_deductible", coerce_decimal),
    ("contents_deductible", coerce_decimal),
    ("replacement_cost_or_actual_cash_value_basis", coerce_str),
    ("annual_premium", coerce_decimal),
    ("premium_paid_status", coerce_str),
    ("waiting_period_or_effective_condition", coerce_str),
    ("lender_loan_number", coerce_str),
)


def _parse_flood_insurance_json(text: str) -> FloodInsuranceExtractionResult | None:
    """Defensively parse a model response into a flood insurance result. Never raises."""
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
        data = FloodInsuranceExtraction.model_validate(
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
    return FloodInsuranceExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_flood_insurance(
    content: bytes, media_type: str
) -> FloodInsuranceExtractionResult:
    """Extract flood insurance values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return FloodInsuranceExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return FloodInsuranceExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="flood_insurance",
    )
    if call.text is None:
        return FloodInsuranceExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_flood_insurance_json(call.text)
    if result is None:
        logger.warning("flood_insurance_extraction_parse_failed")  # no raw response logged
        return FloodInsuranceExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "flood_insurance_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
