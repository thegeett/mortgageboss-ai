"""Letter Of Explanation Asset extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/letter_of_explanation_asset.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class LetterOfExplanationAssetExtraction(BaseModel):
    """A letter of explanation asset in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_name_2: TypedField[str] = Field(default_factory=TypedField)
    borrower_count: TypedField[int] = Field(default_factory=TypedField)
    letter_date: TypedField[date] = Field(default_factory=TypedField)
    financial_institution_or_custodian: TypedField[str] = Field(default_factory=TypedField)
    account_number_last4: TypedField[str] = Field(default_factory=TypedField)
    asset_type: TypedField[str] = Field(default_factory=TypedField)
    asset_issue_type: TypedField[str] = Field(default_factory=TypedField)
    source_or_origin_of_funds: TypedField[str] = Field(default_factory=TypedField)
    source_party_name_and_relationship: TypedField[str] = Field(default_factory=TypedField)
    borrowed_funds_indicator: TypedField[str] = Field(default_factory=TypedField)
    repayment_obligation_terms: TypedField[str] = Field(default_factory=TypedField)
    current_availability_or_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    borrower_certification: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    transfer_path_or_chronology: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class LetterOfExplanationAssetExtractionResult(BaseModel):
    """A letter of explanation asset extraction plus its outcome (mirrors the other extractor results)."""

    data: LetterOfExplanationAssetExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "LetterOfExplanationAssetExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=LetterOfExplanationAssetExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("borrower_name", coerce_str),
    ("borrower_name_2", coerce_str),
    ("borrower_count", coerce_int),
    ("letter_date", coerce_date),
    ("financial_institution_or_custodian", coerce_str),
    ("account_number_last4", coerce_str),
    ("asset_type", coerce_str),
    ("asset_issue_type", coerce_str),
    ("source_or_origin_of_funds", coerce_str),
    ("source_party_name_and_relationship", coerce_str),
    ("borrowed_funds_indicator", coerce_str),
    ("repayment_obligation_terms", coerce_str),
    ("current_availability_or_balance", coerce_decimal),
    ("borrower_certification", coerce_str),
)


_TRANSFER_PATH_OR_CHRONOLOGY_ROW: CoreSpec = (
    ("date", coerce_date),
    ("from", coerce_str),
    ("to", coerce_str),
    ("amount", coerce_decimal),
)


def _parse_transfer_path_or_chronology(raw: Any) -> list[dict[str, Any]]:
    """Coerce the transfer_path_or_chronology rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _TRANSFER_PATH_OR_CHRONOLOGY_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _TRANSFER_PATH_OR_CHRONOLOGY_ROW):
            rows.append(row)
    return rows


def _parse_letter_of_explanation_asset_json(
    text: str,
) -> LetterOfExplanationAssetExtractionResult | None:
    """Defensively parse a model response into a letter of explanation asset result. Never raises."""
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
    transfer_path_or_chronology = _parse_transfer_path_or_chronology(
        payload.get("transfer_path_or_chronology")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = LetterOfExplanationAssetExtraction.model_validate(
            {
                **core_payload,
                "transfer_path_or_chronology": transfer_path_or_chronology,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(transfer_path_or_chronology), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return LetterOfExplanationAssetExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_letter_of_explanation_asset(
    content: bytes, media_type: str
) -> LetterOfExplanationAssetExtractionResult:
    """Extract letter of explanation asset values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return LetterOfExplanationAssetExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return LetterOfExplanationAssetExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="letter_of_explanation_asset",
    )
    if call.text is None:
        return LetterOfExplanationAssetExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_letter_of_explanation_asset_json(call.text)
    if result is None:
        logger.warning(
            "letter_of_explanation_asset_extraction_parse_failed"
        )  # no raw response logged
        return LetterOfExplanationAssetExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "letter_of_explanation_asset_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.transfer_path_or_chronology),
    )
    return result
