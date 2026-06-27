"""Property tax bill extraction (LP-62) — Tier 1 property, the LP-39a shape.

A property tax bill documents the **annual property tax** — part of the housing
expense / DTI (and for another property, an obligation). The typed core captures
the property, the assessed value, the annual tax, the due date(s), and the taxing
authority; installment breakdowns / exemptions / parcel details land in the
grouped catch-all. **The ``property_address`` is captured** so Phase 3 can match
subject-vs-other.

``due_dates`` is a **string** (not a single date) because a tax bill commonly has
two installment due dates — capturing them verbatim loses nothing; Phase 3 can
parse them. Mirrors the existing extractors: typed core + catch-all, honest nulls,
graceful ``.failed()``, metadata-only logging. **V1 starter — refine with Priya**;
accuracy validated as real bills flow through (no samples were available).
"""

import json
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_decimal,
    coerce_str,
    derive_status,
    parse_catch_all,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/property_tax_bill.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class PropertyTaxBillExtraction(BaseModel):
    """A property tax bill in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the ``property_address`` (captured for Phase 3 matching), the
    ``assessed_value``, the ``annual_tax_amount`` (housing expense / DTI), the
    ``due_dates`` (verbatim — often two installments), and the ``taxing_authority``.
    **Grouped catch-all** — installment breakdowns, exemptions, parcel/APN, special
    assessments, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    property_address: TypedField[str] = Field(default_factory=TypedField)  # subject-vs-other: P3
    assessed_value: TypedField[Decimal] = Field(default_factory=TypedField)
    annual_tax_amount: TypedField[Decimal] = Field(default_factory=TypedField)  # housing/DTI
    due_dates: TypedField[str] = Field(default_factory=TypedField)  # str — may be two installments
    taxing_authority: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PropertyTaxBillExtractionResult(BaseModel):
    """A property-tax-bill extraction plus its outcome (mirrors the other results)."""

    data: PropertyTaxBillExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PropertyTaxBillExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PropertyTaxBillExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("property_address", coerce_str),
    ("assessed_value", coerce_decimal),
    ("annual_tax_amount", coerce_decimal),
    ("due_dates", coerce_str),
    ("taxing_authority", coerce_str),
)


def _parse_property_tax_bill_json(text: str) -> PropertyTaxBillExtractionResult | None:
    """Defensively parse a model response into a property-tax-bill result. Never raises."""
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
        data = PropertyTaxBillExtraction.model_validate(
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
    return PropertyTaxBillExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_property_tax_bill(
    content: bytes, media_type: str
) -> PropertyTaxBillExtractionResult:
    """Extract property-tax-bill values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PropertyTaxBillExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PropertyTaxBillExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("property_tax_bill_extraction_ai_failed")  # metadata only
        return PropertyTaxBillExtractionResult.failed("AI call failed")

    result = _parse_property_tax_bill_json(resp.text)
    if result is None:
        logger.warning("property_tax_bill_extraction_parse_failed")  # no raw response logged
        return PropertyTaxBillExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "property_tax_bill_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
