"""Bank Deposit Slip extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/bank_deposit_slip.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class BankDepositSlipExtraction(BaseModel):
    """A bank deposit slip in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    financial_institution_name: TypedField[str] = Field(default_factory=TypedField)
    branch_identifier: TypedField[str] = Field(default_factory=TypedField)
    account_holder_name: TypedField[str] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)
    account_type: TypedField[str] = Field(default_factory=TypedField)
    deposit_date: TypedField[date] = Field(default_factory=TypedField)
    deposit_channel: TypedField[str] = Field(default_factory=TypedField)
    transaction_or_teller_number: TypedField[str] = Field(default_factory=TypedField)
    deposit_total: TypedField[Decimal] = Field(default_factory=TypedField)
    cash_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    checks_total: TypedField[Decimal] = Field(default_factory=TypedField)
    less_cash_received: TypedField[Decimal] = Field(default_factory=TypedField)
    currency: TypedField[str] = Field(default_factory=TypedField)
    funds_availability_date: TypedField[date] = Field(default_factory=TypedField)
    teller_validation_or_stamp: TypedField[str] = Field(default_factory=TypedField)
    deposit_time: TypedField[str] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BankDepositSlipExtractionResult(BaseModel):
    """A bank deposit slip extraction plus its outcome (mirrors the other extractor results)."""

    data: BankDepositSlipExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BankDepositSlipExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BankDepositSlipExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("financial_institution_name", coerce_str),
    ("branch_identifier", coerce_str),
    ("account_holder_name", coerce_str),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("deposit_date", coerce_date),
    ("deposit_channel", coerce_str),
    ("transaction_or_teller_number", coerce_str),
    ("deposit_total", coerce_decimal),
    ("cash_amount", coerce_decimal),
    ("checks_total", coerce_decimal),
    ("less_cash_received", coerce_decimal),
    ("currency", coerce_str),
    ("funds_availability_date", coerce_date),
    ("teller_validation_or_stamp", coerce_str),
    ("deposit_time", coerce_str),
    ("document_issue_date", coerce_date),
    ("loan_number", coerce_str),
)


def _parse_bank_deposit_slip_json(text: str) -> BankDepositSlipExtractionResult | None:
    """Defensively parse a model response into a bank deposit slip result. Never raises."""
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
        data = BankDepositSlipExtraction.model_validate(
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
    return BankDepositSlipExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_bank_deposit_slip(
    content: bytes, media_type: str
) -> BankDepositSlipExtractionResult:
    """Extract bank deposit slip values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BankDepositSlipExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BankDepositSlipExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="bank_deposit_slip",
    )
    if call.text is None:
        return BankDepositSlipExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_bank_deposit_slip_json(call.text)
    if result is None:
        logger.warning("bank_deposit_slip_extraction_parse_failed")  # no raw response logged
        return BankDepositSlipExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "bank_deposit_slip_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
