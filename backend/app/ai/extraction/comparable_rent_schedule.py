"""Comparable rent schedule extraction (LP-642 step 2) — Tier 1 property, the LP-39a shape.

**THE DOCUMENT A RENTAL PURCHASE CANNOT QUALIFY WITHOUT.** Fannie B3-3.8-02 (09/02/2026) makes one of
these mandatory where the subject's rental income is used to qualify:

    "The lender must obtain the following: a Single-Family Comparable Rent Schedule (Form 1007) or
     Small Residential Income Property Appraisal Report (Form 1025), as applicable"

Until LP-642 step 1 neither form had a document type at all, so the DTI on an investment purchase
gated for want of a rent nothing could supply — LF-ZE9N is the file that surfaced it. Step 1 made
them requestable and fileable; this reads the number off them.

**ONE EXTRACTOR, TWO FORMS.** A 1007 (one unit) and a 1025 (two-to-four) answer the same question in
the same shape — an appraiser's opinion of monthly market rent, supported by comparable rentals — so
they share this module and are registered against both document types. ``form_type`` records which
was read, and ``unit_rents`` carries the per-unit breakdown a 1025 has and a 1007 does not.

**THE FIELD THAT MATTERS IS ``opinion_of_monthly_market_rent``**, because that is what the DTI
consumes. Everything else here is provenance a processor uses to judge it: the comparables, the
effective date, who signed it. A form whose grid is present but whose opinion line is blank must read
NULL rather than a total or an average of the comparables — an appraiser's opinion is a judgement,
not the arithmetic mean of the rows above it, and inventing one would put a fabricated rent into a
qualifying ratio.

Starter accuracy, like every extractor here — **refine with the domain expert** as real forms flow
through. No samples were available when this was written.
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
    parse_flat_rows,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/comparable_rent_schedule.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 16384  # two nested lists (comparable_rentals + unit_rents), like property_tax_bill


class ComparableRentScheduleExtraction(BaseModel):
    """A Form 1007 / 1025 in the LP-39a shape: typed core + nested lists + grouped catch-all."""

    # --- Typed core --------------------------------------------------------- #
    form_type: TypedField[str] = Field(
        default_factory=TypedField
    )  # "1007" | "1025" — which form was read
    property_address: TypedField[str] = Field(
        default_factory=TypedField
    )  # matches the subject (LP-642 step 3)
    #: THE FIGURE THE DTI CONSUMES. The appraiser's opinion of monthly market rent for the subject.
    #: Never an average of the comparables and never a total — see the module note.
    opinion_of_monthly_market_rent: TypedField[Decimal] = Field(default_factory=TypedField)
    #: A 1025 states gross monthly income across all units; a 1007 does not. Distinct from the
    #: opinion above on a multi-unit form, and identical to it on a single-unit one.
    total_gross_monthly_income: TypedField[Decimal] = Field(default_factory=TypedField)
    unit_count: TypedField[int] = Field(default_factory=TypedField)  # 1 on a 1007; 2-4 on a 1025
    effective_date: TypedField[date] = Field(
        default_factory=TypedField
    )  # B3-3.8-01 ages the form against the note date
    appraiser_name: TypedField[str] = Field(default_factory=TypedField)
    appraiser_license_number: TypedField[str] = Field(default_factory=TypedField)
    appraisal_company: TypedField[str] = Field(default_factory=TypedField)
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    lender_or_client: TypedField[str] = Field(default_factory=TypedField)

    # --- Nested lists ------------------------------------------------------- #
    #: The comparables grid — the evidence behind the opinion. Read verbatim as strings: a rent may be
    #: written "$1,850/mo" and an adjustment "-100", and normalising either here would lose what the
    #: appraiser wrote without the DTI gaining anything (it consumes the opinion, not the grid).
    comparable_rentals: list[dict[str, str | None]] = Field(default_factory=list)
    #: A 1025's per-unit rents. Empty on a 1007, which has one unit and no breakdown.
    unit_rents: list[dict[str, str | None]] = Field(default_factory=list)

    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class ComparableRentScheduleExtractionResult(BaseModel):
    """A rent-schedule extraction plus its outcome (mirrors the other results)."""

    data: ComparableRentScheduleExtraction
    status: ExtractionStatus
    confidence: float = 0.0
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_used: str | None = None

    @classmethod
    def failed(cls, reason: str) -> "ComparableRentScheduleExtractionResult":
        return cls(
            data=ComparableRentScheduleExtraction(),
            status=ExtractionStatus.FAILED,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("form_type", coerce_str),
    ("property_address", coerce_str),
    ("opinion_of_monthly_market_rent", coerce_decimal),
    ("total_gross_monthly_income", coerce_decimal),
    ("unit_count", coerce_int),
    ("effective_date", coerce_date),
    ("appraiser_name", coerce_str),
    ("appraiser_license_number", coerce_str),
    ("appraisal_company", coerce_str),
    ("borrower_name", coerce_str),
    ("lender_or_client", coerce_str),
)

# Verbatim strings — see `comparable_rentals`.
_COMPARABLE_ROW: CoreSpec = (
    ("comparable_label", coerce_str),
    ("address", coerce_str),
    ("proximity_to_subject", coerce_str),
    ("monthly_rent", coerce_str),
    ("date_of_lease", coerce_str),
    ("unit_breakdown", coerce_str),
    ("adjustments", coerce_str),
    ("adjusted_monthly_rent", coerce_str),
)

_UNIT_ROW: CoreSpec = (
    ("unit_label", coerce_str),
    ("bedrooms", coerce_str),
    ("actual_rent", coerce_str),
    ("market_rent", coerce_str),
    ("lease_status", coerce_str),
)


def _parse_comparable_rent_schedule_json(
    text: str,
) -> ComparableRentScheduleExtractionResult | None:
    """Defensively parse a model response into a rent-schedule result. Never raises."""
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
    comparables = parse_flat_rows(payload.get("comparable_rentals"), _COMPARABLE_ROW)
    unit_rents = parse_flat_rows(payload.get("unit_rents"), _UNIT_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = ComparableRentScheduleExtraction.model_validate(
            {
                **core_payload,
                "comparable_rentals": comparables,
                "unit_rents": unit_rents,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(comparables) + len(unit_rents), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return ComparableRentScheduleExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_comparable_rent_schedule(
    content: bytes, media_type: str
) -> ComparableRentScheduleExtractionResult:
    """Extract Form 1007 / 1025 values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted values are never
    logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return ComparableRentScheduleExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return ComparableRentScheduleExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="comparable_rent_schedule",
    )
    if call.text is None:
        return ComparableRentScheduleExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_comparable_rent_schedule_json(call.text)
    if result is None:
        logger.warning("comparable_rent_schedule_extraction_parse_failed")  # no raw response logged
        return ComparableRentScheduleExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values. The market rent in particular is a
    # figure a qualifying ratio rests on and has no business in a log line.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "comparable_rent_schedule_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        comparables=len(result.data.comparable_rentals),
        unit_rows=len(result.data.unit_rents),
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
