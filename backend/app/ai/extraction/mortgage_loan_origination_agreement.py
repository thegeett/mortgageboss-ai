"""Mortgage Loan Origination Agreement extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/mortgage_loan_origination_agreement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class MortgageLoanOriginationAgreementExtraction(BaseModel):
    """A mortgage loan origination agreement in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    agreement_date: TypedField[date] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    borrower_names_raw: TypedField[str] = Field(default_factory=TypedField)
    mortgage_broker_or_originator_name: TypedField[str] = Field(default_factory=TypedField)
    creditor_or_lender_name: TypedField[str] = Field(default_factory=TypedField)
    organization_nmls_id: TypedField[str] = Field(default_factory=TypedField)
    individual_originator_name: TypedField[str] = Field(default_factory=TypedField)
    individual_nmls_id: TypedField[str] = Field(default_factory=TypedField)
    broker_compensation_method: TypedField[str] = Field(default_factory=TypedField)
    borrower_paid_compensation: TypedField[Decimal] = Field(default_factory=TypedField)
    lender_paid_compensation: TypedField[Decimal] = Field(default_factory=TypedField)
    deposit_or_application_fee: TypedField[Decimal] = Field(default_factory=TypedField)
    lender_credits_or_rebates: TypedField[Decimal] = Field(default_factory=TypedField)
    broker_or_agent_relationship: TypedField[str] = Field(default_factory=TypedField)
    exclusivity_indicator: TypedField[str] = Field(default_factory=TypedField)
    rate_lock_responsibilities: TypedField[str] = Field(default_factory=TypedField)
    refundability_and_cancellation_terms: TypedField[str] = Field(default_factory=TypedField)
    agreement_term_or_expiration: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    origination_and_broker_fee_items: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class MortgageLoanOriginationAgreementExtractionResult(BaseModel):
    """A mortgage loan origination agreement extraction plus its outcome (mirrors the other extractor results)."""

    data: MortgageLoanOriginationAgreementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "MortgageLoanOriginationAgreementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=MortgageLoanOriginationAgreementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("agreement_date", coerce_date),
    ("issuer_name", coerce_str),
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("borrower_names_raw", coerce_str),
    ("mortgage_broker_or_originator_name", coerce_str),
    ("creditor_or_lender_name", coerce_str),
    ("organization_nmls_id", coerce_str),
    ("individual_originator_name", coerce_str),
    ("individual_nmls_id", coerce_str),
    ("broker_compensation_method", coerce_str),
    ("borrower_paid_compensation", coerce_decimal),
    ("lender_paid_compensation", coerce_decimal),
    ("deposit_or_application_fee", coerce_decimal),
    ("lender_credits_or_rebates", coerce_decimal),
    ("broker_or_agent_relationship", coerce_str),
    ("exclusivity_indicator", coerce_str),
    ("rate_lock_responsibilities", coerce_str),
    ("refundability_and_cancellation_terms", coerce_str),
    ("agreement_term_or_expiration", coerce_str),
    ("property_address", coerce_str),
    ("loan_number", coerce_str),
)


_ORIGINATION_AND_BROKER_FEE_ITEMS_ROW: CoreSpec = (
    ("fee_name", coerce_str),
    ("amount", coerce_decimal),
)


def _parse_origination_and_broker_fee_items(raw: Any) -> list[dict[str, Any]]:
    """Coerce the origination_and_broker_fee_items rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _ORIGINATION_AND_BROKER_FEE_ITEMS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _ORIGINATION_AND_BROKER_FEE_ITEMS_ROW):
            rows.append(row)
    return rows


def _parse_mortgage_loan_origination_agreement_json(
    text: str,
) -> MortgageLoanOriginationAgreementExtractionResult | None:
    """Defensively parse a model response into a mortgage loan origination agreement result. Never raises."""
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
    origination_and_broker_fee_items = _parse_origination_and_broker_fee_items(
        payload.get("origination_and_broker_fee_items")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = MortgageLoanOriginationAgreementExtraction.model_validate(
            {
                **core_payload,
                "origination_and_broker_fee_items": origination_and_broker_fee_items,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(origination_and_broker_fee_items), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return MortgageLoanOriginationAgreementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_mortgage_loan_origination_agreement(
    content: bytes, media_type: str
) -> MortgageLoanOriginationAgreementExtractionResult:
    """Extract mortgage loan origination agreement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return MortgageLoanOriginationAgreementExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return MortgageLoanOriginationAgreementExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="mortgage_loan_origination_agreement",
    )
    if call.text is None:
        return MortgageLoanOriginationAgreementExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_mortgage_loan_origination_agreement_json(call.text)
    if result is None:
        logger.warning(
            "mortgage_loan_origination_agreement_extraction_parse_failed"
        )  # no raw response logged
        return MortgageLoanOriginationAgreementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "mortgage_loan_origination_agreement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.origination_and_broker_fee_items),
    )
    return result
