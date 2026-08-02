"""Other Property Note extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/other_property_note.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class OtherPropertyNoteExtraction(BaseModel):
    """A other property note in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    note_date: TypedField[date] = Field(default_factory=TypedField)
    note_city_and_state: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    borrower_names_raw: TypedField[str] = Field(default_factory=TypedField)
    lender_name: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    subject_property_indicator: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)
    original_principal_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    interest_rate: TypedField[Decimal] = Field(default_factory=TypedField)
    rate_type: TypedField[str] = Field(default_factory=TypedField)
    monthly_principal_and_interest: TypedField[Decimal] = Field(default_factory=TypedField)
    payment_due_day: TypedField[int] = Field(default_factory=TypedField)
    first_payment_date: TypedField[date] = Field(default_factory=TypedField)
    maturity_date: TypedField[date] = Field(default_factory=TypedField)
    late_charge_terms: TypedField[str] = Field(default_factory=TypedField)
    prepayment_terms: TypedField[str] = Field(default_factory=TypedField)
    balloon_payment_terms: TypedField[str] = Field(default_factory=TypedField)
    margin_and_caps: TypedField[str] = Field(default_factory=TypedField)
    change_dates_and_index: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class OtherPropertyNoteExtractionResult(BaseModel):
    """A other property note extraction plus its outcome (mirrors the other extractor results)."""

    data: OtherPropertyNoteExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "OtherPropertyNoteExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=OtherPropertyNoteExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("note_date", coerce_date),
    ("note_city_and_state", coerce_str),
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("borrower_names_raw", coerce_str),
    ("lender_name", coerce_str),
    ("property_address", coerce_str),
    ("subject_property_indicator", coerce_str),
    ("loan_number", coerce_str),
    ("original_principal_amount", coerce_decimal),
    ("interest_rate", coerce_decimal),
    ("rate_type", coerce_str),
    ("monthly_principal_and_interest", coerce_decimal),
    ("payment_due_day", coerce_int),
    ("first_payment_date", coerce_date),
    ("maturity_date", coerce_date),
    ("late_charge_terms", coerce_str),
    ("prepayment_terms", coerce_str),
    ("balloon_payment_terms", coerce_str),
    ("margin_and_caps", coerce_str),
    ("change_dates_and_index", coerce_str),
)


def _parse_other_property_note_json(text: str) -> OtherPropertyNoteExtractionResult | None:
    """Defensively parse a model response into a other property note result. Never raises."""
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
        data = OtherPropertyNoteExtraction.model_validate(
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
    return OtherPropertyNoteExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_other_property_note(
    content: bytes, media_type: str
) -> OtherPropertyNoteExtractionResult:
    """Extract other property note values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return OtherPropertyNoteExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return OtherPropertyNoteExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="other_property_note",
    )
    if call.text is None:
        return OtherPropertyNoteExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_other_property_note_json(call.text)
    if result is None:
        logger.warning("other_property_note_extraction_parse_failed")  # no raw response logged
        return OtherPropertyNoteExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "other_property_note_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
