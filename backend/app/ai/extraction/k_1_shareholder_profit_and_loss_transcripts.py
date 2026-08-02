"""K 1 Shareholder Profit And Loss Transcripts extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/k_1_shareholder_profit_and_loss_transcripts.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class K1ShareholderProfitAndLossTranscriptsExtraction(BaseModel):
    """A k 1 shareholder profit and loss transcripts in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    transcript_type: TypedField[str] = Field(default_factory=TypedField)
    transcript_request_or_run_date: TypedField[date] = Field(default_factory=TypedField)
    tax_year: TypedField[str] = Field(default_factory=TypedField)
    source_form: TypedField[str] = Field(default_factory=TypedField)
    entity_name: TypedField[str] = Field(default_factory=TypedField)
    entity_ein_masked: TypedField[str] = Field(default_factory=TypedField)
    shareholder_or_partner_name: TypedField[str] = Field(default_factory=TypedField)
    shareholder_or_partner_tin_masked: TypedField[str] = Field(default_factory=TypedField)
    ownership_percentage: TypedField[str] = Field(default_factory=TypedField)
    ordinary_business_income_or_loss: TypedField[Decimal] = Field(default_factory=TypedField)
    rental_real_estate_income_or_loss: TypedField[Decimal] = Field(default_factory=TypedField)
    other_rental_income_or_loss: TypedField[Decimal] = Field(default_factory=TypedField)
    guaranteed_payments_or_compensation: TypedField[Decimal] = Field(default_factory=TypedField)
    distributions_or_withdrawals: TypedField[Decimal] = Field(default_factory=TypedField)
    interest_dividends_and_gains: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class K1ShareholderProfitAndLossTranscriptsExtractionResult(BaseModel):
    """A k 1 shareholder profit and loss transcripts extraction plus its outcome (mirrors the other extractor results)."""

    data: K1ShareholderProfitAndLossTranscriptsExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "K1ShareholderProfitAndLossTranscriptsExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=K1ShareholderProfitAndLossTranscriptsExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("transcript_type", coerce_str),
    ("transcript_request_or_run_date", coerce_date),
    ("tax_year", coerce_str),
    ("source_form", coerce_str),
    ("entity_name", coerce_str),
    ("entity_ein_masked", coerce_str),
    ("shareholder_or_partner_name", coerce_str),
    ("shareholder_or_partner_tin_masked", coerce_str),
    ("ownership_percentage", coerce_str),
    ("ordinary_business_income_or_loss", coerce_decimal),
    ("rental_real_estate_income_or_loss", coerce_decimal),
    ("other_rental_income_or_loss", coerce_decimal),
    ("guaranteed_payments_or_compensation", coerce_decimal),
    ("distributions_or_withdrawals", coerce_decimal),
    ("interest_dividends_and_gains", coerce_str),
)


def _parse_k_1_shareholder_profit_and_loss_transcripts_json(
    text: str,
) -> K1ShareholderProfitAndLossTranscriptsExtractionResult | None:
    """Defensively parse a model response into a k 1 shareholder profit and loss transcripts result. Never raises."""
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
        data = K1ShareholderProfitAndLossTranscriptsExtraction.model_validate(
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
    return K1ShareholderProfitAndLossTranscriptsExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_k_1_shareholder_profit_and_loss_transcripts(
    content: bytes, media_type: str
) -> K1ShareholderProfitAndLossTranscriptsExtractionResult:
    """Extract k 1 shareholder profit and loss transcripts values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return K1ShareholderProfitAndLossTranscriptsExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return K1ShareholderProfitAndLossTranscriptsExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="k_1_shareholder_profit_and_loss_transcripts",
    )
    if call.text is None:
        return K1ShareholderProfitAndLossTranscriptsExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_k_1_shareholder_profit_and_loss_transcripts_json(call.text)
    if result is None:
        logger.warning(
            "k_1_shareholder_profit_and_loss_transcripts_extraction_parse_failed"
        )  # no raw response logged
        return K1ShareholderProfitAndLossTranscriptsExtractionResult.failed(
            "could not parse extraction"
        )

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "k_1_shareholder_profit_and_loss_transcripts_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
