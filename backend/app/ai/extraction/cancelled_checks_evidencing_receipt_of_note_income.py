"""Cancelled Checks Evidencing Receipt Of Note Income extraction — GENERATED from a schema spec by the LP-434 generator.

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
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/cancelled_checks_evidencing_receipt_of_note_income.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class CancelledChecksEvidencingReceiptOfNoteIncomeExtraction(BaseModel):
    """A cancelled checks evidencing receipt of note income in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    drawer_or_maker_name: TypedField[str] = Field(default_factory=TypedField)
    drawer_bank_name: TypedField[str] = Field(default_factory=TypedField)
    drawer_account_last4: TypedField[str] = Field(default_factory=TypedField)
    payee_or_borrower_name: TypedField[str] = Field(default_factory=TypedField)
    check_number: TypedField[str] = Field(default_factory=TypedField)
    check_date: TypedField[date] = Field(default_factory=TypedField)
    check_amount_numeric: TypedField[Decimal] = Field(default_factory=TypedField)
    check_amount_written: TypedField[str] = Field(default_factory=TypedField)
    memo_or_note_reference: TypedField[str] = Field(default_factory=TypedField)
    front_image_present: TypedField[str] = Field(default_factory=TypedField)
    back_image_present: TypedField[str] = Field(default_factory=TypedField)
    payee_endorsement: TypedField[str] = Field(default_factory=TypedField)
    deposit_account_last4: TypedField[str] = Field(default_factory=TypedField)
    bank_paid_or_cleared_stamp: TypedField[str] = Field(default_factory=TypedField)
    cleared_date: TypedField[date] = Field(default_factory=TypedField)
    deposit_or_posting_date: TypedField[date] = Field(default_factory=TypedField)
    return_stop_or_void_indicator: TypedField[str] = Field(default_factory=TypedField)
    statement_or_transaction_reference: TypedField[str] = Field(default_factory=TypedField)
    related_note_date: TypedField[date] = Field(default_factory=TypedField)
    related_note_payment_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    related_note_maturity_date: TypedField[date] = Field(default_factory=TypedField)
    payment_period_start: TypedField[date] = Field(default_factory=TypedField)
    payment_period_end: TypedField[date] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult(BaseModel):
    """A cancelled checks evidencing receipt of note income extraction plus its outcome (mirrors the other extractor results)."""

    data: CancelledChecksEvidencingReceiptOfNoteIncomeExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CancelledChecksEvidencingReceiptOfNoteIncomeExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("drawer_or_maker_name", coerce_str),
    ("drawer_bank_name", coerce_str),
    ("drawer_account_last4", coerce_str),
    ("payee_or_borrower_name", coerce_str),
    ("check_number", coerce_str),
    ("check_date", coerce_date),
    ("check_amount_numeric", coerce_decimal),
    ("check_amount_written", coerce_str),
    ("memo_or_note_reference", coerce_str),
    ("front_image_present", coerce_str),
    ("back_image_present", coerce_str),
    ("payee_endorsement", coerce_str),
    ("deposit_account_last4", coerce_str),
    ("bank_paid_or_cleared_stamp", coerce_str),
    ("cleared_date", coerce_date),
    ("deposit_or_posting_date", coerce_date),
    ("return_stop_or_void_indicator", coerce_str),
    ("statement_or_transaction_reference", coerce_str),
    ("related_note_date", coerce_date),
    ("related_note_payment_amount", coerce_decimal),
    ("related_note_maturity_date", coerce_date),
    ("payment_period_start", coerce_date),
    ("payment_period_end", coerce_date),
)


def _parse_cancelled_checks_evidencing_receipt_of_note_income_json(
    text: str,
) -> CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult | None:
    """Defensively parse a model response into a cancelled checks evidencing receipt of note income result. Never raises."""
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
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = CancelledChecksEvidencingReceiptOfNoteIncomeExtraction.model_validate(
            {**core_payload, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_cancelled_checks_evidencing_receipt_of_note_income(
    content: bytes, media_type: str
) -> CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult:
    """Extract cancelled checks evidencing receipt of note income values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="cancelled_checks_evidencing_receipt_of_note_income",
    )
    if call.text is None:
        return CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_cancelled_checks_evidencing_receipt_of_note_income_json(call.text)
    if result is None:
        logger.warning(
            "cancelled_checks_evidencing_receipt_of_note_income_extraction_parse_failed"
        )  # no raw response logged
        return CancelledChecksEvidencingReceiptOfNoteIncomeExtractionResult.failed(
            "could not parse extraction"
        )

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "cancelled_checks_evidencing_receipt_of_note_income_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
