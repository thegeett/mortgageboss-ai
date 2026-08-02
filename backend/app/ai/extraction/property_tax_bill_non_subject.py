"""Property Tax Bill Non Subject extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/property_tax_bill_non_subject.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class PropertyTaxBillNonSubjectExtraction(BaseModel):
    """A property tax bill non subject in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    taxing_authority: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    parcel_or_apn: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_name: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_name_2: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_count: TypedField[int] = Field(default_factory=TypedField)
    tax_bill_or_account_number: TypedField[str] = Field(default_factory=TypedField)
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    total_assessed_value: TypedField[Decimal] = Field(default_factory=TypedField)
    taxable_value: TypedField[Decimal] = Field(default_factory=TypedField)
    base_tax_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    total_tax_due: TypedField[Decimal] = Field(default_factory=TypedField)
    penalties_and_interest: TypedField[Decimal] = Field(default_factory=TypedField)
    current_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    delinquent_or_lien_status: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    subject_property_indicator: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    installments_and_due_dates: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PropertyTaxBillNonSubjectExtractionResult(BaseModel):
    """A property tax bill non subject extraction plus its outcome (mirrors the other extractor results)."""

    data: PropertyTaxBillNonSubjectExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PropertyTaxBillNonSubjectExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PropertyTaxBillNonSubjectExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("taxing_authority", coerce_str),
    ("property_address", coerce_str),
    ("parcel_or_apn", coerce_str),
    ("taxpayer_name", coerce_str),
    ("taxpayer_name_2", coerce_str),
    ("taxpayer_count", coerce_int),
    ("tax_bill_or_account_number", coerce_str),
    ("tax_year", coerce_int),
    ("total_assessed_value", coerce_decimal),
    ("taxable_value", coerce_decimal),
    ("base_tax_amount", coerce_decimal),
    ("total_tax_due", coerce_decimal),
    ("penalties_and_interest", coerce_decimal),
    ("current_balance", coerce_decimal),
    ("delinquent_or_lien_status", coerce_str),
    ("legal_description", coerce_str),
    ("subject_property_indicator", coerce_str),
    ("loan_number", coerce_str),
)


_INSTALLMENTS_AND_DUE_DATES_ROW: CoreSpec = (
    ("installment_label", coerce_str),
    ("amount", coerce_decimal),
    ("due_date", coerce_date),
    ("paid_indicator", coerce_str),
)


def _parse_installments_and_due_dates(raw: Any) -> list[dict[str, Any]]:
    """Coerce the installments_and_due_dates rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _INSTALLMENTS_AND_DUE_DATES_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _INSTALLMENTS_AND_DUE_DATES_ROW):
            rows.append(row)
    return rows


def _parse_property_tax_bill_non_subject_json(
    text: str,
) -> PropertyTaxBillNonSubjectExtractionResult | None:
    """Defensively parse a model response into a property tax bill non subject result. Never raises."""
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
    installments_and_due_dates = _parse_installments_and_due_dates(
        payload.get("installments_and_due_dates")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = PropertyTaxBillNonSubjectExtraction.model_validate(
            {
                **core_payload,
                "installments_and_due_dates": installments_and_due_dates,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(installments_and_due_dates), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return PropertyTaxBillNonSubjectExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_property_tax_bill_non_subject(
    content: bytes, media_type: str
) -> PropertyTaxBillNonSubjectExtractionResult:
    """Extract property tax bill non subject values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PropertyTaxBillNonSubjectExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PropertyTaxBillNonSubjectExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="property_tax_bill_non_subject",
    )
    if call.text is None:
        return PropertyTaxBillNonSubjectExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_property_tax_bill_non_subject_json(call.text)
    if result is None:
        logger.warning(
            "property_tax_bill_non_subject_extraction_parse_failed"
        )  # no raw response logged
        return PropertyTaxBillNonSubjectExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "property_tax_bill_non_subject_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.installments_and_due_dates),
    )
    return result
