"""Homeowner S Insurance Quote extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/homeowner_s_insurance_quote.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class HomeownerSInsuranceQuoteExtraction(BaseModel):
    """A homeowner s insurance quote in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    insurance_carrier: TypedField[str] = Field(default_factory=TypedField)
    quote_number: TypedField[str] = Field(default_factory=TypedField)
    quote_date: TypedField[date] = Field(default_factory=TypedField)
    quote_valid_through_date: TypedField[date] = Field(default_factory=TypedField)
    proposed_effective_date: TypedField[date] = Field(default_factory=TypedField)
    binding_status: TypedField[str] = Field(default_factory=TypedField)
    estimated_or_final_premium_indicator: TypedField[str] = Field(default_factory=TypedField)
    agency_or_producer_name: TypedField[str] = Field(default_factory=TypedField)
    named_insured: TypedField[str] = Field(default_factory=TypedField)
    named_insured_2: TypedField[str] = Field(default_factory=TypedField)
    named_insured_count: TypedField[int] = Field(default_factory=TypedField)
    insured_property_address: TypedField[str] = Field(default_factory=TypedField)
    policy_number: TypedField[str] = Field(default_factory=TypedField)
    policy_status: TypedField[str] = Field(default_factory=TypedField)
    dwelling_coverage_a: TypedField[Decimal] = Field(default_factory=TypedField)
    other_structures_coverage_b: TypedField[Decimal] = Field(default_factory=TypedField)
    personal_property_coverage_c: TypedField[Decimal] = Field(default_factory=TypedField)
    personal_liability_coverage_e: TypedField[Decimal] = Field(default_factory=TypedField)
    replacement_cost_or_coinsurance_basis: TypedField[str] = Field(default_factory=TypedField)
    annual_premium: TypedField[Decimal] = Field(default_factory=TypedField)
    premium_paid_or_due_status: TypedField[str] = Field(default_factory=TypedField)
    effective_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    mortgagee_or_lienholder_entries: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class HomeownerSInsuranceQuoteExtractionResult(BaseModel):
    """A homeowner s insurance quote extraction plus its outcome (mirrors the other extractor results)."""

    data: HomeownerSInsuranceQuoteExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "HomeownerSInsuranceQuoteExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=HomeownerSInsuranceQuoteExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("insurance_carrier", coerce_str),
    ("quote_number", coerce_str),
    ("quote_date", coerce_date),
    ("quote_valid_through_date", coerce_date),
    ("proposed_effective_date", coerce_date),
    ("binding_status", coerce_str),
    ("estimated_or_final_premium_indicator", coerce_str),
    ("agency_or_producer_name", coerce_str),
    ("named_insured", coerce_str),
    ("named_insured_2", coerce_str),
    ("named_insured_count", coerce_int),
    ("insured_property_address", coerce_str),
    ("policy_number", coerce_str),
    ("policy_status", coerce_str),
    ("dwelling_coverage_a", coerce_decimal),
    ("other_structures_coverage_b", coerce_decimal),
    ("personal_property_coverage_c", coerce_decimal),
    ("personal_liability_coverage_e", coerce_decimal),
    ("replacement_cost_or_coinsurance_basis", coerce_str),
    ("annual_premium", coerce_decimal),
    ("premium_paid_or_due_status", coerce_str),
    ("effective_date", coerce_date),
    ("expiration_date", coerce_date),
)


_MORTGAGEE_OR_LIENHOLDER_ENTRIES_ROW: CoreSpec = (
    ("lender_name", coerce_str),
    ("loan_number", coerce_str),
    ("clause_address", coerce_str),
)


def _parse_mortgagee_or_lienholder_entries(raw: Any) -> list[dict[str, Any]]:
    """Coerce the mortgagee_or_lienholder_entries rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _MORTGAGEE_OR_LIENHOLDER_ENTRIES_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _MORTGAGEE_OR_LIENHOLDER_ENTRIES_ROW):
            rows.append(row)
    return rows


def _parse_homeowner_s_insurance_quote_json(
    text: str,
) -> HomeownerSInsuranceQuoteExtractionResult | None:
    """Defensively parse a model response into a homeowner s insurance quote result. Never raises."""
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
    mortgagee_or_lienholder_entries = _parse_mortgagee_or_lienholder_entries(
        payload.get("mortgagee_or_lienholder_entries")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = HomeownerSInsuranceQuoteExtraction.model_validate(
            {
                **core_payload,
                "mortgagee_or_lienholder_entries": mortgagee_or_lienholder_entries,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(mortgagee_or_lienholder_entries), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return HomeownerSInsuranceQuoteExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_homeowner_s_insurance_quote(
    content: bytes, media_type: str
) -> HomeownerSInsuranceQuoteExtractionResult:
    """Extract homeowner s insurance quote values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return HomeownerSInsuranceQuoteExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return HomeownerSInsuranceQuoteExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="homeowner_s_insurance_quote",
    )
    if call.text is None:
        return HomeownerSInsuranceQuoteExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_homeowner_s_insurance_quote_json(call.text)
    if result is None:
        logger.warning(
            "homeowner_s_insurance_quote_extraction_parse_failed"
        )  # no raw response logged
        return HomeownerSInsuranceQuoteExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "homeowner_s_insurance_quote_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.mortgagee_or_lienholder_entries),
    )
    return result
