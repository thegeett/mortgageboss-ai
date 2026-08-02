"""Bankruptcy Discharge Notice extraction — GENERATED from a schema spec by the LP-434 generator.

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
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
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

_PROMPT_PATH = "extraction/bankruptcy_discharge_notice.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class BankruptcyDischargeNoticeExtraction(BaseModel):
    """A bankruptcy discharge notice in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    debtor_name: TypedField[str] = Field(default_factory=TypedField)
    joint_debtor_name: TypedField[str] = Field(default_factory=TypedField)
    bankruptcy_chapter: TypedField[str] = Field(default_factory=TypedField)
    discharge_granted_indicator: TypedField[str] = Field(default_factory=TypedField)
    discharge_order_date: TypedField[date] = Field(default_factory=TypedField)
    discharge_effective_date: TypedField[date] = Field(default_factory=TypedField)
    case_status_after_discharge: TypedField[str] = Field(default_factory=TypedField)
    bankruptcy_court_name: TypedField[str] = Field(default_factory=TypedField)
    district_or_division: TypedField[str] = Field(default_factory=TypedField)
    case_number: TypedField[str] = Field(default_factory=TypedField)
    case_filing_date: TypedField[date] = Field(default_factory=TypedField)
    exceptions_or_nondischargeable_debts: TypedField[str] = Field(default_factory=TypedField)
    debts_subject_to_discharge_summary: TypedField[str] = Field(default_factory=TypedField)
    prior_discharge_or_revocation_reference: TypedField[str] = Field(default_factory=TypedField)
    judge_name: TypedField[str] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BankruptcyDischargeNoticeExtractionResult(BaseModel):
    """A bankruptcy discharge notice extraction plus its outcome (mirrors the other extractor results)."""

    data: BankruptcyDischargeNoticeExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BankruptcyDischargeNoticeExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BankruptcyDischargeNoticeExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("debtor_name", coerce_str),
    ("joint_debtor_name", coerce_str),
    ("bankruptcy_chapter", coerce_str),
    ("discharge_granted_indicator", coerce_str),
    ("discharge_order_date", coerce_date),
    ("discharge_effective_date", coerce_date),
    ("case_status_after_discharge", coerce_str),
    ("bankruptcy_court_name", coerce_str),
    ("district_or_division", coerce_str),
    ("case_number", coerce_str),
    ("case_filing_date", coerce_date),
    ("exceptions_or_nondischargeable_debts", coerce_str),
    ("debts_subject_to_discharge_summary", coerce_str),
    ("prior_discharge_or_revocation_reference", coerce_str),
    ("judge_name", coerce_str),
    ("document_issue_date", coerce_date),
    ("loan_number", coerce_str),
    ("property_address", coerce_str),
)


def _parse_bankruptcy_discharge_notice_json(
    text: str,
) -> BankruptcyDischargeNoticeExtractionResult | None:
    """Defensively parse a model response into a bankruptcy discharge notice result. Never raises."""
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
        data = BankruptcyDischargeNoticeExtraction.model_validate(
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
    return BankruptcyDischargeNoticeExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_bankruptcy_discharge_notice(
    content: bytes, media_type: str
) -> BankruptcyDischargeNoticeExtractionResult:
    """Extract bankruptcy discharge notice values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BankruptcyDischargeNoticeExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BankruptcyDischargeNoticeExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="bankruptcy_discharge_notice",
    )
    if call.text is None:
        return BankruptcyDischargeNoticeExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_bankruptcy_discharge_notice_json(call.text)
    if result is None:
        logger.warning(
            "bankruptcy_discharge_notice_extraction_parse_failed"
        )  # no raw response logged
        return BankruptcyDischargeNoticeExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "bankruptcy_discharge_notice_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
