"""Title Commitment extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/title_commitment.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 16384 (guide §7 sizing rule; 2 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 16384


class TitleCommitmentExtraction(BaseModel):
    """A title commitment in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    title_company_name: TypedField[str] = Field(default_factory=TypedField)
    commitment_number: TypedField[str] = Field(default_factory=TypedField)
    effective_date: TypedField[date] = Field(default_factory=TypedField)
    commitment_date: TypedField[date] = Field(default_factory=TypedField)
    policy_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    policy_type: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    legal_description_type: TypedField[str] = Field(default_factory=TypedField)
    parcel_identification_number: TypedField[str] = Field(default_factory=TypedField)
    county: TypedField[str] = Field(default_factory=TypedField)
    vested_owner_name: TypedField[str] = Field(default_factory=TypedField)
    vested_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    vesting_type: TypedField[str] = Field(default_factory=TypedField)
    vesting_marital_recital: TypedField[str] = Field(default_factory=TypedField)
    proposed_insured_name: TypedField[str] = Field(default_factory=TypedField)
    seller_of_record: TypedField[str] = Field(default_factory=TypedField)
    open_liens_indicator: TypedField[str] = Field(default_factory=TypedField)
    judgments_indicator: TypedField[str] = Field(default_factory=TypedField)
    survey_exception_indicator: TypedField[str] = Field(default_factory=TypedField)
    taxes_status: TypedField[str] = Field(default_factory=TypedField)
    annual_tax_amount: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class TitleCommitmentExtractionResult(BaseModel):
    """A title commitment extraction plus its outcome (mirrors the other extractor results)."""

    data: TitleCommitmentExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "TitleCommitmentExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=TitleCommitmentExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("title_company_name", coerce_str),
    ("commitment_number", coerce_str),
    ("effective_date", coerce_date),
    ("commitment_date", coerce_date),
    ("policy_amount", coerce_decimal),
    ("policy_type", coerce_str),
    ("property_address", coerce_str),
    ("legal_description", coerce_str),
    ("legal_description_type", coerce_str),
    ("parcel_identification_number", coerce_str),
    ("county", coerce_str),
    ("vested_owner_name", coerce_str),
    ("vested_owner_name_2", coerce_str),
    ("vesting_type", coerce_str),
    ("vesting_marital_recital", coerce_str),
    ("proposed_insured_name", coerce_str),
    ("seller_of_record", coerce_str),
    ("open_liens_indicator", coerce_str),
    ("judgments_indicator", coerce_str),
    ("survey_exception_indicator", coerce_str),
    ("taxes_status", coerce_str),
    ("annual_tax_amount", coerce_decimal),
)


def _parse_title_commitment_json(text: str) -> TitleCommitmentExtractionResult | None:
    """Defensively parse a model response into a title commitment result. Never raises."""
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
        data = TitleCommitmentExtraction.model_validate(
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
    return TitleCommitmentExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_title_commitment(
    content: bytes, media_type: str
) -> TitleCommitmentExtractionResult:
    """Extract title commitment values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return TitleCommitmentExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return TitleCommitmentExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="title_commitment",
    )
    if call.text is None:
        return TitleCommitmentExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_title_commitment_json(call.text)
    if result is None:
        logger.warning("title_commitment_extraction_parse_failed")  # no raw response logged
        return TitleCommitmentExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "title_commitment_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
