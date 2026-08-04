"""Appraisal extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/appraisal.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class AppraisalExtraction(BaseModel):
    """A appraisal in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    uad_version: TypedField[str] = Field(default_factory=TypedField)
    form_type: TypedField[str] = Field(default_factory=TypedField)
    appraisal_effective_date: TypedField[date] = Field(default_factory=TypedField)
    report_date: TypedField[date] = Field(default_factory=TypedField)
    appraiser_name: TypedField[str] = Field(default_factory=TypedField)
    appraiser_license: TypedField[str] = Field(default_factory=TypedField)
    lender_client_name: TypedField[str] = Field(default_factory=TypedField)
    subject_property_address: TypedField[str] = Field(default_factory=TypedField)
    county: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    parcel_identification_number: TypedField[str] = Field(default_factory=TypedField)
    property_type: TypedField[str] = Field(default_factory=TypedField)
    number_of_units: TypedField[int] = Field(default_factory=TypedField)
    occupant_status: TypedField[str] = Field(default_factory=TypedField)
    year_built: TypedField[int] = Field(default_factory=TypedField)
    gross_living_area: TypedField[int] = Field(default_factory=TypedField)
    project_name: TypedField[str] = Field(default_factory=TypedField)
    hoa_dues_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    hoa_dues_frequency: TypedField[str] = Field(default_factory=TypedField)
    appraised_value: TypedField[Decimal] = Field(default_factory=TypedField)
    contract_price_stated: TypedField[Decimal] = Field(default_factory=TypedField)
    value_approach_used: TypedField[str] = Field(default_factory=TypedField)
    property_owner_of_record: TypedField[str] = Field(default_factory=TypedField)
    prior_sale_date: TypedField[date] = Field(default_factory=TypedField)
    prior_sale_price: TypedField[Decimal] = Field(default_factory=TypedField)
    condition_rating: TypedField[str] = Field(default_factory=TypedField)
    quality_rating: TypedField[str] = Field(default_factory=TypedField)
    appraisal_completion_condition: TypedField[str] = Field(default_factory=TypedField)
    repairs_required_indicator: TypedField[str] = Field(default_factory=TypedField)
    fha_condition_deficiencies: TypedField[str] = Field(default_factory=TypedField)
    estimated_monthly_market_rent: TypedField[Decimal] = Field(default_factory=TypedField)
    rent_schedule_attached: TypedField[str] = Field(default_factory=TypedField)
    comparable_count: TypedField[int] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    comparable_sales: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class AppraisalExtractionResult(BaseModel):
    """A appraisal extraction plus its outcome (mirrors the other extractor results)."""

    data: AppraisalExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "AppraisalExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=AppraisalExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("uad_version", coerce_str),
    ("form_type", coerce_str),
    ("appraisal_effective_date", coerce_date),
    ("report_date", coerce_date),
    ("appraiser_name", coerce_str),
    ("appraiser_license", coerce_str),
    ("lender_client_name", coerce_str),
    ("subject_property_address", coerce_str),
    ("county", coerce_str),
    ("legal_description", coerce_str),
    ("parcel_identification_number", coerce_str),
    ("property_type", coerce_str),
    ("number_of_units", coerce_int),
    ("occupant_status", coerce_str),
    ("year_built", coerce_int),
    ("gross_living_area", coerce_int),
    ("project_name", coerce_str),
    ("hoa_dues_amount", coerce_decimal),
    ("hoa_dues_frequency", coerce_str),
    ("appraised_value", coerce_decimal),
    ("contract_price_stated", coerce_decimal),
    ("value_approach_used", coerce_str),
    ("property_owner_of_record", coerce_str),
    ("prior_sale_date", coerce_date),
    ("prior_sale_price", coerce_decimal),
    ("condition_rating", coerce_str),
    ("quality_rating", coerce_str),
    ("appraisal_completion_condition", coerce_str),
    ("repairs_required_indicator", coerce_str),
    ("fha_condition_deficiencies", coerce_str),
    ("estimated_monthly_market_rent", coerce_decimal),
    ("rent_schedule_attached", coerce_str),
    ("comparable_count", coerce_int),
)


_COMPARABLE_SALES_ROW: CoreSpec = (
    ("comp_number", coerce_int),
    ("address", coerce_str),
    ("sale_price", coerce_decimal),
    ("sale_date", coerce_date),
    ("gross_living_area", coerce_int),
    ("distance_from_subject", coerce_str),
    ("net_adjustment", coerce_decimal),
    ("adjusted_value", coerce_decimal),
)


def _parse_comparable_sales(raw: Any) -> list[dict[str, Any]]:
    """Coerce the comparable_sales rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _COMPARABLE_SALES_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _COMPARABLE_SALES_ROW):
            rows.append(row)
    return rows


def _parse_appraisal_json(text: str) -> AppraisalExtractionResult | None:
    """Defensively parse a model response into a appraisal result. Never raises."""
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
    comparable_sales = _parse_comparable_sales(payload.get("comparable_sales"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = AppraisalExtraction.model_validate(
            {**core_payload, "comparable_sales": comparable_sales, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(comparable_sales), coercion_lost)

    # Count cross-check (guide §8, LP-443): a declared count that disagrees with the
    # captured row count means rows were dropped WITHOUT the API truncating → PARTIAL.
    if (
        status is ExtractionStatus.SUCCEEDED
        and data.comparable_count.value is not None
        and data.comparable_count.value != len(data.comparable_sales)
    ):
        status = ExtractionStatus.PARTIAL
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return AppraisalExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_appraisal(content: bytes, media_type: str) -> AppraisalExtractionResult:
    """Extract appraisal values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return AppraisalExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return AppraisalExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="appraisal",
    )
    if call.text is None:
        return AppraisalExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_appraisal_json(call.text)
    if result is None:
        logger.warning("appraisal_extraction_parse_failed")  # no raw response logged
        return AppraisalExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "appraisal_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.comparable_sales),
    )
    return result
