"""Miscellaneous Document extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/miscellaneous_document.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class MiscellaneousDocumentExtraction(BaseModel):
    """A miscellaneous document in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    provisional_document_subtype: TypedField[str] = Field(default_factory=TypedField)
    issuer_or_creator: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    document_date: TypedField[date] = Field(default_factory=TypedField)
    document_purpose_or_category: TypedField[str] = Field(default_factory=TypedField)
    effective_or_coverage_period: TypedField[str] = Field(default_factory=TypedField)
    party_name: TypedField[str] = Field(default_factory=TypedField)
    party_name_2: TypedField[str] = Field(default_factory=TypedField)
    parties_named_raw: TypedField[str] = Field(default_factory=TypedField)
    property_orloan_reference: TypedField[str] = Field(default_factory=TypedField)
    account_case_or_reference_number: TypedField[str] = Field(default_factory=TypedField)
    status_or_outcome: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    key_value_pairs: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class MiscellaneousDocumentExtractionResult(BaseModel):
    """A miscellaneous document extraction plus its outcome (mirrors the other extractor results)."""

    data: MiscellaneousDocumentExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "MiscellaneousDocumentExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=MiscellaneousDocumentExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("provisional_document_subtype", coerce_str),
    ("issuer_or_creator", coerce_str),
    ("issuer_name", coerce_str),
    ("document_date", coerce_date),
    ("document_purpose_or_category", coerce_str),
    ("effective_or_coverage_period", coerce_str),
    ("party_name", coerce_str),
    ("party_name_2", coerce_str),
    ("parties_named_raw", coerce_str),
    ("property_orloan_reference", coerce_str),
    ("account_case_or_reference_number", coerce_str),
    ("status_or_outcome", coerce_str),
)


_KEY_VALUE_PAIRS_ROW: CoreSpec = (
    ("key", coerce_str),
    ("value", coerce_str),
)


def _parse_key_value_pairs(raw: Any) -> list[dict[str, Any]]:
    """Coerce the key_value_pairs rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _KEY_VALUE_PAIRS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _KEY_VALUE_PAIRS_ROW):
            rows.append(row)
    return rows


def _parse_miscellaneous_document_json(text: str) -> MiscellaneousDocumentExtractionResult | None:
    """Defensively parse a model response into a miscellaneous document result. Never raises."""
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
    key_value_pairs = _parse_key_value_pairs(payload.get("key_value_pairs"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = MiscellaneousDocumentExtraction.model_validate(
            {**core_payload, "key_value_pairs": key_value_pairs, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(key_value_pairs), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return MiscellaneousDocumentExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_miscellaneous_document(
    content: bytes, media_type: str
) -> MiscellaneousDocumentExtractionResult:
    """Extract miscellaneous document values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return MiscellaneousDocumentExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return MiscellaneousDocumentExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="miscellaneous_document",
    )
    if call.text is None:
        return MiscellaneousDocumentExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_miscellaneous_document_json(call.text)
    if result is None:
        logger.warning("miscellaneous_document_extraction_parse_failed")  # no raw response logged
        return MiscellaneousDocumentExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "miscellaneous_document_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.key_value_pairs),
    )
    return result
