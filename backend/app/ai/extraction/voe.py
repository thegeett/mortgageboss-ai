"""VOE extraction (LP-60) — Tier 1 income/employment, following the LP-39a shape.

A Verification of Employment (VOE) is an employer-completed form confirming a
borrower's employment and income — high-value because the income is
employer-verified. The typed core captures the employment facts + the verified
income figures; everything else (prior-year earnings, breakdowns, remarks, the
verifier's signature block) lands in the grouped catch-all.

Mirrors :mod:`app.ai.extraction.w2`: typed core (each a ``TypedField`` with
source) + ``additional_sections`` catch-all, full-document Opus reading, the
shared tolerant parser, honest nulls, graceful ``.failed()``, and metadata-only
logging. Typed core is a **V1 starter — refine with Priya**; accuracy is validated
as real VOEs flow through (no samples were available when this was built).
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

_PROMPT_PATH = "extraction/voe.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 8192  # LP-446: list-bearing (gross_earnings_history) → unbounded-list budget


class VOEExtraction(BaseModel):
    """A VOE in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the employment facts (employer/employee, title, current vs
    former, dates) + the verified income (current amount + frequency, YTD, hours,
    probability of continued employment). **Grouped catch-all** — prior-year
    earnings, overtime/bonus breakdowns, remarks, verifier block, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    employer_name: TypedField[str] = Field(default_factory=TypedField)
    employee_name: TypedField[str] = Field(default_factory=TypedField)
    position_title: TypedField[str] = Field(default_factory=TypedField)
    employment_status: TypedField[str] = Field(default_factory=TypedField)  # current / former
    start_date: TypedField[date] = Field(default_factory=TypedField)
    end_date: TypedField[date] = Field(default_factory=TypedField)  # if former
    current_income_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    income_frequency: TypedField[str] = Field(default_factory=TypedField)  # annual/monthly/hourly
    ytd_income: TypedField[Decimal] = Field(default_factory=TypedField)
    hours: TypedField[Decimal] = Field(default_factory=TypedField)  # e.g. hours/week
    probability_of_continued_employment: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else, by section -------------------- #
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    document_issue_date: TypedField[date] = Field(default_factory=TypedField)
    employer_address: TypedField[str] = Field(default_factory=TypedField)
    lender_name: TypedField[str] = Field(default_factory=TypedField)
    applicant_address: TypedField[str] = Field(default_factory=TypedField)
    employee_number: TypedField[str] = Field(default_factory=TypedField)
    previous_employment_hire_date: TypedField[date] = Field(default_factory=TypedField)
    position_held: TypedField[str] = Field(default_factory=TypedField)
    employer_signer_name: TypedField[str] = Field(default_factory=TypedField)
    employer_signer_title: TypedField[str] = Field(default_factory=TypedField)
    employer_signer_phone: TypedField[str] = Field(default_factory=TypedField)
    employer_signature_and_date: TypedField[date] = Field(default_factory=TypedField)
    direct_return_to_lender_indicator: TypedField[str] = Field(default_factory=TypedField)
    applicant_authorization_signature: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-461 diff — verified scalar additions --------------------------- #
    # For a staffing-agency VOE the employer of record differs from where the person actually works:
    # ``employer_address`` is the corporate address; these capture the worksite + the client placement.
    work_location: TypedField[str] = Field(default_factory=TypedField)
    client_or_assignment_name: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-446 diff — captured nested list(s) (bare rows) --------------------- #
    gross_earnings_history: list[dict[str, Any]] = Field(default_factory=list)

    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class VOEExtractionResult(BaseModel):
    """A VOE extraction plus its outcome (mirrors ``W2ExtractionResult``)."""

    data: VOEExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "VOEExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=VOEExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("employer_name", coerce_str),
    ("employee_name", coerce_str),
    ("position_title", coerce_str),
    ("employment_status", coerce_str),
    ("start_date", coerce_date),
    ("end_date", coerce_date),
    ("current_income_amount", coerce_decimal),
    ("income_frequency", coerce_str),
    ("ytd_income", coerce_decimal),
    ("hours", coerce_decimal),
    ("probability_of_continued_employment", coerce_str),
    # LP-446 diff additions
    ("issuer_name", coerce_str),
    ("document_issue_date", coerce_date),
    ("employer_address", coerce_str),
    ("lender_name", coerce_str),
    ("applicant_address", coerce_str),
    ("employee_number", coerce_str),
    ("previous_employment_hire_date", coerce_date),
    ("position_held", coerce_str),
    ("employer_signer_name", coerce_str),
    ("employer_signer_title", coerce_str),
    ("employer_signer_phone", coerce_str),
    ("employer_signature_and_date", coerce_date),
    ("direct_return_to_lender_indicator", coerce_str),
    ("applicant_authorization_signature", coerce_str),
    # LP-461 diff additions
    ("work_location", coerce_str),
    ("client_or_assignment_name", coerce_str),
)

_GROSS_EARNINGS_HISTORY_ROW: CoreSpec = (
    ("period", coerce_str),
    ("base", coerce_str),
    ("overtime", coerce_str),
    ("commission", coerce_str),
    ("bonus", coerce_str),
)


def _parse_rows(raw: Any, row_spec: CoreSpec) -> list[dict[str, Any]]:
    """LP-446 — coerce a bare-row list (each declared field coerced, a per-row source kept, empty rows
    dropped). Mirrors bank_statement's transactions parse; row values are read as strings by the snapshot."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {name: coerce(entry.get(name)) for name, coerce in row_spec}
        row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in row_spec):
            rows.append(row)
    return rows


def _parse_voe_json(text: str) -> VOEExtractionResult | None:
    """Defensively parse a model response into a VOE result. Never raises."""
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
    gross_earnings_history = _parse_rows(
        payload.get("gross_earnings_history"), _GROSS_EARNINGS_HISTORY_ROW
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = VOEExtraction.model_validate(
            {
                **core_payload,
                "gross_earnings_history": gross_earnings_history,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(gross_earnings_history), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return VOEExtractionResult(data=data, status=status, confidence=confidence, reasoning=reasoning)


async def extract_voe(content: bytes, media_type: str) -> VOEExtractionResult:
    """Extract structured VOE values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`. The bytes/base64, raw
    response, and extracted values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return VOEExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return VOEExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="voe",
    )
    if call.text is None:
        return VOEExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_voe_json(call.text)
    if result is None:
        logger.warning("voe_extraction_parse_failed")  # no raw response logged
        return VOEExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — NEVER the values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "voe_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
