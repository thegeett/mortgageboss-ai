"""Verbal Voe extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/verbal_voe.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7). Tune per the sizing
# rule; the test_extraction_budget_sizing CI guard enforces consistency.
_MAX_TOKENS = 4096


class VerbalVoeExtraction(BaseModel):
    """A verbal voe in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    borrower_or_employee_name: TypedField[str] = Field(default_factory=TypedField)
    employer_name: TypedField[str] = Field(default_factory=TypedField)
    employer_address: TypedField[str] = Field(default_factory=TypedField)
    employer_phone_used: TypedField[str] = Field(default_factory=TypedField)
    phone_source: TypedField[str] = Field(default_factory=TypedField)
    position_or_title: TypedField[str] = Field(default_factory=TypedField)
    employment_status: TypedField[str] = Field(default_factory=TypedField)
    employment_start_date: TypedField[date] = Field(default_factory=TypedField)
    employment_end_or_leave_status: TypedField[str] = Field(default_factory=TypedField)
    probability_of_continued_employment: TypedField[str] = Field(default_factory=TypedField)
    verifier_name: TypedField[str] = Field(default_factory=TypedField)
    verifier_title_or_department: TypedField[str] = Field(default_factory=TypedField)
    verifier_relationship_or_authority: TypedField[str] = Field(default_factory=TypedField)
    lender_representative_name: TypedField[str] = Field(default_factory=TypedField)
    call_date: TypedField[date] = Field(default_factory=TypedField)
    call_time: TypedField[str] = Field(default_factory=TypedField)
    verification_method: TypedField[str] = Field(default_factory=TypedField)
    verification_result: TypedField[str] = Field(default_factory=TypedField)
    comments_or_discrepancies: TypedField[str] = Field(default_factory=TypedField)
    self_employment_business_name: TypedField[str] = Field(default_factory=TypedField)
    third_party_business_verification_source: TypedField[str] = Field(default_factory=TypedField)
    business_active_status_and_date: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class VerbalVoeExtractionResult(BaseModel):
    """A verbal voe extraction plus its outcome (mirrors the other extractor results)."""

    data: VerbalVoeExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "VerbalVoeExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=VerbalVoeExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("borrower_or_employee_name", coerce_str),
    ("employer_name", coerce_str),
    ("employer_address", coerce_str),
    ("employer_phone_used", coerce_str),
    ("phone_source", coerce_str),
    ("position_or_title", coerce_str),
    ("employment_status", coerce_str),
    ("employment_start_date", coerce_date),
    ("employment_end_or_leave_status", coerce_str),
    ("probability_of_continued_employment", coerce_str),
    ("verifier_name", coerce_str),
    ("verifier_title_or_department", coerce_str),
    ("verifier_relationship_or_authority", coerce_str),
    ("lender_representative_name", coerce_str),
    ("call_date", coerce_date),
    ("call_time", coerce_str),
    ("verification_method", coerce_str),
    ("verification_result", coerce_str),
    ("comments_or_discrepancies", coerce_str),
    ("self_employment_business_name", coerce_str),
    ("third_party_business_verification_source", coerce_str),
    ("business_active_status_and_date", coerce_str),
)


def _parse_verbal_voe_json(text: str) -> VerbalVoeExtractionResult | None:
    """Defensively parse a model response into a verbal voe result. Never raises."""
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
        data = VerbalVoeExtraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return VerbalVoeExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_verbal_voe(content: bytes, media_type: str) -> VerbalVoeExtractionResult:
    """Extract verbal voe values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return VerbalVoeExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return VerbalVoeExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="verbal_voe",
    )
    if call.text is None:
        return VerbalVoeExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_verbal_voe_json(call.text)
    if result is None:
        logger.warning("verbal_voe_extraction_parse_failed")  # no raw response logged
        return VerbalVoeExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "verbal_voe_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
