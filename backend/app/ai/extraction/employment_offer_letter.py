"""Employment Offer Letter extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/employment_offer_letter.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class EmploymentOfferLetterExtraction(BaseModel):
    """A employment offer letter in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    candidate_or_borrower_name: TypedField[str] = Field(default_factory=TypedField)
    position_title: TypedField[str] = Field(default_factory=TypedField)
    start_date: TypedField[date] = Field(default_factory=TypedField)
    employer_legal_name: TypedField[str] = Field(default_factory=TypedField)
    employer_address: TypedField[str] = Field(default_factory=TypedField)
    employer_contact: TypedField[str] = Field(default_factory=TypedField)
    base_salary_or_hourly_rate: TypedField[Decimal] = Field(default_factory=TypedField)
    pay_frequency: TypedField[str] = Field(default_factory=TypedField)
    employment_type: TypedField[str] = Field(default_factory=TypedField)
    guaranteed_hours_per_week: TypedField[Decimal] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)
    offer_expiration_date: TypedField[date] = Field(default_factory=TypedField)
    start_date_confirmed_or_employment_commenced: TypedField[str] = Field(
        default_factory=TypedField
    )
    employer_signer_name_title: TypedField[str] = Field(default_factory=TypedField)
    employer_signature_and_date: TypedField[str] = Field(default_factory=TypedField)
    candidate_acceptance_signature_and_date: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    employment_contingencies: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class EmploymentOfferLetterExtractionResult(BaseModel):
    """A employment offer letter extraction plus its outcome (mirrors the other extractor results)."""

    data: EmploymentOfferLetterExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "EmploymentOfferLetterExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=EmploymentOfferLetterExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("candidate_or_borrower_name", coerce_str),
    ("position_title", coerce_str),
    ("start_date", coerce_date),
    ("employer_legal_name", coerce_str),
    ("employer_address", coerce_str),
    ("employer_contact", coerce_str),
    ("base_salary_or_hourly_rate", coerce_decimal),
    ("pay_frequency", coerce_str),
    ("employment_type", coerce_str),
    ("guaranteed_hours_per_week", coerce_decimal),
    ("document_issue_date", coerce_date),
    ("offer_expiration_date", coerce_date),
    ("start_date_confirmed_or_employment_commenced", coerce_str),
    ("employer_signer_name_title", coerce_str),
    ("employer_signature_and_date", coerce_str),
    ("candidate_acceptance_signature_and_date", coerce_str),
)


_EMPLOYMENT_CONTINGENCIES_ROW: CoreSpec = (("contingency", coerce_str),)


def _parse_employment_contingencies(raw: Any) -> list[dict[str, Any]]:
    """Coerce the employment_contingencies rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _EMPLOYMENT_CONTINGENCIES_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _EMPLOYMENT_CONTINGENCIES_ROW):
            rows.append(row)
    return rows


def _parse_employment_offer_letter_json(text: str) -> EmploymentOfferLetterExtractionResult | None:
    """Defensively parse a model response into a employment offer letter result. Never raises."""
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
    employment_contingencies = _parse_employment_contingencies(
        payload.get("employment_contingencies")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = EmploymentOfferLetterExtraction.model_validate(
            {
                **core_payload,
                "employment_contingencies": employment_contingencies,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(employment_contingencies), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return EmploymentOfferLetterExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_employment_offer_letter(
    content: bytes, media_type: str
) -> EmploymentOfferLetterExtractionResult:
    """Extract employment offer letter values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return EmploymentOfferLetterExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return EmploymentOfferLetterExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="employment_offer_letter",
    )
    if call.text is None:
        return EmploymentOfferLetterExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_employment_offer_letter_json(call.text)
    if result is None:
        logger.warning("employment_offer_letter_extraction_parse_failed")  # no raw response logged
        return EmploymentOfferLetterExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "employment_offer_letter_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.employment_contingencies),
    )
    return result
