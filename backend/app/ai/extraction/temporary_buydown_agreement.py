"""Temporary Buydown Agreement extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/temporary_buydown_agreement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class TemporaryBuydownAgreementExtraction(BaseModel):
    """A temporary buydown agreement in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    loan_number: TypedField[str] = Field(default_factory=TypedField)
    lender_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    note_rate: TypedField[Decimal] = Field(default_factory=TypedField)
    note_monthly_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    buydown_type: TypedField[str] = Field(default_factory=TypedField)
    funding_party: TypedField[str] = Field(default_factory=TypedField)
    total_subsidy_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    subsidy_account_holder: TypedField[str] = Field(default_factory=TypedField)
    agreement_date: TypedField[date] = Field(default_factory=TypedField)
    is_signed: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    payment_schedule: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class TemporaryBuydownAgreementExtractionResult(BaseModel):
    """A temporary buydown agreement extraction plus its outcome (mirrors the other extractor results)."""

    data: TemporaryBuydownAgreementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "TemporaryBuydownAgreementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=TemporaryBuydownAgreementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("loan_number", coerce_str),
    ("lender_name", coerce_str),
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("property_address", coerce_str),
    ("note_rate", coerce_decimal),
    ("note_monthly_payment", coerce_decimal),
    ("buydown_type", coerce_str),
    ("funding_party", coerce_str),
    ("total_subsidy_amount", coerce_decimal),
    ("subsidy_account_holder", coerce_str),
    ("agreement_date", coerce_date),
    ("is_signed", coerce_str),
)


_PAYMENT_SCHEDULE_ROW: CoreSpec = (
    ("period_label", coerce_str),
    ("period_start", coerce_date),
    ("effective_rate", coerce_decimal),
    ("borrower_payment", coerce_decimal),
    ("monthly_subsidy", coerce_decimal),
    ("source", coerce_str),
)


def _parse_payment_schedule(raw: Any) -> list[dict[str, Any]]:
    """Coerce the payment_schedule rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _PAYMENT_SCHEDULE_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _PAYMENT_SCHEDULE_ROW):
            rows.append(row)
    return rows


def _parse_temporary_buydown_agreement_json(
    text: str,
) -> TemporaryBuydownAgreementExtractionResult | None:
    """Defensively parse a model response into a temporary buydown agreement result. Never raises."""
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
    payment_schedule = _parse_payment_schedule(payload.get("payment_schedule"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = TemporaryBuydownAgreementExtraction.model_validate(
            {**core_payload, "payment_schedule": payment_schedule, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(payment_schedule), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return TemporaryBuydownAgreementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_temporary_buydown_agreement(
    content: bytes, media_type: str
) -> TemporaryBuydownAgreementExtractionResult:
    """Extract temporary buydown agreement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return TemporaryBuydownAgreementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return TemporaryBuydownAgreementExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="temporary_buydown_agreement",
    )
    if call.text is None:
        return TemporaryBuydownAgreementExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_temporary_buydown_agreement_json(call.text)
    if result is None:
        logger.warning(
            "temporary_buydown_agreement_extraction_parse_failed"
        )  # no raw response logged
        return TemporaryBuydownAgreementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "temporary_buydown_agreement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.payment_schedule),
    )
    return result
