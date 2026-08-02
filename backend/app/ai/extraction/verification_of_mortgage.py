"""Verification Of Mortgage extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/verification_of_mortgage.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class VerificationOfMortgageExtraction(BaseModel):
    """A verification of mortgage in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    mortgage_holder_or_servicer: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    loan_number_masked: TypedField[str] = Field(default_factory=TypedField)
    origination_date: TypedField[date] = Field(default_factory=TypedField)
    original_loan_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    loan_type: TypedField[str] = Field(default_factory=TypedField)
    interest_rate: TypedField[str] = Field(default_factory=TypedField)
    maturity_date: TypedField[date] = Field(default_factory=TypedField)
    current_principal_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    scheduled_monthly_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    principal_and_interest_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    escrow_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    next_payment_due_date: TypedField[date] = Field(default_factory=TypedField)
    taxes_and_insurance_current: TypedField[str] = Field(default_factory=TypedField)
    late_30_count: TypedField[int] = Field(default_factory=TypedField)
    late_60_count: TypedField[int] = Field(default_factory=TypedField)
    late_90_count: TypedField[int] = Field(default_factory=TypedField)
    late_120_plus_count: TypedField[int] = Field(default_factory=TypedField)
    worst_rating: TypedField[str] = Field(default_factory=TypedField)
    current_delinquency_status: TypedField[str] = Field(default_factory=TypedField)
    past_due_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    foreclosure_or_loss_mitigation_status: TypedField[str] = Field(default_factory=TypedField)
    forbearance_or_modification_terms: TypedField[str] = Field(default_factory=TypedField)
    verifier_name_title: TypedField[str] = Field(default_factory=TypedField)
    verifier_phone_or_contact: TypedField[str] = Field(default_factory=TypedField)
    verification_date: TypedField[date] = Field(default_factory=TypedField)
    direct_source_indicator: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class VerificationOfMortgageExtractionResult(BaseModel):
    """A verification of mortgage extraction plus its outcome (mirrors the other extractor results)."""

    data: VerificationOfMortgageExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "VerificationOfMortgageExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=VerificationOfMortgageExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("property_address", coerce_str),
    ("mortgage_holder_or_servicer", coerce_str),
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("loan_number_masked", coerce_str),
    ("origination_date", coerce_date),
    ("original_loan_amount", coerce_decimal),
    ("loan_type", coerce_str),
    ("interest_rate", coerce_str),
    ("maturity_date", coerce_date),
    ("current_principal_balance", coerce_decimal),
    ("scheduled_monthly_payment", coerce_decimal),
    ("principal_and_interest_payment", coerce_decimal),
    ("escrow_payment", coerce_decimal),
    ("next_payment_due_date", coerce_date),
    ("taxes_and_insurance_current", coerce_str),
    ("late_30_count", coerce_int),
    ("late_60_count", coerce_int),
    ("late_90_count", coerce_int),
    ("late_120_plus_count", coerce_int),
    ("worst_rating", coerce_str),
    ("current_delinquency_status", coerce_str),
    ("past_due_amount", coerce_decimal),
    ("foreclosure_or_loss_mitigation_status", coerce_str),
    ("forbearance_or_modification_terms", coerce_str),
    ("verifier_name_title", coerce_str),
    ("verifier_phone_or_contact", coerce_str),
    ("verification_date", coerce_date),
    ("direct_source_indicator", coerce_str),
)


def _parse_verification_of_mortgage_json(
    text: str,
) -> VerificationOfMortgageExtractionResult | None:
    """Defensively parse a model response into a verification of mortgage result. Never raises."""
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
        data = VerificationOfMortgageExtraction.model_validate(
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
    return VerificationOfMortgageExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_verification_of_mortgage(
    content: bytes, media_type: str
) -> VerificationOfMortgageExtractionResult:
    """Extract verification of mortgage values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return VerificationOfMortgageExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return VerificationOfMortgageExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="verification_of_mortgage",
    )
    if call.text is None:
        return VerificationOfMortgageExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_verification_of_mortgage_json(call.text)
    if result is None:
        logger.warning("verification_of_mortgage_extraction_parse_failed")  # no raw response logged
        return VerificationOfMortgageExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "verification_of_mortgage_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
