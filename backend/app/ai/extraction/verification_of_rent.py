"""Verification Of Rent extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/verification_of_rent.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class VerificationOfRentExtraction(BaseModel):
    """A verification of rent in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    landlord_or_property_manager_name: TypedField[str] = Field(default_factory=TypedField)
    landlord_contact_phone: TypedField[str] = Field(default_factory=TypedField)
    landlord_relationship_to_borrower: TypedField[str] = Field(default_factory=TypedField)
    tenant_name: TypedField[str] = Field(default_factory=TypedField)
    tenant_name_2: TypedField[str] = Field(default_factory=TypedField)
    rental_property_address: TypedField[str] = Field(default_factory=TypedField)
    lease_start_date: TypedField[date] = Field(default_factory=TypedField)
    lease_end_date: TypedField[date] = Field(default_factory=TypedField)
    current_tenant_indicator: TypedField[str] = Field(default_factory=TypedField)
    monthly_rent: TypedField[Decimal] = Field(default_factory=TypedField)
    rent_due_day: TypedField[int] = Field(default_factory=TypedField)
    subsidy_or_concession: TypedField[str] = Field(default_factory=TypedField)
    late_payment_count: TypedField[int] = Field(default_factory=TypedField)
    returned_payment_count: TypedField[int] = Field(default_factory=TypedField)
    current_arrears: TypedField[Decimal] = Field(default_factory=TypedField)
    eviction_or_collection_status: TypedField[str] = Field(default_factory=TypedField)
    verifier_name_title: TypedField[str] = Field(default_factory=TypedField)
    verification_date: TypedField[date] = Field(default_factory=TypedField)
    independent_source_indicator: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    rent_payment_history: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class VerificationOfRentExtractionResult(BaseModel):
    """A verification of rent extraction plus its outcome (mirrors the other extractor results)."""

    data: VerificationOfRentExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "VerificationOfRentExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=VerificationOfRentExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("landlord_or_property_manager_name", coerce_str),
    ("landlord_contact_phone", coerce_str),
    ("landlord_relationship_to_borrower", coerce_str),
    ("tenant_name", coerce_str),
    ("tenant_name_2", coerce_str),
    ("rental_property_address", coerce_str),
    ("lease_start_date", coerce_date),
    ("lease_end_date", coerce_date),
    ("current_tenant_indicator", coerce_str),
    ("monthly_rent", coerce_decimal),
    ("rent_due_day", coerce_int),
    ("subsidy_or_concession", coerce_str),
    ("late_payment_count", coerce_int),
    ("returned_payment_count", coerce_int),
    ("current_arrears", coerce_decimal),
    ("eviction_or_collection_status", coerce_str),
    ("verifier_name_title", coerce_str),
    ("verification_date", coerce_date),
    ("independent_source_indicator", coerce_str),
)


_RENT_PAYMENT_HISTORY_ROW: CoreSpec = (
    ("month", coerce_str),
    ("amount_due", coerce_decimal),
    ("amount_paid", coerce_decimal),
    ("payment_status", coerce_str),
    ("source", coerce_str),
)


def _parse_rent_payment_history(raw: Any) -> list[dict[str, Any]]:
    """Coerce the rent_payment_history rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _RENT_PAYMENT_HISTORY_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _RENT_PAYMENT_HISTORY_ROW):
            rows.append(row)
    return rows


def _parse_verification_of_rent_json(text: str) -> VerificationOfRentExtractionResult | None:
    """Defensively parse a model response into a verification of rent result. Never raises."""
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
    rent_payment_history = _parse_rent_payment_history(payload.get("rent_payment_history"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = VerificationOfRentExtraction.model_validate(
            {
                **core_payload,
                "rent_payment_history": rent_payment_history,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(rent_payment_history), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return VerificationOfRentExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_verification_of_rent(
    content: bytes, media_type: str
) -> VerificationOfRentExtractionResult:
    """Extract verification of rent values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return VerificationOfRentExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return VerificationOfRentExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="verification_of_rent",
    )
    if call.text is None:
        return VerificationOfRentExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_verification_of_rent_json(call.text)
    if result is None:
        logger.warning("verification_of_rent_extraction_parse_failed")  # no raw response logged
        return VerificationOfRentExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "verification_of_rent_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.rent_payment_history),
    )
    return result
