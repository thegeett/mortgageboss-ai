"""Form 1120 Corporate Tax Transcripts extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/form_1120_corporate_tax_transcripts.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class Form1120CorporateTaxTranscriptsExtraction(BaseModel):
    """A form 1120 corporate tax transcripts in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    transcript_type: TypedField[str] = Field(default_factory=TypedField)
    tax_form_number: TypedField[str] = Field(default_factory=TypedField)
    tax_period_ending: TypedField[date] = Field(default_factory=TypedField)
    request_or_processing_date: TypedField[date] = Field(default_factory=TypedField)
    corporation_legal_name: TypedField[str] = Field(default_factory=TypedField)
    ein_masked: TypedField[str] = Field(default_factory=TypedField)
    business_address: TypedField[str] = Field(default_factory=TypedField)
    date_incorporated: TypedField[date] = Field(default_factory=TypedField)
    accounting_method: TypedField[str] = Field(default_factory=TypedField)
    consolidated_return_indicator: TypedField[str] = Field(default_factory=TypedField)
    gross_receipts_or_sales: TypedField[Decimal] = Field(default_factory=TypedField)
    cost_of_goods_sold: TypedField[Decimal] = Field(default_factory=TypedField)
    gross_profit: TypedField[Decimal] = Field(default_factory=TypedField)
    total_income: TypedField[Decimal] = Field(default_factory=TypedField)
    taxable_income_before_nol_and_special_deductions: TypedField[Decimal] = Field(
        default_factory=TypedField
    )
    taxable_income: TypedField[Decimal] = Field(default_factory=TypedField)
    total_tax: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    officer_compensation: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class Form1120CorporateTaxTranscriptsExtractionResult(BaseModel):
    """A form 1120 corporate tax transcripts extraction plus its outcome (mirrors the other extractor results)."""

    data: Form1120CorporateTaxTranscriptsExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "Form1120CorporateTaxTranscriptsExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=Form1120CorporateTaxTranscriptsExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("transcript_type", coerce_str),
    ("tax_form_number", coerce_str),
    ("tax_period_ending", coerce_date),
    ("request_or_processing_date", coerce_date),
    ("corporation_legal_name", coerce_str),
    ("ein_masked", coerce_str),
    ("business_address", coerce_str),
    ("date_incorporated", coerce_date),
    ("accounting_method", coerce_str),
    ("consolidated_return_indicator", coerce_str),
    ("gross_receipts_or_sales", coerce_decimal),
    ("cost_of_goods_sold", coerce_decimal),
    ("gross_profit", coerce_decimal),
    ("total_income", coerce_decimal),
    ("taxable_income_before_nol_and_special_deductions", coerce_decimal),
    ("taxable_income", coerce_decimal),
    ("total_tax", coerce_decimal),
)


_OFFICER_COMPENSATION_ROW: CoreSpec = (
    ("officer_name_or_label", coerce_str),
    ("title", coerce_str),
    ("percent_time_or_ownership", coerce_str),
    ("compensation_amount", coerce_decimal),
    ("source", coerce_str),
)


def _parse_officer_compensation(raw: Any) -> list[dict[str, Any]]:
    """Coerce the officer_compensation rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _OFFICER_COMPENSATION_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _OFFICER_COMPENSATION_ROW):
            rows.append(row)
    return rows


def _parse_form_1120_corporate_tax_transcripts_json(
    text: str,
) -> Form1120CorporateTaxTranscriptsExtractionResult | None:
    """Defensively parse a model response into a form 1120 corporate tax transcripts result. Never raises."""
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
    officer_compensation = _parse_officer_compensation(payload.get("officer_compensation"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = Form1120CorporateTaxTranscriptsExtraction.model_validate(
            {
                **core_payload,
                "officer_compensation": officer_compensation,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(officer_compensation), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return Form1120CorporateTaxTranscriptsExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_form_1120_corporate_tax_transcripts(
    content: bytes, media_type: str
) -> Form1120CorporateTaxTranscriptsExtractionResult:
    """Extract form 1120 corporate tax transcripts values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return Form1120CorporateTaxTranscriptsExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return Form1120CorporateTaxTranscriptsExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="form_1120_corporate_tax_transcripts",
    )
    if call.text is None:
        return Form1120CorporateTaxTranscriptsExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_form_1120_corporate_tax_transcripts_json(call.text)
    if result is None:
        logger.warning(
            "form_1120_corporate_tax_transcripts_extraction_parse_failed"
        )  # no raw response logged
        return Form1120CorporateTaxTranscriptsExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "form_1120_corporate_tax_transcripts_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.officer_compensation),
    )
    return result
