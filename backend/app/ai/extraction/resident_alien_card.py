"""Resident Alien Card extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/resident_alien_card.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class ResidentAlienCardExtraction(BaseModel):
    """A resident alien card in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_type: TypedField[str] = Field(default_factory=TypedField)
    full_name: TypedField[str] = Field(default_factory=TypedField)
    date_of_birth: TypedField[date] = Field(default_factory=TypedField)
    uscis_number_or_a_number: TypedField[str] = Field(default_factory=TypedField)
    card_number: TypedField[str] = Field(default_factory=TypedField)
    category_code: TypedField[str] = Field(default_factory=TypedField)
    country_of_birth: TypedField[str] = Field(default_factory=TypedField)
    sex: TypedField[str] = Field(default_factory=TypedField)
    resident_since_date: TypedField[date] = Field(default_factory=TypedField)
    card_expiration_date: TypedField[date] = Field(default_factory=TypedField)
    card_issue_or_revision_date: TypedField[date] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    photo_present: TypedField[str] = Field(default_factory=TypedField)
    signature_or_signature_waived: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class ResidentAlienCardExtractionResult(BaseModel):
    """A resident alien card extraction plus its outcome (mirrors the other extractor results)."""

    data: ResidentAlienCardExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "ResidentAlienCardExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=ResidentAlienCardExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_type", coerce_str),
    ("full_name", coerce_str),
    ("date_of_birth", coerce_date),
    ("uscis_number_or_a_number", coerce_str),
    ("card_number", coerce_str),
    ("category_code", coerce_str),
    ("country_of_birth", coerce_str),
    ("sex", coerce_str),
    ("resident_since_date", coerce_date),
    ("card_expiration_date", coerce_date),
    ("card_issue_or_revision_date", coerce_date),
    ("issuer_name", coerce_str),
    ("photo_present", coerce_str),
    ("signature_or_signature_waived", coerce_str),
)


def _parse_resident_alien_card_json(text: str) -> ResidentAlienCardExtractionResult | None:
    """Defensively parse a model response into a resident alien card result. Never raises."""
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
        data = ResidentAlienCardExtraction.model_validate(
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
    return ResidentAlienCardExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_resident_alien_card(
    content: bytes, media_type: str
) -> ResidentAlienCardExtractionResult:
    """Extract resident alien card values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return ResidentAlienCardExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return ResidentAlienCardExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="resident_alien_card",
    )
    if call.text is None:
        return ResidentAlienCardExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_resident_alien_card_json(call.text)
    if result is None:
        logger.warning("resident_alien_card_extraction_parse_failed")  # no raw response logged
        return ResidentAlienCardExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "resident_alien_card_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
