"""Military Leave And Earning Statement Les extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/military_leave_and_earning_statement_les.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class MilitaryLeaveAndEarningStatementLesExtraction(BaseModel):
    """A military leave and earning statement les in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    service_member_name: TypedField[str] = Field(default_factory=TypedField)
    social_security_number_masked: TypedField[str] = Field(default_factory=TypedField)
    pay_grade: TypedField[str] = Field(default_factory=TypedField)
    branch_or_component: TypedField[str] = Field(default_factory=TypedField)
    pay_period: TypedField[str] = Field(default_factory=TypedField)
    pay_date_or_service_date: TypedField[date] = Field(default_factory=TypedField)
    years_of_service: TypedField[Decimal] = Field(default_factory=TypedField)
    ets_or_service_expiration_date: TypedField[date] = Field(default_factory=TypedField)
    duty_station: TypedField[str] = Field(default_factory=TypedField)
    bah_dependency_status: TypedField[str] = Field(default_factory=TypedField)
    gross_entitlements: TypedField[Decimal] = Field(default_factory=TypedField)
    total_deductions: TypedField[Decimal] = Field(default_factory=TypedField)
    total_allotments: TypedField[Decimal] = Field(default_factory=TypedField)
    net_pay: TypedField[Decimal] = Field(default_factory=TypedField)
    end_of_month_pay: TypedField[Decimal] = Field(default_factory=TypedField)
    federal_tax_data: TypedField[str] = Field(default_factory=TypedField)
    fica_tax_data: TypedField[str] = Field(default_factory=TypedField)
    state_tax_data: TypedField[str] = Field(default_factory=TypedField)
    leave_balance: TypedField[str] = Field(default_factory=TypedField)
    direct_deposit_account_last4: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class MilitaryLeaveAndEarningStatementLesExtractionResult(BaseModel):
    """A military leave and earning statement les extraction plus its outcome (mirrors the other extractor results)."""

    data: MilitaryLeaveAndEarningStatementLesExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "MilitaryLeaveAndEarningStatementLesExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=MilitaryLeaveAndEarningStatementLesExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("issuer_name", coerce_str),
    ("service_member_name", coerce_str),
    ("social_security_number_masked", coerce_str),
    ("pay_grade", coerce_str),
    ("branch_or_component", coerce_str),
    ("pay_period", coerce_str),
    ("pay_date_or_service_date", coerce_date),
    ("years_of_service", coerce_decimal),
    ("ets_or_service_expiration_date", coerce_date),
    ("duty_station", coerce_str),
    ("bah_dependency_status", coerce_str),
    ("gross_entitlements", coerce_decimal),
    ("total_deductions", coerce_decimal),
    ("total_allotments", coerce_decimal),
    ("net_pay", coerce_decimal),
    ("end_of_month_pay", coerce_decimal),
    ("federal_tax_data", coerce_str),
    ("fica_tax_data", coerce_str),
    ("state_tax_data", coerce_str),
    ("leave_balance", coerce_str),
    ("direct_deposit_account_last4", coerce_str),
)


def _parse_military_leave_and_earning_statement_les_json(
    text: str,
) -> MilitaryLeaveAndEarningStatementLesExtractionResult | None:
    """Defensively parse a model response into a military leave and earning statement les result. Never raises."""
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
        data = MilitaryLeaveAndEarningStatementLesExtraction.model_validate(
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
    return MilitaryLeaveAndEarningStatementLesExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_military_leave_and_earning_statement_les(
    content: bytes, media_type: str
) -> MilitaryLeaveAndEarningStatementLesExtractionResult:
    """Extract military leave and earning statement les values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return MilitaryLeaveAndEarningStatementLesExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return MilitaryLeaveAndEarningStatementLesExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="military_leave_and_earning_statement_les",
    )
    if call.text is None:
        return MilitaryLeaveAndEarningStatementLesExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_military_leave_and_earning_statement_les_json(call.text)
    if result is None:
        logger.warning(
            "military_leave_and_earning_statement_les_extraction_parse_failed"
        )  # no raw response logged
        return MilitaryLeaveAndEarningStatementLesExtractionResult.failed(
            "could not parse extraction"
        )

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "military_leave_and_earning_statement_les_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
