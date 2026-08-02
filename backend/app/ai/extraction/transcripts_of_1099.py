"""Transcripts Of 1099 extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/transcripts_of_1099.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class TranscriptsOf1099Extraction(BaseModel):
    """A transcripts of 1099 in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    transcript_type: TypedField[str] = Field(default_factory=TypedField)
    transcript_request_or_run_date: TypedField[date] = Field(default_factory=TypedField)
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    recipient_name: TypedField[str] = Field(default_factory=TypedField)
    recipient_tin_masked: TypedField[str] = Field(default_factory=TypedField)
    address_or_customer_file_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    information_return_records: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class TranscriptsOf1099ExtractionResult(BaseModel):
    """A transcripts of 1099 extraction plus its outcome (mirrors the other extractor results)."""

    data: TranscriptsOf1099Extraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "TranscriptsOf1099ExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=TranscriptsOf1099Extraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("issuer_name", coerce_str),
    ("transcript_type", coerce_str),
    ("transcript_request_or_run_date", coerce_date),
    ("tax_year", coerce_int),
    ("recipient_name", coerce_str),
    ("recipient_tin_masked", coerce_str),
    ("address_or_customer_file_number", coerce_str),
)


_INFORMATION_RETURN_RECORDS_ROW: CoreSpec = (
    ("form_type", coerce_str),
    ("payer_name", coerce_str),
    ("payer_tin_masked", coerce_str),
    ("box_or_income_type", coerce_str),
    ("amount", coerce_decimal),
    ("account_number_masked", coerce_str),
)


def _parse_information_return_records(raw: Any) -> list[dict[str, Any]]:
    """Coerce the information_return_records rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _INFORMATION_RETURN_RECORDS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _INFORMATION_RETURN_RECORDS_ROW):
            rows.append(row)
    return rows


def _parse_transcripts_of_1099_json(text: str) -> TranscriptsOf1099ExtractionResult | None:
    """Defensively parse a model response into a transcripts of 1099 result. Never raises."""
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
    information_return_records = _parse_information_return_records(
        payload.get("information_return_records")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = TranscriptsOf1099Extraction.model_validate(
            {
                **core_payload,
                "information_return_records": information_return_records,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(information_return_records), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return TranscriptsOf1099ExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_transcripts_of_1099(
    content: bytes, media_type: str
) -> TranscriptsOf1099ExtractionResult:
    """Extract transcripts of 1099 values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return TranscriptsOf1099ExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return TranscriptsOf1099ExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="transcripts_of_1099",
    )
    if call.text is None:
        return TranscriptsOf1099ExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_transcripts_of_1099_json(call.text)
    if result is None:
        logger.warning("transcripts_of_1099_extraction_parse_failed")  # no raw response logged
        return TranscriptsOf1099ExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "transcripts_of_1099_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.information_return_records),
    )
    return result
