"""Seller Signature Authority extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/seller_signature_authority.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class SellerSignatureAuthorityExtraction(BaseModel):
    """A seller signature authority in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    seller_legal_name: TypedField[str] = Field(default_factory=TypedField)
    seller_entity_type: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    transaction_or_contract_reference: TypedField[str] = Field(default_factory=TypedField)
    authorized_signer_name: TypedField[str] = Field(default_factory=TypedField)
    authorized_signer_title_or_capacity: TypedField[str] = Field(default_factory=TypedField)
    authority_document_type: TypedField[str] = Field(default_factory=TypedField)
    authority_document_date: TypedField[date] = Field(default_factory=TypedField)
    authority_scope: TypedField[str] = Field(default_factory=TypedField)
    authority_effective_date: TypedField[date] = Field(default_factory=TypedField)
    authority_expiration_or_termination: TypedField[str] = Field(default_factory=TypedField)
    specific_property_or_transaction_authority: TypedField[str] = Field(default_factory=TypedField)
    entity_resolution_or_governing_document_reference: TypedField[str] = Field(
        default_factory=TypedField
    )
    trust_or_estate_reference: TypedField[str] = Field(default_factory=TypedField)
    poa_principal: TypedField[str] = Field(default_factory=TypedField)
    poa_agent: TypedField[str] = Field(default_factory=TypedField)
    recording_reference: TypedField[str] = Field(default_factory=TypedField)
    revocation_or_superseding_document_indicator: TypedField[str] = Field(
        default_factory=TypedField
    )
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class SellerSignatureAuthorityExtractionResult(BaseModel):
    """A seller signature authority extraction plus its outcome (mirrors the other extractor results)."""

    data: SellerSignatureAuthorityExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "SellerSignatureAuthorityExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=SellerSignatureAuthorityExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("seller_legal_name", coerce_str),
    ("seller_entity_type", coerce_str),
    ("property_address", coerce_str),
    ("transaction_or_contract_reference", coerce_str),
    ("authorized_signer_name", coerce_str),
    ("authorized_signer_title_or_capacity", coerce_str),
    ("authority_document_type", coerce_str),
    ("authority_document_date", coerce_date),
    ("authority_scope", coerce_str),
    ("authority_effective_date", coerce_date),
    ("authority_expiration_or_termination", coerce_str),
    ("specific_property_or_transaction_authority", coerce_str),
    ("entity_resolution_or_governing_document_reference", coerce_str),
    ("trust_or_estate_reference", coerce_str),
    ("poa_principal", coerce_str),
    ("poa_agent", coerce_str),
    ("recording_reference", coerce_str),
    ("revocation_or_superseding_document_indicator", coerce_str),
    ("loan_number", coerce_str),
)


def _parse_seller_signature_authority_json(
    text: str,
) -> SellerSignatureAuthorityExtractionResult | None:
    """Defensively parse a model response into a seller signature authority result. Never raises."""
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
        data = SellerSignatureAuthorityExtraction.model_validate(
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
    return SellerSignatureAuthorityExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_seller_signature_authority(
    content: bytes, media_type: str
) -> SellerSignatureAuthorityExtractionResult:
    """Extract seller signature authority values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return SellerSignatureAuthorityExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return SellerSignatureAuthorityExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="seller_signature_authority",
    )
    if call.text is None:
        return SellerSignatureAuthorityExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_seller_signature_authority_json(call.text)
    if result is None:
        logger.warning(
            "seller_signature_authority_extraction_parse_failed"
        )  # no raw response logged
        return SellerSignatureAuthorityExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "seller_signature_authority_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
