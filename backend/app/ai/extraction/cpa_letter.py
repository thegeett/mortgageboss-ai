"""Cpa Letter extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/cpa_letter.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class CpaLetterExtraction(BaseModel):
    """A cpa letter in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    cpa_name: TypedField[str] = Field(default_factory=TypedField)
    cpa_firm_name: TypedField[str] = Field(default_factory=TypedField)
    cpa_firm_address: TypedField[str] = Field(default_factory=TypedField)
    cpa_license_number: TypedField[str] = Field(default_factory=TypedField)
    cpa_license_state: TypedField[str] = Field(default_factory=TypedField)
    license_status_or_verification: TypedField[str] = Field(default_factory=TypedField)
    client_or_borrower_names: TypedField[str] = Field(default_factory=TypedField)
    business_legal_name: TypedField[str] = Field(default_factory=TypedField)
    entity_type: TypedField[str] = Field(default_factory=TypedField)
    borrower_ownership_percentage: TypedField[str] = Field(default_factory=TypedField)
    business_start_date_or_operating_duration: TypedField[str] = Field(default_factory=TypedField)
    business_address_and_activity: TypedField[str] = Field(default_factory=TypedField)
    cpa_client_relationship_start_date: TypedField[date] = Field(default_factory=TypedField)
    business_existence_assertion: TypedField[str] = Field(default_factory=TypedField)
    self_employment_status_assertion: TypedField[str] = Field(default_factory=TypedField)
    income_or_compensation_facts: TypedField[str] = Field(default_factory=TypedField)
    business_liquidity_or_withdrawal_impact_statement: TypedField[str] = Field(
        default_factory=TypedField
    )
    scope_limitations_and_disclaimers: TypedField[str] = Field(default_factory=TypedField)
    letter_date: TypedField[date] = Field(default_factory=TypedField)
    cpa_signature: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CpaLetterExtractionResult(BaseModel):
    """A cpa letter extraction plus its outcome (mirrors the other extractor results)."""

    data: CpaLetterExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CpaLetterExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CpaLetterExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("cpa_name", coerce_str),
    ("cpa_firm_name", coerce_str),
    ("cpa_firm_address", coerce_str),
    ("cpa_license_number", coerce_str),
    ("cpa_license_state", coerce_str),
    ("license_status_or_verification", coerce_str),
    ("client_or_borrower_names", coerce_str),
    ("business_legal_name", coerce_str),
    ("entity_type", coerce_str),
    ("borrower_ownership_percentage", coerce_str),
    ("business_start_date_or_operating_duration", coerce_str),
    ("business_address_and_activity", coerce_str),
    ("cpa_client_relationship_start_date", coerce_date),
    ("business_existence_assertion", coerce_str),
    ("self_employment_status_assertion", coerce_str),
    ("income_or_compensation_facts", coerce_str),
    ("business_liquidity_or_withdrawal_impact_statement", coerce_str),
    ("scope_limitations_and_disclaimers", coerce_str),
    ("letter_date", coerce_date),
    ("cpa_signature", coerce_str),
)


def _parse_cpa_letter_json(text: str) -> CpaLetterExtractionResult | None:
    """Defensively parse a model response into a cpa letter result. Never raises."""
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
        data = CpaLetterExtraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return CpaLetterExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_cpa_letter(content: bytes, media_type: str) -> CpaLetterExtractionResult:
    """Extract cpa letter values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CpaLetterExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CpaLetterExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="cpa_letter",
    )
    if call.text is None:
        return CpaLetterExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_cpa_letter_json(call.text)
    if result is None:
        logger.warning("cpa_letter_extraction_parse_failed")  # no raw response logged
        return CpaLetterExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "cpa_letter_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
