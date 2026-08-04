"""Boarder Proof Of Residency extraction — GENERATED from a schema spec by the LP-434 generator.

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
    source_payload,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/boarder_proof_of_residency.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class BoarderProofOfResidencyExtraction(BaseModel):
    """A boarder proof of residency in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    document_title: TypedField[str] = Field(default_factory=TypedField)
    boarder_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_or_host_name: TypedField[str] = Field(default_factory=TypedField)
    relationship_to_borrower: TypedField[str] = Field(default_factory=TypedField)
    residence_address: TypedField[str] = Field(default_factory=TypedField)
    unit_or_room_description: TypedField[str] = Field(default_factory=TypedField)
    evidence_type: TypedField[str] = Field(default_factory=TypedField)
    evidence_issuer_or_provider: TypedField[str] = Field(default_factory=TypedField)
    document_date: TypedField[date] = Field(default_factory=TypedField)
    coverage_or_service_period_start: TypedField[date] = Field(default_factory=TypedField)
    coverage_or_service_period_end: TypedField[date] = Field(default_factory=TypedField)
    account_or_reference_number_masked: TypedField[str] = Field(default_factory=TypedField)
    residency_start_date: TypedField[date] = Field(default_factory=TypedField)
    current_residency_indicator: TypedField[str] = Field(default_factory=TypedField)
    mailing_and_service_address: TypedField[str] = Field(default_factory=TypedField)
    occupancy_attestation: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)
    account_case_reference_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    supporting_documents: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class BoarderProofOfResidencyExtractionResult(BaseModel):
    """A boarder proof of residency extraction plus its outcome (mirrors the other extractor results)."""

    data: BoarderProofOfResidencyExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "BoarderProofOfResidencyExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=BoarderProofOfResidencyExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("document_title", coerce_str),
    ("boarder_name", coerce_str),
    ("borrower_or_host_name", coerce_str),
    ("relationship_to_borrower", coerce_str),
    ("residence_address", coerce_str),
    ("unit_or_room_description", coerce_str),
    ("evidence_type", coerce_str),
    ("evidence_issuer_or_provider", coerce_str),
    ("document_date", coerce_date),
    ("coverage_or_service_period_start", coerce_date),
    ("coverage_or_service_period_end", coerce_date),
    ("account_or_reference_number_masked", coerce_str),
    ("residency_start_date", coerce_date),
    ("current_residency_indicator", coerce_str),
    ("mailing_and_service_address", coerce_str),
    ("occupancy_attestation", coerce_str),
    ("property_address", coerce_str),
    ("loan_number", coerce_str),
    ("account_case_reference_number", coerce_str),
)


_SUPPORTING_DOCUMENTS_ROW: CoreSpec = (("document_name", coerce_str),)


def _parse_supporting_documents(raw: Any) -> list[dict[str, Any]]:
    """Coerce the supporting_documents rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _SUPPORTING_DOCUMENTS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _SUPPORTING_DOCUMENTS_ROW):
            rows.append(row)
    return rows


def _parse_boarder_proof_of_residency_json(
    text: str,
) -> BoarderProofOfResidencyExtractionResult | None:
    """Defensively parse a model response into a boarder proof of residency result. Never raises."""
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
    supporting_documents = _parse_supporting_documents(payload.get("supporting_documents"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = BoarderProofOfResidencyExtraction.model_validate(
            {
                **core_payload,
                "supporting_documents": supporting_documents,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(supporting_documents), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return BoarderProofOfResidencyExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_boarder_proof_of_residency(
    content: bytes, media_type: str
) -> BoarderProofOfResidencyExtractionResult:
    """Extract boarder proof of residency values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return BoarderProofOfResidencyExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return BoarderProofOfResidencyExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="boarder_proof_of_residency",
    )
    if call.text is None:
        return BoarderProofOfResidencyExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_boarder_proof_of_residency_json(call.text)
    if result is None:
        logger.warning(
            "boarder_proof_of_residency_extraction_parse_failed"
        )  # no raw response logged
        return BoarderProofOfResidencyExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "boarder_proof_of_residency_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.supporting_documents),
    )
    return result
