"""Disability Award Letter extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/disability_award_letter.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class DisabilityAwardLetterExtraction(BaseModel):
    """A disability award letter in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    awarding_agency_or_insurer: TypedField[str] = Field(default_factory=TypedField)
    beneficiary_name: TypedField[str] = Field(default_factory=TypedField)
    claim_or_account_number_masked: TypedField[str] = Field(default_factory=TypedField)
    benefit_program_or_policy: TypedField[str] = Field(default_factory=TypedField)
    award_letter_date: TypedField[date] = Field(default_factory=TypedField)
    disability_status: TypedField[str] = Field(default_factory=TypedField)
    disability_onset_or_entitlement_date: TypedField[date] = Field(default_factory=TypedField)
    gross_benefit_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payment_frequency: TypedField[str] = Field(default_factory=TypedField)
    net_benefit_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    taxable_status: TypedField[str] = Field(default_factory=TypedField)
    benefit_start_date: TypedField[date] = Field(default_factory=TypedField)
    benefit_end_or_review_date: TypedField[date] = Field(default_factory=TypedField)
    continuation_or_permanency_statement: TypedField[str] = Field(default_factory=TypedField)
    retroactive_or_lump_sum_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    appeal_or_pending_review_status: TypedField[str] = Field(default_factory=TypedField)
    agency_contact_information: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    deductions_or_offsets: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class DisabilityAwardLetterExtractionResult(BaseModel):
    """A disability award letter extraction plus its outcome (mirrors the other extractor results)."""

    data: DisabilityAwardLetterExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "DisabilityAwardLetterExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=DisabilityAwardLetterExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("awarding_agency_or_insurer", coerce_str),
    ("beneficiary_name", coerce_str),
    ("claim_or_account_number_masked", coerce_str),
    ("benefit_program_or_policy", coerce_str),
    ("award_letter_date", coerce_date),
    ("disability_status", coerce_str),
    ("disability_onset_or_entitlement_date", coerce_date),
    ("gross_benefit_amount", coerce_decimal),
    ("payment_frequency", coerce_str),
    ("net_benefit_amount", coerce_decimal),
    ("taxable_status", coerce_str),
    ("benefit_start_date", coerce_date),
    ("benefit_end_or_review_date", coerce_date),
    ("continuation_or_permanency_statement", coerce_str),
    ("retroactive_or_lump_sum_amount", coerce_decimal),
    ("appeal_or_pending_review_status", coerce_str),
    ("agency_contact_information", coerce_str),
)


_DEDUCTIONS_OR_OFFSETS_ROW: CoreSpec = (
    ("label", coerce_str),
    ("amount", coerce_decimal),
    ("source", coerce_str),
)


def _parse_deductions_or_offsets(raw: Any) -> list[dict[str, Any]]:
    """Coerce the deductions_or_offsets rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _DEDUCTIONS_OR_OFFSETS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _DEDUCTIONS_OR_OFFSETS_ROW):
            rows.append(row)
    return rows


def _parse_disability_award_letter_json(text: str) -> DisabilityAwardLetterExtractionResult | None:
    """Defensively parse a model response into a disability award letter result. Never raises."""
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
    deductions_or_offsets = _parse_deductions_or_offsets(payload.get("deductions_or_offsets"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = DisabilityAwardLetterExtraction.model_validate(
            {
                **core_payload,
                "deductions_or_offsets": deductions_or_offsets,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(deductions_or_offsets), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return DisabilityAwardLetterExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_disability_award_letter(
    content: bytes, media_type: str
) -> DisabilityAwardLetterExtractionResult:
    """Extract disability award letter values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return DisabilityAwardLetterExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return DisabilityAwardLetterExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="disability_award_letter",
    )
    if call.text is None:
        return DisabilityAwardLetterExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_disability_award_letter_json(call.text)
    if result is None:
        logger.warning("disability_award_letter_extraction_parse_failed")  # no raw response logged
        return DisabilityAwardLetterExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "disability_award_letter_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.deductions_or_offsets),
    )
    return result
