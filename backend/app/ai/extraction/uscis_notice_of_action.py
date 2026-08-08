"""Uscis Notice Of Action extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/uscis_notice_of_action.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class UscisNoticeOfActionExtraction(BaseModel):
    """A uscis notice of action in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    form_type: TypedField[str] = Field(default_factory=TypedField)
    notice_type: TypedField[str] = Field(default_factory=TypedField)
    receipt_number: TypedField[str] = Field(default_factory=TypedField)
    case_type: TypedField[str] = Field(default_factory=TypedField)
    received_date: TypedField[date] = Field(default_factory=TypedField)
    notice_date: TypedField[date] = Field(default_factory=TypedField)
    petitioner_name: TypedField[str] = Field(default_factory=TypedField)
    beneficiary_name: TypedField[str] = Field(default_factory=TypedField)
    beneficiary_a_number: TypedField[str] = Field(default_factory=TypedField)
    beneficiary_date_of_birth: TypedField[date] = Field(default_factory=TypedField)
    beneficiary_country_of_citizenship: TypedField[str] = Field(default_factory=TypedField)
    classification: TypedField[str] = Field(default_factory=TypedField)
    validity_from: TypedField[date] = Field(default_factory=TypedField)
    validity_to: TypedField[date] = Field(default_factory=TypedField)
    petition_valid_from: TypedField[date] = Field(default_factory=TypedField)
    petition_valid_to: TypedField[date] = Field(default_factory=TypedField)
    i94_number: TypedField[str] = Field(default_factory=TypedField)
    i94_class_of_admission: TypedField[str] = Field(default_factory=TypedField)
    priority_date: TypedField[date] = Field(default_factory=TypedField)
    service_center: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class UscisNoticeOfActionExtractionResult(BaseModel):
    """A uscis notice of action extraction plus its outcome (mirrors the other extractor results)."""

    data: UscisNoticeOfActionExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "UscisNoticeOfActionExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=UscisNoticeOfActionExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("form_type", coerce_str),
    ("notice_type", coerce_str),
    ("receipt_number", coerce_str),
    ("case_type", coerce_str),
    ("received_date", coerce_date),
    ("notice_date", coerce_date),
    ("petitioner_name", coerce_str),
    ("beneficiary_name", coerce_str),
    ("beneficiary_a_number", coerce_str),
    ("beneficiary_date_of_birth", coerce_date),
    ("beneficiary_country_of_citizenship", coerce_str),
    ("classification", coerce_str),
    ("validity_from", coerce_date),
    ("validity_to", coerce_date),
    ("petition_valid_from", coerce_date),
    ("petition_valid_to", coerce_date),
    ("i94_number", coerce_str),
    ("i94_class_of_admission", coerce_str),
    ("priority_date", coerce_date),
    ("service_center", coerce_str),
)


def _parse_uscis_notice_of_action_json(text: str) -> UscisNoticeOfActionExtractionResult | None:
    """Defensively parse a model response into a uscis notice of action result. Never raises."""
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
        data = UscisNoticeOfActionExtraction.model_validate(
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
    return UscisNoticeOfActionExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_uscis_notice_of_action(
    content: bytes, media_type: str
) -> UscisNoticeOfActionExtractionResult:
    """Extract uscis notice of action values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return UscisNoticeOfActionExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return UscisNoticeOfActionExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="uscis_notice_of_action",
    )
    if call.text is None:
        return UscisNoticeOfActionExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_uscis_notice_of_action_json(call.text)
    if result is None:
        logger.warning("uscis_notice_of_action_extraction_parse_failed")  # no raw response logged
        return UscisNoticeOfActionExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "uscis_notice_of_action_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
