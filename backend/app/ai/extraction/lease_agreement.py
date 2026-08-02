"""Lease Agreement extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/lease_agreement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class LeaseAgreementExtraction(BaseModel):
    """A lease agreement in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    landlord_or_lessor_names_raw: TypedField[str] = Field(default_factory=TypedField)
    landlord_or_lessor_name: TypedField[str] = Field(default_factory=TypedField)
    landlord_or_lessor_name_2: TypedField[str] = Field(default_factory=TypedField)
    tenant_or_lessee_names_raw: TypedField[str] = Field(default_factory=TypedField)
    tenant_or_lessee_name: TypedField[str] = Field(default_factory=TypedField)
    tenant_or_lessee_name_2: TypedField[str] = Field(default_factory=TypedField)
    rental_property_address: TypedField[str] = Field(default_factory=TypedField)
    unit_or_premises_description: TypedField[str] = Field(default_factory=TypedField)
    lease_start_date: TypedField[date] = Field(default_factory=TypedField)
    lease_end_date: TypedField[date] = Field(default_factory=TypedField)
    lease_term_type: TypedField[str] = Field(default_factory=TypedField)
    monthly_rent: TypedField[Decimal] = Field(default_factory=TypedField)
    rent_due_date_or_day: TypedField[str] = Field(default_factory=TypedField)
    security_deposit: TypedField[Decimal] = Field(default_factory=TypedField)
    renewal_and_termination_terms: TypedField[str] = Field(default_factory=TypedField)
    landlord_signature_date: TypedField[date] = Field(default_factory=TypedField)
    tenant_signature_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class LeaseAgreementExtractionResult(BaseModel):
    """A lease agreement extraction plus its outcome (mirrors the other extractor results)."""

    data: LeaseAgreementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "LeaseAgreementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=LeaseAgreementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("issuer_name", coerce_str),
    ("landlord_or_lessor_names_raw", coerce_str),
    ("landlord_or_lessor_name", coerce_str),
    ("landlord_or_lessor_name_2", coerce_str),
    ("tenant_or_lessee_names_raw", coerce_str),
    ("tenant_or_lessee_name", coerce_str),
    ("tenant_or_lessee_name_2", coerce_str),
    ("rental_property_address", coerce_str),
    ("unit_or_premises_description", coerce_str),
    ("lease_start_date", coerce_date),
    ("lease_end_date", coerce_date),
    ("lease_term_type", coerce_str),
    ("monthly_rent", coerce_decimal),
    ("rent_due_date_or_day", coerce_str),
    ("security_deposit", coerce_decimal),
    ("renewal_and_termination_terms", coerce_str),
    ("landlord_signature_date", coerce_date),
    ("tenant_signature_date", coerce_date),
)


def _parse_lease_agreement_json(text: str) -> LeaseAgreementExtractionResult | None:
    """Defensively parse a model response into a lease agreement result. Never raises."""
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
        data = LeaseAgreementExtraction.model_validate(
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
    return LeaseAgreementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_lease_agreement(
    content: bytes, media_type: str
) -> LeaseAgreementExtractionResult:
    """Extract lease agreement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return LeaseAgreementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return LeaseAgreementExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="lease_agreement",
    )
    if call.text is None:
        return LeaseAgreementExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_lease_agreement_json(call.text)
    if result is None:
        logger.warning("lease_agreement_extraction_parse_failed")  # no raw response logged
        return LeaseAgreementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "lease_agreement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
