"""Letter of Explanation extraction (LP-60) — Tier 1, the LP-39a shape, prose-light.

A Letter of Explanation (LOE) is borrower prose addressing a question in the file
(a credit inquiry, a large deposit, an employment gap, …). It has no fixed form,
so the typed core is deliberately **light**: what is being explained
(``subject``), the explanation itself (``explanation_summary``), and — if the
letter centers on one — a single referenced employer / date / amount. ANY further
references (multiple dates/amounts/parties) go to the grouped catch-all. The point
is to capture *what is explained*, not to force prose into rigid fields.

The same document type also appears in the borrower-info context (LP-63); the
distinction is what the letter explains, not the extractor — this one is the
income/employment variant registered for Tier 1 routing.

Mirrors :mod:`app.ai.extraction.w2` for the result interface / graceful failure /
metadata-only logging. **V1 starter — refine with Priya**; accuracy is validated
as real LOEs flow through (no samples were available when this was built).
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

_PROMPT_PATH = "extraction/letter_of_explanation.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class LetterOfExplanationExtraction(BaseModel):
    """An LOE in the LP-39a shape: a light typed core + grouped catch-all.

    **Typed core** — ``subject`` (what is being explained), ``explanation_summary``
    (a faithful summary of the borrower's explanation), and a single primary
    ``referenced_employer`` / ``referenced_date`` / ``referenced_amount`` if the
    letter centers on one. **Grouped catch-all** — any additional references
    (further dates, amounts, parties) captured as a "References" section.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    subject: TypedField[str] = Field(default_factory=TypedField)  # what is being explained
    explanation_summary: TypedField[str] = Field(default_factory=TypedField)
    referenced_employer: TypedField[str] = Field(default_factory=TypedField)
    referenced_date: TypedField[date] = Field(default_factory=TypedField)
    referenced_amount: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — additional references, by section -------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class LetterOfExplanationExtractionResult(BaseModel):
    """An LOE extraction plus its outcome (mirrors ``W2ExtractionResult``)."""

    data: LetterOfExplanationExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "LetterOfExplanationExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=LetterOfExplanationExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("subject", coerce_str),
    ("explanation_summary", coerce_str),
    ("referenced_employer", coerce_str),
    ("referenced_date", coerce_date),
    ("referenced_amount", coerce_decimal),
)


def _parse_loe_json(text: str) -> LetterOfExplanationExtractionResult | None:
    """Defensively parse a model response into an LOE result. Never raises."""
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
        data = LetterOfExplanationExtraction.model_validate(
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
    return LetterOfExplanationExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_letter_of_explanation(
    content: bytes, media_type: str
) -> LetterOfExplanationExtractionResult:
    """Extract structured LOE values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`. The bytes/base64, raw
    response, and extracted values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return LetterOfExplanationExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return LetterOfExplanationExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("loe_extraction_ai_failed")  # metadata only — no bytes/content
        return LetterOfExplanationExtractionResult.failed("AI call failed")

    result = _parse_loe_json(resp.text)
    if result is None:
        logger.warning("loe_extraction_parse_failed")  # no raw response logged
        return LetterOfExplanationExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — NEVER the values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "loe_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
