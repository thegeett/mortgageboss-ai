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
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    creditor_or_inquiry_company: TypedField[str] = Field(default_factory=TypedField)
    account_number_last4: TypedField[str] = Field(default_factory=TypedField)
    credit_report_bureau_or_reference: TypedField[str] = Field(default_factory=TypedField)
    new_debt_resulted_from_inquiry: TypedField[str] = Field(default_factory=TypedField)
    one_time_or_recurring_indicator: TypedField[str] = Field(default_factory=TypedField)
    resolution_or_payoff_action: TypedField[str] = Field(default_factory=TypedField)
    current_account_orissue_status: TypedField[str] = Field(default_factory=TypedField)
    supporting_documents: TypedField[str] = Field(default_factory=TypedField)
    borrower_certification: TypedField[str] = Field(default_factory=TypedField)
    borrower_signature_present: TypedField[str] = Field(default_factory=TypedField)
    borrower_signature_date: TypedField[date] = Field(default_factory=TypedField)

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
    # LP-446 diff additions
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("creditor_or_inquiry_company", coerce_str),
    ("account_number_last4", coerce_str),
    ("credit_report_bureau_or_reference", coerce_str),
    ("new_debt_resulted_from_inquiry", coerce_str),
    ("one_time_or_recurring_indicator", coerce_str),
    ("resolution_or_payoff_action", coerce_str),
    ("current_account_orissue_status", coerce_str),
    ("supporting_documents", coerce_str),
    ("borrower_certification", coerce_str),
    ("borrower_signature_present", coerce_str),
    ("borrower_signature_date", coerce_date),
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

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="letter_of_explanation",
    )
    if call.text is None:
        return LetterOfExplanationExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_loe_json(call.text)
    if result is None:
        logger.warning("loe_extraction_parse_failed")  # no raw response logged
        return LetterOfExplanationExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

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
