"""Credit Card Authorization extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/credit_card_authorization.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class CreditCardAuthorizationExtraction(BaseModel):
    """A credit card authorization in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    merchant_or_lender_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_or_customer_name: TypedField[str] = Field(default_factory=TypedField)
    cardholder_name: TypedField[str] = Field(default_factory=TypedField)
    billing_address: TypedField[str] = Field(default_factory=TypedField)
    card_brand: TypedField[str] = Field(default_factory=TypedField)
    card_number_last4_or_token: TypedField[str] = Field(default_factory=TypedField)
    expiration_month_year: TypedField[str] = Field(default_factory=TypedField)
    authorized_amount_or_maximum: TypedField[Decimal] = Field(default_factory=TypedField)
    charge_description_or_purpose: TypedField[str] = Field(default_factory=TypedField)
    one_time_or_recurring_authorization: TypedField[str] = Field(default_factory=TypedField)
    authorization_date: TypedField[date] = Field(default_factory=TypedField)
    authorization_expiration_or_cancel_terms: TypedField[str] = Field(default_factory=TypedField)
    loan_number_property_or_invoice: TypedField[str] = Field(default_factory=TypedField)
    cardholder_signature: TypedField[str] = Field(default_factory=TypedField)
    charged_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    transaction_status: TypedField[str] = Field(default_factory=TypedField)
    authorization_or_transaction_id: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CreditCardAuthorizationExtractionResult(BaseModel):
    """A credit card authorization extraction plus its outcome (mirrors the other extractor results)."""

    data: CreditCardAuthorizationExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CreditCardAuthorizationExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CreditCardAuthorizationExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("merchant_or_lender_name", coerce_str),
    ("borrower_or_customer_name", coerce_str),
    ("cardholder_name", coerce_str),
    ("billing_address", coerce_str),
    ("card_brand", coerce_str),
    ("card_number_last4_or_token", coerce_str),
    ("expiration_month_year", coerce_str),
    ("authorized_amount_or_maximum", coerce_decimal),
    ("charge_description_or_purpose", coerce_str),
    ("one_time_or_recurring_authorization", coerce_str),
    ("authorization_date", coerce_date),
    ("authorization_expiration_or_cancel_terms", coerce_str),
    ("loan_number_property_or_invoice", coerce_str),
    ("cardholder_signature", coerce_str),
    ("charged_amount", coerce_decimal),
    ("transaction_status", coerce_str),
    ("authorization_or_transaction_id", coerce_str),
)


def _parse_credit_card_authorization_json(
    text: str,
) -> CreditCardAuthorizationExtractionResult | None:
    """Defensively parse a model response into a credit card authorization result. Never raises."""
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
        data = CreditCardAuthorizationExtraction.model_validate(
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
    return CreditCardAuthorizationExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_credit_card_authorization(
    content: bytes, media_type: str
) -> CreditCardAuthorizationExtractionResult:
    """Extract credit card authorization values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CreditCardAuthorizationExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CreditCardAuthorizationExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="credit_card_authorization",
    )
    if call.text is None:
        return CreditCardAuthorizationExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_credit_card_authorization_json(call.text)
    if result is None:
        logger.warning(
            "credit_card_authorization_extraction_parse_failed"
        )  # no raw response logged
        return CreditCardAuthorizationExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "credit_card_authorization_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
