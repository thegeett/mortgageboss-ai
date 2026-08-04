"""Trust Federal Tax Returns extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/trust_federal_tax_returns.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class TrustFederalTaxReturnsExtraction(BaseModel):
    """A trust federal tax returns in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    document_title: TypedField[str] = Field(default_factory=TypedField)
    form_number: TypedField[str] = Field(default_factory=TypedField)
    tax_year_or_period: TypedField[str] = Field(default_factory=TypedField)
    estate_or_trust_name: TypedField[str] = Field(default_factory=TypedField)
    ein: TypedField[str] = Field(default_factory=TypedField)
    entity_type: TypedField[str] = Field(default_factory=TypedField)
    initial_final_or_amended_return: TypedField[str] = Field(default_factory=TypedField)
    date_entity_created: TypedField[date] = Field(default_factory=TypedField)
    fiduciary_name: TypedField[str] = Field(default_factory=TypedField)
    fiduciary_address: TypedField[str] = Field(default_factory=TypedField)
    party_names_raw: TypedField[str] = Field(default_factory=TypedField)
    total_income: TypedField[Decimal] = Field(default_factory=TypedField)
    income_distribution_deduction: TypedField[Decimal] = Field(default_factory=TypedField)
    distributable_net_income: TypedField[Decimal] = Field(default_factory=TypedField)
    distributions_paid_or_required: TypedField[Decimal] = Field(default_factory=TypedField)
    taxable_income: TypedField[Decimal] = Field(default_factory=TypedField)
    total_tax: TypedField[Decimal] = Field(default_factory=TypedField)
    accounting_method: TypedField[str] = Field(default_factory=TypedField)
    fiduciary_signed: TypedField[str] = Field(default_factory=TypedField)
    fiduciary_signature_date: TypedField[date] = Field(default_factory=TypedField)
    preparer_name: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    beneficiary_k1_records: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class TrustFederalTaxReturnsExtractionResult(BaseModel):
    """A trust federal tax returns extraction plus its outcome (mirrors the other extractor results)."""

    data: TrustFederalTaxReturnsExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "TrustFederalTaxReturnsExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=TrustFederalTaxReturnsExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_title", coerce_str),
    ("form_number", coerce_str),
    ("tax_year_or_period", coerce_str),
    ("estate_or_trust_name", coerce_str),
    ("ein", coerce_str),
    ("entity_type", coerce_str),
    ("initial_final_or_amended_return", coerce_str),
    ("date_entity_created", coerce_date),
    ("fiduciary_name", coerce_str),
    ("fiduciary_address", coerce_str),
    ("party_names_raw", coerce_str),
    ("total_income", coerce_decimal),
    ("income_distribution_deduction", coerce_decimal),
    ("distributable_net_income", coerce_decimal),
    ("distributions_paid_or_required", coerce_decimal),
    ("taxable_income", coerce_decimal),
    ("total_tax", coerce_decimal),
    ("accounting_method", coerce_str),
    ("fiduciary_signed", coerce_str),
    ("fiduciary_signature_date", coerce_date),
    ("preparer_name", coerce_str),
)


_BENEFICIARY_K1_RECORDS_ROW: CoreSpec = (
    ("beneficiary_name", coerce_str),
    ("beneficiary_tin_masked", coerce_str),
    ("distributive_share_amount", coerce_decimal),
    ("income_type", coerce_str),
    ("source", coerce_str),
)


def _parse_beneficiary_k1_records(raw: Any) -> list[dict[str, Any]]:
    """Coerce the beneficiary_k1_records rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _BENEFICIARY_K1_RECORDS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _BENEFICIARY_K1_RECORDS_ROW):
            rows.append(row)
    return rows


def _parse_trust_federal_tax_returns_json(
    text: str,
) -> TrustFederalTaxReturnsExtractionResult | None:
    """Defensively parse a model response into a trust federal tax returns result. Never raises."""
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
    beneficiary_k1_records = _parse_beneficiary_k1_records(payload.get("beneficiary_k1_records"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = TrustFederalTaxReturnsExtraction.model_validate(
            {
                **core_payload,
                "beneficiary_k1_records": beneficiary_k1_records,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(beneficiary_k1_records), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return TrustFederalTaxReturnsExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_trust_federal_tax_returns(
    content: bytes, media_type: str
) -> TrustFederalTaxReturnsExtractionResult:
    """Extract trust federal tax returns values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return TrustFederalTaxReturnsExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return TrustFederalTaxReturnsExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="trust_federal_tax_returns",
    )
    if call.text is None:
        return TrustFederalTaxReturnsExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_trust_federal_tax_returns_json(call.text)
    if result is None:
        logger.warning(
            "trust_federal_tax_returns_extraction_parse_failed"
        )  # no raw response logged
        return TrustFederalTaxReturnsExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "trust_federal_tax_returns_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.beneficiary_k1_records),
    )
    return result
