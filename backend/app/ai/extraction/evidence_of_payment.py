"""Evidence Of Payment extraction — GENERATED from a schema spec by the LP-434 generator.

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
    source_payload,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/evidence_of_payment.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class EvidenceOfPaymentExtraction(BaseModel):
    """A evidence of payment in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    payer_name: TypedField[str] = Field(default_factory=TypedField)
    payee_or_creditor_name: TypedField[str] = Field(default_factory=TypedField)
    obligation_type: TypedField[str] = Field(default_factory=TypedField)
    account_or_case_number_masked: TypedField[str] = Field(default_factory=TypedField)
    property_address_if_applicable: TypedField[str] = Field(default_factory=TypedField)
    payment_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payment_date: TypedField[date] = Field(default_factory=TypedField)
    posting_or_cleared_date: TypedField[date] = Field(default_factory=TypedField)
    payment_method: TypedField[str] = Field(default_factory=TypedField)
    check_reference_or_trace_number: TypedField[str] = Field(default_factory=TypedField)
    source_institution: TypedField[str] = Field(default_factory=TypedField)
    source_account_last4: TypedField[str] = Field(default_factory=TypedField)
    payment_description_or_memo: TypedField[str] = Field(default_factory=TypedField)
    cleared_or_completed_indicator: TypedField[str] = Field(default_factory=TypedField)
    balance_before_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    balance_after_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    paid_in_full_indicator: TypedField[str] = Field(default_factory=TypedField)
    account_status_after_payment: TypedField[str] = Field(default_factory=TypedField)
    billing_or_due_period: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    recurring_payment_history: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class EvidenceOfPaymentExtractionResult(BaseModel):
    """A evidence of payment extraction plus its outcome (mirrors the other extractor results)."""

    data: EvidenceOfPaymentExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "EvidenceOfPaymentExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=EvidenceOfPaymentExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("payer_name", coerce_str),
    ("payee_or_creditor_name", coerce_str),
    ("obligation_type", coerce_str),
    ("account_or_case_number_masked", coerce_str),
    ("property_address_if_applicable", coerce_str),
    ("payment_amount", coerce_decimal),
    ("payment_date", coerce_date),
    ("posting_or_cleared_date", coerce_date),
    ("payment_method", coerce_str),
    ("check_reference_or_trace_number", coerce_str),
    ("source_institution", coerce_str),
    ("source_account_last4", coerce_str),
    ("payment_description_or_memo", coerce_str),
    ("cleared_or_completed_indicator", coerce_str),
    ("balance_before_payment", coerce_decimal),
    ("balance_after_payment", coerce_decimal),
    ("paid_in_full_indicator", coerce_str),
    ("account_status_after_payment", coerce_str),
    ("billing_or_due_period", coerce_str),
    ("loan_number", coerce_str),
)


_RECURRING_PAYMENT_HISTORY_ROW: CoreSpec = (
    ("date", coerce_date),
    ("amount", coerce_decimal),
    ("status", coerce_str),
    ("source", coerce_str),
)


def _parse_recurring_payment_history(raw: Any) -> list[dict[str, Any]]:
    """Coerce the recurring_payment_history rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _RECURRING_PAYMENT_HISTORY_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _RECURRING_PAYMENT_HISTORY_ROW):
            rows.append(row)
    return rows


def _parse_evidence_of_payment_json(text: str) -> EvidenceOfPaymentExtractionResult | None:
    """Defensively parse a model response into a evidence of payment result. Never raises."""
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
    recurring_payment_history = _parse_recurring_payment_history(
        payload.get("recurring_payment_history")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = EvidenceOfPaymentExtraction.model_validate(
            {
                **core_payload,
                "recurring_payment_history": recurring_payment_history,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(recurring_payment_history), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return EvidenceOfPaymentExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_evidence_of_payment(
    content: bytes, media_type: str
) -> EvidenceOfPaymentExtractionResult:
    """Extract evidence of payment values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return EvidenceOfPaymentExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return EvidenceOfPaymentExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="evidence_of_payment",
    )
    if call.text is None:
        return EvidenceOfPaymentExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_evidence_of_payment_json(call.text)
    if result is None:
        logger.warning("evidence_of_payment_extraction_parse_failed")  # no raw response logged
        return EvidenceOfPaymentExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "evidence_of_payment_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.recurring_payment_history),
    )
    return result
