"""Retirement Check extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/retirement_check.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class RetirementCheckExtraction(BaseModel):
    """A retirement check in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    payer_or_plan_name: TypedField[str] = Field(default_factory=TypedField)
    payer_bank_name: TypedField[str] = Field(default_factory=TypedField)
    payee_or_retiree_name: TypedField[str] = Field(default_factory=TypedField)
    check_number: TypedField[str] = Field(default_factory=TypedField)
    check_date: TypedField[date] = Field(default_factory=TypedField)
    benefit_period_start: TypedField[date] = Field(default_factory=TypedField)
    benefit_period_end: TypedField[date] = Field(default_factory=TypedField)
    benefit_type: TypedField[str] = Field(default_factory=TypedField)
    plan_claim_or_account_last4: TypedField[str] = Field(default_factory=TypedField)
    gross_benefit_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    net_check_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    written_amount: TypedField[str] = Field(default_factory=TypedField)
    payment_frequency: TypedField[str] = Field(default_factory=TypedField)
    memo_or_benefit_reference: TypedField[str] = Field(default_factory=TypedField)
    front_image_present: TypedField[str] = Field(default_factory=TypedField)
    back_image_present: TypedField[str] = Field(default_factory=TypedField)
    payee_endorsement: TypedField[str] = Field(default_factory=TypedField)
    deposit_account_last4: TypedField[str] = Field(default_factory=TypedField)
    cleared_or_posted_date: TypedField[date] = Field(default_factory=TypedField)
    void_stop_orreturn_status: TypedField[str] = Field(default_factory=TypedField)
    related_award_orstatement_reference: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class RetirementCheckExtractionResult(BaseModel):
    """A retirement check extraction plus its outcome (mirrors the other extractor results)."""

    data: RetirementCheckExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "RetirementCheckExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=RetirementCheckExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("payer_or_plan_name", coerce_str),
    ("payer_bank_name", coerce_str),
    ("payee_or_retiree_name", coerce_str),
    ("check_number", coerce_str),
    ("check_date", coerce_date),
    ("benefit_period_start", coerce_date),
    ("benefit_period_end", coerce_date),
    ("benefit_type", coerce_str),
    ("plan_claim_or_account_last4", coerce_str),
    ("gross_benefit_amount", coerce_decimal),
    ("net_check_amount", coerce_decimal),
    ("written_amount", coerce_str),
    ("payment_frequency", coerce_str),
    ("memo_or_benefit_reference", coerce_str),
    ("front_image_present", coerce_str),
    ("back_image_present", coerce_str),
    ("payee_endorsement", coerce_str),
    ("deposit_account_last4", coerce_str),
    ("cleared_or_posted_date", coerce_date),
    ("void_stop_orreturn_status", coerce_str),
    ("related_award_orstatement_reference", coerce_str),
    ("loan_number", coerce_str),
)


def _parse_retirement_check_json(text: str) -> RetirementCheckExtractionResult | None:
    """Defensively parse a model response into a retirement check result. Never raises."""
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
        data = RetirementCheckExtraction.model_validate(
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
    return RetirementCheckExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_retirement_check(
    content: bytes, media_type: str
) -> RetirementCheckExtractionResult:
    """Extract retirement check values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return RetirementCheckExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return RetirementCheckExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="retirement_check",
    )
    if call.text is None:
        return RetirementCheckExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_retirement_check_json(call.text)
    if result is None:
        logger.warning("retirement_check_extraction_parse_failed")  # no raw response logged
        return RetirementCheckExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "retirement_check_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
