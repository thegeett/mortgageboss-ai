"""Credit Report extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/credit_report.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 16384 (guide §7 sizing rule; 3 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 16384


class CreditReportExtraction(BaseModel):
    """A credit report in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    borrower_name: TypedField[str] = Field(default_factory=TypedField)
    co_borrower_name: TypedField[str] = Field(default_factory=TypedField)
    borrower_ssn: TypedField[str] = Field(default_factory=TypedField)
    co_borrower_ssn: TypedField[str] = Field(default_factory=TypedField)
    borrower_date_of_birth: TypedField[date] = Field(default_factory=TypedField)
    borrower_current_address: TypedField[str] = Field(default_factory=TypedField)
    borrower_former_address: TypedField[str] = Field(default_factory=TypedField)
    report_date: TypedField[date] = Field(default_factory=TypedField)
    score_date: TypedField[date] = Field(default_factory=TypedField)
    report_provider: TypedField[str] = Field(default_factory=TypedField)
    report_reference_number: TypedField[str] = Field(default_factory=TypedField)
    credit_report_type: TypedField[str] = Field(default_factory=TypedField)
    score_equifax: TypedField[int] = Field(default_factory=TypedField)
    score_experian: TypedField[int] = Field(default_factory=TypedField)
    score_transunion: TypedField[int] = Field(default_factory=TypedField)
    score_model: TypedField[str] = Field(default_factory=TypedField)
    open_tradeline_count: TypedField[int] = Field(default_factory=TypedField)
    total_tradeline_count: TypedField[int] = Field(default_factory=TypedField)
    total_monthly_debt_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    public_record_count: TypedField[int] = Field(default_factory=TypedField)
    inquiry_count: TypedField[int] = Field(default_factory=TypedField)
    security_freeze_or_fraud_alert: TypedField[str] = Field(default_factory=TypedField)
    ssn_alert_status: TypedField[str] = Field(default_factory=TypedField)
    ssn_first_reported_date: TypedField[date] = Field(default_factory=TypedField)
    address_usage_alert: TypedField[str] = Field(default_factory=TypedField)
    address_tenure_months: TypedField[int] = Field(default_factory=TypedField)
    credit_report_current_employer: TypedField[str] = Field(default_factory=TypedField)
    credit_report_previous_employer: TypedField[str] = Field(default_factory=TypedField)
    credit_report_occupation: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    tradelines: list[dict[str, Any]] = Field(default_factory=list)
    public_records: list[dict[str, Any]] = Field(default_factory=list)
    inquiries: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CreditReportExtractionResult(BaseModel):
    """A credit report extraction plus its outcome (mirrors the other extractor results)."""

    data: CreditReportExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CreditReportExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CreditReportExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("borrower_name", coerce_str),
    ("co_borrower_name", coerce_str),
    ("borrower_ssn", coerce_str),
    ("co_borrower_ssn", coerce_str),
    ("borrower_date_of_birth", coerce_date),
    ("borrower_current_address", coerce_str),
    ("borrower_former_address", coerce_str),
    ("report_date", coerce_date),
    ("score_date", coerce_date),
    ("report_provider", coerce_str),
    ("report_reference_number", coerce_str),
    ("credit_report_type", coerce_str),
    ("score_equifax", coerce_int),
    ("score_experian", coerce_int),
    ("score_transunion", coerce_int),
    ("score_model", coerce_str),
    ("open_tradeline_count", coerce_int),
    ("total_tradeline_count", coerce_int),
    ("total_monthly_debt_payment", coerce_decimal),
    ("public_record_count", coerce_int),
    ("inquiry_count", coerce_int),
    ("security_freeze_or_fraud_alert", coerce_str),
    ("ssn_alert_status", coerce_str),
    ("ssn_first_reported_date", coerce_date),
    ("address_usage_alert", coerce_str),
    ("address_tenure_months", coerce_int),
    ("credit_report_current_employer", coerce_str),
    ("credit_report_previous_employer", coerce_str),
    ("credit_report_occupation", coerce_str),
)


_TRADELINES_ROW: CoreSpec = (
    ("creditor_name", coerce_str),
    ("account_type", coerce_str),
    ("account_number_masked", coerce_str),
    ("account_ownership", coerce_str),
    ("date_opened", coerce_date),
    ("balance", coerce_decimal),
    ("credit_limit_or_high_credit", coerce_decimal),
    ("monthly_payment", coerce_decimal),
    ("past_due_amount", coerce_decimal),
    ("account_status", coerce_str),
    ("payment_status", coerce_str),
    ("payment_history_24mo", coerce_str),
    ("worst_delinquency", coerce_str),
    ("is_disputed", coerce_str),
)


def _parse_tradelines(raw: Any) -> list[dict[str, Any]]:
    """Coerce the tradelines rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {name: coerce(entry.get(name)) for name, coerce in _TRADELINES_ROW}
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _TRADELINES_ROW):
            rows.append(row)
    return rows


_PUBLIC_RECORDS_ROW: CoreSpec = (
    ("record_type", coerce_str),
    ("filing_date", coerce_date),
    ("discharge_or_satisfied_date", coerce_date),
    ("status", coerce_str),
    ("amount", coerce_decimal),
    ("court_or_jurisdiction", coerce_str),
)


def _parse_public_records(raw: Any) -> list[dict[str, Any]]:
    """Coerce the public_records rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _PUBLIC_RECORDS_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _PUBLIC_RECORDS_ROW):
            rows.append(row)
    return rows


_INQUIRIES_ROW: CoreSpec = (
    ("inquiry_date", coerce_date),
    ("creditor_name", coerce_str),
    ("inquiry_type", coerce_str),
)


def _parse_inquiries(raw: Any) -> list[dict[str, Any]]:
    """Coerce the inquiries rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {name: coerce(entry.get(name)) for name, coerce in _INQUIRIES_ROW}
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _INQUIRIES_ROW):
            rows.append(row)
    return rows


def _parse_credit_report_json(text: str) -> CreditReportExtractionResult | None:
    """Defensively parse a model response into a credit report result. Never raises."""
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
    tradelines = _parse_tradelines(payload.get("tradelines"))
    public_records = _parse_public_records(payload.get("public_records"))
    inquiries = _parse_inquiries(payload.get("inquiries"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = CreditReportExtraction.model_validate(
            {
                **core_payload,
                "tradelines": tradelines,
                "public_records": public_records,
                "inquiries": inquiries,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(
        non_null + len(tradelines) + len(public_records) + len(inquiries), coercion_lost
    )

    # Count cross-check (guide §8, LP-443): a declared count that disagrees with the
    # captured row count means rows were dropped WITHOUT the API truncating → PARTIAL.
    if (
        status is ExtractionStatus.SUCCEEDED
        and data.total_tradeline_count.value is not None
        and data.total_tradeline_count.value != len(data.tradelines)
    ):
        status = ExtractionStatus.PARTIAL
    if (
        status is ExtractionStatus.SUCCEEDED
        and data.public_record_count.value is not None
        and data.public_record_count.value != len(data.public_records)
    ):
        status = ExtractionStatus.PARTIAL
    if (
        status is ExtractionStatus.SUCCEEDED
        and data.inquiry_count.value is not None
        and data.inquiry_count.value != len(data.inquiries)
    ):
        status = ExtractionStatus.PARTIAL
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return CreditReportExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_credit_report(content: bytes, media_type: str) -> CreditReportExtractionResult:
    """Extract credit report values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CreditReportExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CreditReportExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="credit_report",
    )
    if call.text is None:
        return CreditReportExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_credit_report_json(call.text)
    if result is None:
        logger.warning("credit_report_extraction_parse_failed")  # no raw response logged
        return CreditReportExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "credit_report_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.tradelines)
        + len(result.data.public_records)
        + len(result.data.inquiries),
    )
    return result
