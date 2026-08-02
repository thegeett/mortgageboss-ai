"""Business Existence Verification Cpa Ltr Bus Lic extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/business_existence_verification_cpa_ltr_bus_lic.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class BusinessExistenceVerificationCpaLtrBusLicExtraction(BaseModel):
    """A business existence verification cpa ltr bus lic in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    business_legal_name: TypedField[str] = Field(default_factory=TypedField)
    entity_type: TypedField[str] = Field(default_factory=TypedField)
    business_address: TypedField[str] = Field(default_factory=TypedField)
    ein_or_state_entity_number_masked: TypedField[str] = Field(default_factory=TypedField)
    formation_or_incorporation_date: TypedField[date] = Field(default_factory=TypedField)
    business_start_date: TypedField[date] = Field(default_factory=TypedField)
    industry_or_business_activity: TypedField[str] = Field(default_factory=TypedField)
    active_or_good_standing_status: TypedField[str] = Field(default_factory=TypedField)
    status_as_of_date: TypedField[date] = Field(default_factory=TypedField)
    borrower_owner_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    ownership_percentage: TypedField[str] = Field(default_factory=TypedField)
    owner_title_or_role: TypedField[str] = Field(default_factory=TypedField)
    verification_document_type: TypedField[str] = Field(default_factory=TypedField)
    license_or_registration_number: TypedField[str] = Field(default_factory=TypedField)
    license_issue_date: TypedField[date] = Field(default_factory=TypedField)
    license_expiration_date: TypedField[date] = Field(default_factory=TypedField)
    verifying_authority_or_cpa: TypedField[str] = Field(default_factory=TypedField)
    verification_method: TypedField[str] = Field(default_factory=TypedField)
    verification_date: TypedField[date] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    account_case_reference_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BusinessExistenceVerificationCpaLtrBusLicExtractionResult(BaseModel):
    """A business existence verification cpa ltr bus lic extraction plus its outcome (mirrors the other extractor results)."""

    data: BusinessExistenceVerificationCpaLtrBusLicExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BusinessExistenceVerificationCpaLtrBusLicExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BusinessExistenceVerificationCpaLtrBusLicExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("business_legal_name", coerce_str),
    ("entity_type", coerce_str),
    ("business_address", coerce_str),
    ("ein_or_state_entity_number_masked", coerce_str),
    ("formation_or_incorporation_date", coerce_date),
    ("business_start_date", coerce_date),
    ("industry_or_business_activity", coerce_str),
    ("active_or_good_standing_status", coerce_str),
    ("status_as_of_date", coerce_date),
    ("borrower_owner_name", coerce_str),
    ("borrower_owner_name_2", coerce_str),
    ("ownership_percentage", coerce_str),
    ("owner_title_or_role", coerce_str),
    ("verification_document_type", coerce_str),
    ("license_or_registration_number", coerce_str),
    ("license_issue_date", coerce_date),
    ("license_expiration_date", coerce_date),
    ("verifying_authority_or_cpa", coerce_str),
    ("verification_method", coerce_str),
    ("verification_date", coerce_date),
    ("issuer_name", coerce_str),
    ("account_case_reference_number", coerce_str),
)


def _parse_business_existence_verification_cpa_ltr_bus_lic_json(
    text: str,
) -> BusinessExistenceVerificationCpaLtrBusLicExtractionResult | None:
    """Defensively parse a model response into a business existence verification cpa ltr bus lic result. Never raises."""
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
        data = BusinessExistenceVerificationCpaLtrBusLicExtraction.model_validate(
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
    return BusinessExistenceVerificationCpaLtrBusLicExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_business_existence_verification_cpa_ltr_bus_lic(
    content: bytes, media_type: str
) -> BusinessExistenceVerificationCpaLtrBusLicExtractionResult:
    """Extract business existence verification cpa ltr bus lic values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BusinessExistenceVerificationCpaLtrBusLicExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BusinessExistenceVerificationCpaLtrBusLicExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="business_existence_verification_cpa_ltr_bus_lic",
    )
    if call.text is None:
        return BusinessExistenceVerificationCpaLtrBusLicExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_business_existence_verification_cpa_ltr_bus_lic_json(call.text)
    if result is None:
        logger.warning(
            "business_existence_verification_cpa_ltr_bus_lic_extraction_parse_failed"
        )  # no raw response logged
        return BusinessExistenceVerificationCpaLtrBusLicExtractionResult.failed(
            "could not parse extraction"
        )

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "business_existence_verification_cpa_ltr_bus_lic_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
