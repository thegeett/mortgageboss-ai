"""Certificate Of Eligibility extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/certificate_of_eligibility.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class CertificateOfEligibilityExtraction(BaseModel):
    """A certificate of eligibility in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    regional_loan_center_or_issuer: TypedField[str] = Field(default_factory=TypedField)
    veteran_or_service_member_name: TypedField[str] = Field(default_factory=TypedField)
    social_security_number_masked: TypedField[str] = Field(default_factory=TypedField)
    va_file_or_loan_number: TypedField[str] = Field(default_factory=TypedField)
    coe_status: TypedField[str] = Field(default_factory=TypedField)
    coe_issue_date: TypedField[date] = Field(default_factory=TypedField)
    entitlement_code: TypedField[str] = Field(default_factory=TypedField)
    basic_entitlement_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    available_entitlement_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    funding_fee_exempt_indicator: TypedField[str] = Field(default_factory=TypedField)
    funding_fee_exemption_reason: TypedField[str] = Field(default_factory=TypedField)
    disability_compensation_status: TypedField[str] = Field(default_factory=TypedField)
    restoration_status: TypedField[str] = Field(default_factory=TypedField)
    minimum_service_requirement_met: TypedField[str] = Field(default_factory=TypedField)
    branch_of_service: TypedField[str] = Field(default_factory=TypedField)
    service_status: TypedField[str] = Field(default_factory=TypedField)
    surviving_spouse_indicator: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    prior_va_loan_or_entitlement_charges: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CertificateOfEligibilityExtractionResult(BaseModel):
    """A certificate of eligibility extraction plus its outcome (mirrors the other extractor results)."""

    data: CertificateOfEligibilityExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CertificateOfEligibilityExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CertificateOfEligibilityExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("regional_loan_center_or_issuer", coerce_str),
    ("veteran_or_service_member_name", coerce_str),
    ("social_security_number_masked", coerce_str),
    ("va_file_or_loan_number", coerce_str),
    ("coe_status", coerce_str),
    ("coe_issue_date", coerce_date),
    ("entitlement_code", coerce_str),
    ("basic_entitlement_amount", coerce_decimal),
    ("available_entitlement_amount", coerce_decimal),
    ("funding_fee_exempt_indicator", coerce_str),
    ("funding_fee_exemption_reason", coerce_str),
    ("disability_compensation_status", coerce_str),
    ("restoration_status", coerce_str),
    ("minimum_service_requirement_met", coerce_str),
    ("branch_of_service", coerce_str),
    ("service_status", coerce_str),
    ("surviving_spouse_indicator", coerce_str),
)


_PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_ROW: CoreSpec = (
    ("prior_loan_reference", coerce_str),
    ("entitlement_amount_charged", coerce_decimal),
    ("prior_loan_status", coerce_str),
)


def _parse_prior_va_loan_or_entitlement_charges(raw: Any) -> list[dict[str, Any]]:
    """Coerce the prior_va_loan_or_entitlement_charges rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name))
            for name, coerce in _PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _PRIOR_VA_LOAN_OR_ENTITLEMENT_CHARGES_ROW):
            rows.append(row)
    return rows


def _parse_certificate_of_eligibility_json(
    text: str,
) -> CertificateOfEligibilityExtractionResult | None:
    """Defensively parse a model response into a certificate of eligibility result. Never raises."""
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
    prior_va_loan_or_entitlement_charges = _parse_prior_va_loan_or_entitlement_charges(
        payload.get("prior_va_loan_or_entitlement_charges")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = CertificateOfEligibilityExtraction.model_validate(
            {
                **core_payload,
                "prior_va_loan_or_entitlement_charges": prior_va_loan_or_entitlement_charges,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(prior_va_loan_or_entitlement_charges), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return CertificateOfEligibilityExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_certificate_of_eligibility(
    content: bytes, media_type: str
) -> CertificateOfEligibilityExtractionResult:
    """Extract certificate of eligibility values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CertificateOfEligibilityExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CertificateOfEligibilityExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="certificate_of_eligibility",
    )
    if call.text is None:
        return CertificateOfEligibilityExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_certificate_of_eligibility_json(call.text)
    if result is None:
        logger.warning(
            "certificate_of_eligibility_extraction_parse_failed"
        )  # no raw response logged
        return CertificateOfEligibilityExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "certificate_of_eligibility_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.prior_va_loan_or_entitlement_charges),
    )
    return result
