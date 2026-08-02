"""Child Support Income extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/child_support_income.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class ChildSupportIncomeExtraction(BaseModel):
    """A child support income in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    recipient_name: TypedField[str] = Field(default_factory=TypedField)
    payer_name: TypedField[str] = Field(default_factory=TypedField)
    court_or_agreement_type: TypedField[str] = Field(default_factory=TypedField)
    court_name: TypedField[str] = Field(default_factory=TypedField)
    case_number: TypedField[str] = Field(default_factory=TypedField)
    order_or_agreement_date: TypedField[date] = Field(default_factory=TypedField)
    modification_date: TypedField[date] = Field(default_factory=TypedField)
    support_type: TypedField[str] = Field(default_factory=TypedField)
    ordered_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payment_frequency: TypedField[str] = Field(default_factory=TypedField)
    start_date: TypedField[date] = Field(default_factory=TypedField)
    end_date_or_termination_events: TypedField[str] = Field(default_factory=TypedField)
    child_ages_or_dates_of_birth: TypedField[str] = Field(default_factory=TypedField)
    support_termination_age_or_event: TypedField[str] = Field(default_factory=TypedField)
    escalation_or_cost_of_living_terms: TypedField[str] = Field(default_factory=TypedField)
    arrears_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    current_payment_status: TypedField[str] = Field(default_factory=TypedField)
    third_party_collection_or_sdu: TypedField[str] = Field(default_factory=TypedField)
    deposit_account_last4: TypedField[str] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class ChildSupportIncomeExtractionResult(BaseModel):
    """A child support income extraction plus its outcome (mirrors the other extractor results)."""

    data: ChildSupportIncomeExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "ChildSupportIncomeExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=ChildSupportIncomeExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("issuer_name", coerce_str),
    ("recipient_name", coerce_str),
    ("payer_name", coerce_str),
    ("court_or_agreement_type", coerce_str),
    ("court_name", coerce_str),
    ("case_number", coerce_str),
    ("order_or_agreement_date", coerce_date),
    ("modification_date", coerce_date),
    ("support_type", coerce_str),
    ("ordered_amount", coerce_decimal),
    ("payment_frequency", coerce_str),
    ("start_date", coerce_date),
    ("end_date_or_termination_events", coerce_str),
    ("child_ages_or_dates_of_birth", coerce_str),
    ("support_termination_age_or_event", coerce_str),
    ("escalation_or_cost_of_living_terms", coerce_str),
    ("arrears_balance", coerce_decimal),
    ("current_payment_status", coerce_str),
    ("third_party_collection_or_sdu", coerce_str),
    ("deposit_account_last4", coerce_str),
    ("document_issue_date", coerce_date),
    ("loan_number", coerce_str),
)


def _parse_child_support_income_json(text: str) -> ChildSupportIncomeExtractionResult | None:
    """Defensively parse a model response into a child support income result. Never raises."""
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
        data = ChildSupportIncomeExtraction.model_validate(
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
    return ChildSupportIncomeExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_child_support_income(
    content: bytes, media_type: str
) -> ChildSupportIncomeExtractionResult:
    """Extract child support income values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return ChildSupportIncomeExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return ChildSupportIncomeExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="child_support_income",
    )
    if call.text is None:
        return ChildSupportIncomeExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_child_support_income_json(call.text)
    if result is None:
        logger.warning("child_support_income_extraction_parse_failed")  # no raw response logged
        return ChildSupportIncomeExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "child_support_income_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
