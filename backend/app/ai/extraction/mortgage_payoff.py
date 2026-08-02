"""Mortgage Payoff extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/mortgage_payoff.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class MortgagePayoffExtraction(BaseModel):
    """A mortgage payoff in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    creditor_or_servicer_name: TypedField[str] = Field(default_factory=TypedField)
    servicer_phone: TypedField[str] = Field(default_factory=TypedField)
    borrower_names_raw: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    loan_number_masked: TypedField[str] = Field(default_factory=TypedField)
    account_case_reference_number: TypedField[str] = Field(default_factory=TypedField)
    payoff_quote_date: TypedField[date] = Field(default_factory=TypedField)
    payoff_good_through_date: TypedField[date] = Field(default_factory=TypedField)
    unpaid_principal_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    interest_through_good_through_date: TypedField[Decimal] = Field(default_factory=TypedField)
    per_diem_interest: TypedField[Decimal] = Field(default_factory=TypedField)
    escrow_balance_orcredit: TypedField[Decimal] = Field(default_factory=TypedField)
    prepayment_penalty: TypedField[Decimal] = Field(default_factory=TypedField)
    total_payoff_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payoff_after_good_through_formula: TypedField[str] = Field(default_factory=TypedField)
    payment_method_allowed: TypedField[str] = Field(default_factory=TypedField)
    wire_or_remittance_instructions: TypedField[str] = Field(default_factory=TypedField)
    certified_funds_requirement: TypedField[str] = Field(default_factory=TypedField)
    lien_release_timing: TypedField[str] = Field(default_factory=TypedField)
    quote_status: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class MortgagePayoffExtractionResult(BaseModel):
    """A mortgage payoff extraction plus its outcome (mirrors the other extractor results)."""

    data: MortgagePayoffExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "MortgagePayoffExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=MortgagePayoffExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("creditor_or_servicer_name", coerce_str),
    ("servicer_phone", coerce_str),
    ("borrower_names_raw", coerce_str),
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("property_address", coerce_str),
    ("loan_number_masked", coerce_str),
    ("account_case_reference_number", coerce_str),
    ("payoff_quote_date", coerce_date),
    ("payoff_good_through_date", coerce_date),
    ("unpaid_principal_balance", coerce_decimal),
    ("interest_through_good_through_date", coerce_decimal),
    ("per_diem_interest", coerce_decimal),
    ("escrow_balance_orcredit", coerce_decimal),
    ("prepayment_penalty", coerce_decimal),
    ("total_payoff_amount", coerce_decimal),
    ("payoff_after_good_through_formula", coerce_str),
    ("payment_method_allowed", coerce_str),
    ("wire_or_remittance_instructions", coerce_str),
    ("certified_funds_requirement", coerce_str),
    ("lien_release_timing", coerce_str),
    ("quote_status", coerce_str),
)


def _parse_mortgage_payoff_json(text: str) -> MortgagePayoffExtractionResult | None:
    """Defensively parse a model response into a mortgage payoff result. Never raises."""
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
        data = MortgagePayoffExtraction.model_validate(
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
    return MortgagePayoffExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_mortgage_payoff(
    content: bytes, media_type: str
) -> MortgagePayoffExtractionResult:
    """Extract mortgage payoff values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return MortgagePayoffExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return MortgagePayoffExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="mortgage_payoff",
    )
    if call.text is None:
        return MortgagePayoffExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_mortgage_payoff_json(call.text)
    if result is None:
        logger.warning("mortgage_payoff_extraction_parse_failed")  # no raw response logged
        return MortgagePayoffExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "mortgage_payoff_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
