"""Proof Of Occupancy extraction — GENERATED from a schema spec by the LP-434 generator.

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
    coerce_int,
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

_PROMPT_PATH = "extraction/proof_of_occupancy.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7). Tune per the sizing
# rule; the test_extraction_budget_sizing CI guard enforces consistency.
_MAX_TOKENS = 4096


class ProofOfOccupancyExtraction(BaseModel):
    """A proof of occupancy in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    evidence_type: TypedField[str] = Field(default_factory=TypedField)
    issuer_or_provider_name: TypedField[str] = Field(default_factory=TypedField)
    occupant_name: TypedField[str] = Field(default_factory=TypedField)
    occupant_name_2: TypedField[str] = Field(default_factory=TypedField)
    occupant_count: TypedField[int] = Field(default_factory=TypedField)
    service_or_property_address: TypedField[str] = Field(default_factory=TypedField)
    mailing_address: TypedField[str] = Field(default_factory=TypedField)
    document_or_statement_date: TypedField[date] = Field(default_factory=TypedField)
    coverage_period_start: TypedField[date] = Field(default_factory=TypedField)
    coverage_period_end: TypedField[date] = Field(default_factory=TypedField)
    service_or_lease_start_date: TypedField[date] = Field(default_factory=TypedField)
    current_service_or_occupancy_status: TypedField[str] = Field(default_factory=TypedField)
    owner_renter_or_other_status: TypedField[str] = Field(default_factory=TypedField)
    household_or_residency_relationship: TypedField[str] = Field(default_factory=TypedField)
    account_or_reference_number_masked: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class ProofOfOccupancyExtractionResult(BaseModel):
    """A proof of occupancy extraction plus its outcome (mirrors the other extractor results)."""

    data: ProofOfOccupancyExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "ProofOfOccupancyExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=ProofOfOccupancyExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("evidence_type", coerce_str),
    ("issuer_or_provider_name", coerce_str),
    ("occupant_name", coerce_str),
    ("occupant_name_2", coerce_str),
    ("occupant_count", coerce_int),
    ("service_or_property_address", coerce_str),
    ("mailing_address", coerce_str),
    ("document_or_statement_date", coerce_date),
    ("coverage_period_start", coerce_date),
    ("coverage_period_end", coerce_date),
    ("service_or_lease_start_date", coerce_date),
    ("current_service_or_occupancy_status", coerce_str),
    ("owner_renter_or_other_status", coerce_str),
    ("household_or_residency_relationship", coerce_str),
    ("account_or_reference_number_masked", coerce_str),
    ("loan_number", coerce_str),
)


def _parse_proof_of_occupancy_json(text: str) -> ProofOfOccupancyExtractionResult | None:
    """Defensively parse a model response into a proof of occupancy result. Never raises."""
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
        data = ProofOfOccupancyExtraction.model_validate(
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
    return ProofOfOccupancyExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_proof_of_occupancy(
    content: bytes, media_type: str
) -> ProofOfOccupancyExtractionResult:
    """Extract proof of occupancy values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return ProofOfOccupancyExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return ProofOfOccupancyExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="proof_of_occupancy",
    )
    if call.text is None:
        return ProofOfOccupancyExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_proof_of_occupancy_json(call.text)
    if result is None:
        logger.warning("proof_of_occupancy_extraction_parse_failed")  # no raw response logged
        return ProofOfOccupancyExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "proof_of_occupancy_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
