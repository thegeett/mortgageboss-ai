"""VOE extraction (LP-60) — Tier 1 income/employment, following the LP-39a shape.

A Verification of Employment (VOE) is an employer-completed form confirming a
borrower's employment and income — high-value because the income is
employer-verified. The typed core captures the employment facts + the verified
income figures; everything else (prior-year earnings, breakdowns, remarks, the
verifier's signature block) lands in the grouped catch-all.

Mirrors :mod:`app.ai.extraction.w2`: typed core (each a ``TypedField`` with
source) + ``additional_sections`` catch-all, full-document Sonnet reading, the
shared tolerant parser, honest nulls, graceful ``.failed()``, and metadata-only
logging. Typed core is a **V1 starter — refine with Priya**; accuracy is validated
as real VOEs flow through (no samples were available when this was built).
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
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
from app.core.config import settings
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/voe.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class VOEExtraction(BaseModel):
    """A VOE in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the employment facts (employer/employee, title, current vs
    former, dates) + the verified income (current amount + frequency, YTD, hours,
    probability of continued employment). **Grouped catch-all** — prior-year
    earnings, overtime/bonus breakdowns, remarks, verifier block, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    employer_name: TypedField[str] = Field(default_factory=TypedField)
    employee_name: TypedField[str] = Field(default_factory=TypedField)
    position_title: TypedField[str] = Field(default_factory=TypedField)
    employment_status: TypedField[str] = Field(default_factory=TypedField)  # current / former
    start_date: TypedField[date] = Field(default_factory=TypedField)
    end_date: TypedField[date] = Field(default_factory=TypedField)  # if former
    current_income_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    income_frequency: TypedField[str] = Field(default_factory=TypedField)  # annual/monthly/hourly
    ytd_income: TypedField[Decimal] = Field(default_factory=TypedField)
    hours: TypedField[Decimal] = Field(default_factory=TypedField)  # e.g. hours/week
    probability_of_continued_employment: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else, by section -------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class VOEExtractionResult(BaseModel):
    """A VOE extraction plus its outcome (mirrors ``W2ExtractionResult``)."""

    data: VOEExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "VOEExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=VOEExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("employer_name", coerce_str),
    ("employee_name", coerce_str),
    ("position_title", coerce_str),
    ("employment_status", coerce_str),
    ("start_date", coerce_date),
    ("end_date", coerce_date),
    ("current_income_amount", coerce_decimal),
    ("income_frequency", coerce_str),
    ("ytd_income", coerce_decimal),
    ("hours", coerce_decimal),
    ("probability_of_continued_employment", coerce_str),
)


def _parse_voe_json(text: str) -> VOEExtractionResult | None:
    """Defensively parse a model response into a VOE result. Never raises."""
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
        data = VOEExtraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return VOEExtractionResult(data=data, status=status, confidence=confidence, reasoning=reasoning)


async def extract_voe(content: bytes, media_type: str) -> VOEExtractionResult:
    """Extract structured VOE values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`. The bytes/base64, raw
    response, and extracted values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return VOEExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return VOEExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("voe_extraction_ai_failed")  # metadata only — no bytes/content
        return VOEExtractionResult.failed("AI call failed")

    result = _parse_voe_json(resp.text)
    if result is None:
        logger.warning("voe_extraction_parse_failed")  # no raw response logged
        return VOEExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — NEVER the values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "voe_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
