"""Letter Of Explanation Property extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/letter_of_explanation_property.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class LetterOfExplanationPropertyExtraction(BaseModel):
    """A letter of explanation property in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    letter_date: TypedField[date] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    borrower_names_raw: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    parcel_or_apn: TypedField[str] = Field(default_factory=TypedField)
    property_issue_type: TypedField[str] = Field(default_factory=TypedField)
    ownership_or_vesting_details: TypedField[str] = Field(default_factory=TypedField)
    occupancy_or_use_details: TypedField[str] = Field(default_factory=TypedField)
    subject_property_indicator: TypedField[str] = Field(default_factory=TypedField)
    address_mismatch_orhistory: TypedField[str] = Field(default_factory=TypedField)
    reason_or_cause: TypedField[str] = Field(default_factory=TypedField)
    resolution_and_current_status: TypedField[str] = Field(default_factory=TypedField)
    rental_or_vacancy_details: TypedField[str] = Field(default_factory=TypedField)
    supporting_documents_summary: TypedField[str] = Field(default_factory=TypedField)
    borrower_certification: TypedField[str] = Field(default_factory=TypedField)
    signature_date: TypedField[date] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class LetterOfExplanationPropertyExtractionResult(BaseModel):
    """A letter of explanation property extraction plus its outcome (mirrors the other extractor results)."""

    data: LetterOfExplanationPropertyExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "LetterOfExplanationPropertyExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=LetterOfExplanationPropertyExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("letter_date", coerce_date),
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("borrower_names_raw", coerce_str),
    ("issuer_name", coerce_str),
    ("property_address", coerce_str),
    ("parcel_or_apn", coerce_str),
    ("property_issue_type", coerce_str),
    ("ownership_or_vesting_details", coerce_str),
    ("occupancy_or_use_details", coerce_str),
    ("subject_property_indicator", coerce_str),
    ("address_mismatch_orhistory", coerce_str),
    ("reason_or_cause", coerce_str),
    ("resolution_and_current_status", coerce_str),
    ("rental_or_vacancy_details", coerce_str),
    ("supporting_documents_summary", coerce_str),
    ("borrower_certification", coerce_str),
    ("signature_date", coerce_date),
    ("loan_number", coerce_str),
)


def _parse_letter_of_explanation_property_json(
    text: str,
) -> LetterOfExplanationPropertyExtractionResult | None:
    """Defensively parse a model response into a letter of explanation property result. Never raises."""
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
        data = LetterOfExplanationPropertyExtraction.model_validate(
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
    return LetterOfExplanationPropertyExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_letter_of_explanation_property(
    content: bytes, media_type: str
) -> LetterOfExplanationPropertyExtractionResult:
    """Extract letter of explanation property values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return LetterOfExplanationPropertyExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return LetterOfExplanationPropertyExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="letter_of_explanation_property",
    )
    if call.text is None:
        return LetterOfExplanationPropertyExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_letter_of_explanation_property_json(call.text)
    if result is None:
        logger.warning(
            "letter_of_explanation_property_extraction_parse_failed"
        )  # no raw response logged
        return LetterOfExplanationPropertyExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "letter_of_explanation_property_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
