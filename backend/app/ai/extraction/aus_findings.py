"""Aus Findings extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/aus_findings.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class AusFindingsExtraction(BaseModel):
    """A aus findings in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    aus_engine: TypedField[str] = Field(default_factory=TypedField)
    casefile_or_key_number: TypedField[str] = Field(default_factory=TypedField)
    submission_date: TypedField[date] = Field(default_factory=TypedField)
    submission_number: TypedField[int] = Field(default_factory=TypedField)
    lender_loan_number: TypedField[str] = Field(default_factory=TypedField)
    recommendation: TypedField[str] = Field(default_factory=TypedField)
    eligibility_status: TypedField[str] = Field(default_factory=TypedField)
    risk_class: TypedField[str] = Field(default_factory=TypedField)
    ineligibility_reasons: TypedField[str] = Field(default_factory=TypedField)
    aus_qualifying_income: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_total_assets: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_credit_score: TypedField[int] = Field(default_factory=TypedField)
    aus_dti_ratio: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_ltv_ratio: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_cltv_ratio: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_loan_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_property_value: TypedField[Decimal] = Field(default_factory=TypedField)
    aus_occupancy: TypedField[str] = Field(default_factory=TypedField)
    aus_loan_purpose: TypedField[str] = Field(default_factory=TypedField)
    required_reserve_months: TypedField[Decimal] = Field(default_factory=TypedField)
    asset_documentation_level: TypedField[str] = Field(default_factory=TypedField)
    income_documentation_level: TypedField[str] = Field(default_factory=TypedField)
    condition_count: TypedField[int] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    aus_required_conditions: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class AusFindingsExtractionResult(BaseModel):
    """A aus findings extraction plus its outcome (mirrors the other extractor results)."""

    data: AusFindingsExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "AusFindingsExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=AusFindingsExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("aus_engine", coerce_str),
    ("casefile_or_key_number", coerce_str),
    ("submission_date", coerce_date),
    ("submission_number", coerce_int),
    ("lender_loan_number", coerce_str),
    ("recommendation", coerce_str),
    ("eligibility_status", coerce_str),
    ("risk_class", coerce_str),
    ("ineligibility_reasons", coerce_str),
    ("aus_qualifying_income", coerce_decimal),
    ("aus_total_assets", coerce_decimal),
    ("aus_credit_score", coerce_int),
    ("aus_dti_ratio", coerce_decimal),
    ("aus_ltv_ratio", coerce_decimal),
    ("aus_cltv_ratio", coerce_decimal),
    ("aus_loan_amount", coerce_decimal),
    ("aus_property_value", coerce_decimal),
    ("aus_occupancy", coerce_str),
    ("aus_loan_purpose", coerce_str),
    ("required_reserve_months", coerce_decimal),
    ("asset_documentation_level", coerce_str),
    ("income_documentation_level", coerce_str),
    ("condition_count", coerce_int),
)


_AUS_REQUIRED_CONDITIONS_ROW: CoreSpec = (
    ("condition_number", coerce_str),
    ("condition_category", coerce_str),
    ("condition_text", coerce_str),
    ("is_prior_to_close", coerce_str),
)


def _parse_aus_required_conditions(raw: Any) -> list[dict[str, Any]]:
    """Coerce the aus_required_conditions rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _AUS_REQUIRED_CONDITIONS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _AUS_REQUIRED_CONDITIONS_ROW):
            rows.append(row)
    return rows


def _parse_aus_findings_json(text: str) -> AusFindingsExtractionResult | None:
    """Defensively parse a model response into a aus findings result. Never raises."""
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
    aus_required_conditions = _parse_aus_required_conditions(payload.get("aus_required_conditions"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = AusFindingsExtraction.model_validate(
            {
                **core_payload,
                "aus_required_conditions": aus_required_conditions,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(aus_required_conditions), coercion_lost)

    # Count cross-check (guide §8, LP-443): a declared count that disagrees with the
    # captured row count means rows were dropped WITHOUT the API truncating → PARTIAL.
    if (
        status is ExtractionStatus.SUCCEEDED
        and data.condition_count.value is not None
        and data.condition_count.value != len(data.aus_required_conditions)
    ):
        status = ExtractionStatus.PARTIAL
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return AusFindingsExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_aus_findings(content: bytes, media_type: str) -> AusFindingsExtractionResult:
    """Extract aus findings values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return AusFindingsExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return AusFindingsExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="aus_findings",
    )
    if call.text is None:
        return AusFindingsExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_aus_findings_json(call.text)
    if result is None:
        logger.warning("aus_findings_extraction_parse_failed")  # no raw response logged
        return AusFindingsExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "aus_findings_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.aus_required_conditions),
    )
    return result
