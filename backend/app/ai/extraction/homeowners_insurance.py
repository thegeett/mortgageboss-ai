"""Homeowner's insurance extraction (LP-62) — Tier 1 property, the LP-39a shape.

A homeowner's insurance binder / declarations page proves the **subject property**
is insured to the lender's requirement, and its **annual premium** is part of the
borrower's housing expense. The typed core captures the carrier, policy, property,
coverage, premium, and the policy term; endorsements/deductibles/additional
coverages land in the grouped catch-all.

Mirrors the existing extractors: typed core + ``additional_sections`` catch-all,
Opus full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging. Typed core is a **V1 starter — refine with
Priya**; accuracy is validated as real binders flow through (no samples available).
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
    coerce_int,
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

_PROMPT_PATH = "extraction/homeowners_insurance.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# LP-446 — now list-bearing (forms_and_endorsements) → the unbounded-list budget (guide §7; was 4096).
_MAX_TOKENS = 8192


class HomeownersInsuranceExtraction(BaseModel):
    """A homeowner's insurance binder in the LP-39a shape: typed core + catch-all.

    **Typed core** — carrier + policy number + the insured ``property_address`` +
    ``coverage_amount`` (dwelling coverage) + ``annual_premium`` (housing expense)
    + the policy effective/expiration dates. **Grouped catch-all** — deductibles,
    additional coverages, endorsements, mortgagee clause, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    named_insured: TypedField[str] = Field(default_factory=TypedField)  # the borrower(s) (LP-202)
    carrier_name: TypedField[str] = Field(default_factory=TypedField)
    policy_number: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    coverage_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    annual_premium: TypedField[Decimal] = Field(default_factory=TypedField)  # housing expense
    effective_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_date: TypedField[date] = Field(default_factory=TypedField)

    # --- LP-446 diff (011 spec) — the exists_today:false additions ----------- #
    named_insured_2: TypedField[str] = Field(default_factory=TypedField)
    named_insured_raw: TypedField[str] = Field(default_factory=TypedField)
    agency_producer_name: TypedField[str] = Field(default_factory=TypedField)
    policy_form: TypedField[str] = Field(default_factory=TypedField)  # e.g. "HO 00 03" (form code)
    policy_status: TypedField[str] = Field(default_factory=TypedField)
    # The DWELLING's loss-settlement basis (replacement cost vs ACV vs coinsurance) — the IH-1 signal,
    # kept DISTINCT from any personal-property endorsement in forms_and_endorsements (the anti-conflation).
    replacement_cost_or_coinsurance_basis: TypedField[str] = Field(default_factory=TypedField)
    wind_hail_hurricane_coverage: TypedField[str] = Field(default_factory=TypedField)
    wind_hail_deductible: TypedField[str] = Field(default_factory=TypedField)
    premium_paid_or_due_status: TypedField[str] = Field(default_factory=TypedField)
    mortgagee_name: TypedField[str] = Field(default_factory=TypedField)
    mortgagee_clause_raw: TypedField[str] = Field(default_factory=TypedField)
    mortgagee_count: TypedField[int] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Captured nested list (LP-446 / LP-437) — bare rows, snapshot-read generically ------- #
    forms_and_endorsements: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class HomeownersInsuranceExtractionResult(BaseModel):
    """A homeowner's-insurance extraction plus its outcome (mirrors the other results)."""

    data: HomeownersInsuranceExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "HomeownersInsuranceExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=HomeownersInsuranceExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("named_insured", coerce_str),
    ("carrier_name", coerce_str),
    ("policy_number", coerce_str),
    ("property_address", coerce_str),
    ("coverage_amount", coerce_decimal),
    ("annual_premium", coerce_decimal),
    ("effective_date", coerce_date),
    ("expiration_date", coerce_date),
    # LP-446 diff additions
    ("named_insured_2", coerce_str),
    ("named_insured_raw", coerce_str),
    ("agency_producer_name", coerce_str),
    ("policy_form", coerce_str),
    ("policy_status", coerce_str),
    ("replacement_cost_or_coinsurance_basis", coerce_str),
    ("wind_hail_hurricane_coverage", coerce_str),
    ("wind_hail_deductible", coerce_str),
    ("premium_paid_or_due_status", coerce_str),
    ("mortgagee_name", coerce_str),
    ("mortgagee_clause_raw", coerce_str),
    ("mortgagee_count", coerce_int),
    ("document_issue_date", coerce_date),
)

# LP-446 — the forms_and_endorsements list: bare rows (mirrors bank_statement's transactions parse).
_FORMS_AND_ENDORSEMENTS_ROW: CoreSpec = (
    ("code_or_label", coerce_str),
    ("description", coerce_str),
)


def _parse_forms_and_endorsements(raw: Any) -> list[dict[str, Any]]:
    """Coerce the forms_and_endorsements rows — bare scalars + a per-row page/snippet source (LP-446).

    Each declared field is coerced, a per-row source kept, and a fully-empty row dropped (no hallucinated
    rows). A PERSONAL-PROPERTY replacement-cost endorsement lands HERE as a row — never conflated with the
    dwelling's ``replacement_cost_or_coinsurance_basis`` typed field."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _FORMS_AND_ENDORSEMENTS_ROW
        }
        row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _FORMS_AND_ENDORSEMENTS_ROW):
            rows.append(row)
    return rows


def _parse_homeowners_insurance_json(text: str) -> HomeownersInsuranceExtractionResult | None:
    """Defensively parse a model response into an insurance result. Never raises."""
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
    forms_and_endorsements = _parse_forms_and_endorsements(payload.get("forms_and_endorsements"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = HomeownersInsuranceExtraction.model_validate(
            {
                **core_payload,
                "forms_and_endorsements": forms_and_endorsements,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(forms_and_endorsements), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return HomeownersInsuranceExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_homeowners_insurance(
    content: bytes, media_type: str
) -> HomeownersInsuranceExtractionResult:
    """Extract homeowner's-insurance values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return HomeownersInsuranceExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return HomeownersInsuranceExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="homeowners_insurance",
    )
    if call.text is None:
        return HomeownersInsuranceExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_homeowners_insurance_json(call.text)
    if result is None:
        logger.warning("homeowners_insurance_extraction_parse_failed")  # no raw response logged
        return HomeownersInsuranceExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "homeowners_insurance_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        forms_and_endorsements=len(result.data.forms_and_endorsements),
    )
    return result
