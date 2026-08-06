"""HOA statement extraction (LP-62) — Tier 1 property, the LP-39a shape.

A homeowners-association (HOA) statement documents the **dues** owed on a property
— a recurring obligation (housing expense / DTI). The typed core captures the
association, the property, the dues amount + frequency, the balance, and the due
date; assessment breakdowns / fees / contact details land in the grouped catch-all.
**The ``property_address`` is captured** so Phase 3 can match subject-vs-other.

Mirrors the existing extractors: typed core + ``additional_sections`` catch-all,
honest nulls, graceful ``.failed()``, metadata-only logging. **V1 starter — refine
with Priya**; accuracy validated as real statements flow through (no samples).
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
    parse_flat_rows,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/hoa_statement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = (
    16384  # LP-460: TWO nested lists (special_assessment_items + payment_ledger) → ≥2-list tier
)


class HOAStatementExtraction(BaseModel):
    """An HOA statement in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the ``association_name``, the ``property_address`` (captured for
    Phase 3 matching), the ``dues_amount`` + ``dues_frequency`` (the obligation), the
    ``balance``, and the ``due_date``. **Grouped catch-all** — special assessments,
    late fees, fines, management-company contact, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    owner_name: TypedField[str] = Field(
        default_factory=TypedField
    )  # the homeowner-borrower (LP-202)
    association_name: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)  # subject-vs-other: P3
    dues_amount: TypedField[Decimal] = Field(default_factory=TypedField)  # obligation
    dues_frequency: TypedField[str] = Field(default_factory=TypedField)  # monthly / quarterly / ...
    balance: TypedField[Decimal] = Field(default_factory=TypedField)
    due_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    management_company: TypedField[str] = Field(default_factory=TypedField)
    association_contact_phone: TypedField[str] = Field(default_factory=TypedField)
    association_contact_email_or_url: TypedField[str] = Field(default_factory=TypedField)
    association_contact_address: TypedField[str] = Field(default_factory=TypedField)
    unit_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    owner_account_number_masked: TypedField[str] = Field(default_factory=TypedField)
    statement_date: TypedField[date] = Field(default_factory=TypedField)
    past_due_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    paid_current_indicator: TypedField[str] = Field(default_factory=TypedField)
    collection_or_lien_status: TypedField[str] = Field(default_factory=TypedField)
    reserve_percentage: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-446 diff — captured nested list(s) (bare rows) --------------------- #
    special_assessment_items: list[dict[str, Any]] = Field(default_factory=list)
    # --- LP-460 diff — the account ledger (a posting table with nowhere to land today) ------ #
    payment_ledger: list[dict[str, Any]] = Field(default_factory=list)

    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class HOAStatementExtractionResult(BaseModel):
    """An HOA-statement extraction plus its outcome (mirrors the other results)."""

    data: HOAStatementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "HOAStatementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=HOAStatementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("owner_name", coerce_str),
    ("association_name", coerce_str),
    ("property_address", coerce_str),
    ("dues_amount", coerce_decimal),
    ("dues_frequency", coerce_str),
    ("balance", coerce_decimal),
    ("due_date", coerce_date),
    # LP-446 diff additions
    ("issuer_name", coerce_str),
    ("management_company", coerce_str),
    ("association_contact_phone", coerce_str),
    ("association_contact_email_or_url", coerce_str),
    ("association_contact_address", coerce_str),
    ("unit_owner_name_2", coerce_str),
    ("owner_account_number_masked", coerce_str),
    ("statement_date", coerce_date),
    ("past_due_amount", coerce_decimal),
    ("paid_current_indicator", coerce_str),
    ("collection_or_lien_status", coerce_str),
    ("reserve_percentage", coerce_str),
)

_SPECIAL_ASSESSMENT_ITEMS_ROW: CoreSpec = (
    ("description", coerce_str),
    ("amount", coerce_str),
    ("duration", coerce_str),
)

# LP-460 — the account ledger rows (Date / Description / Charge / Paid / Balance). Row values are read as
# strings by the snapshot, kept verbatim (coerce_str). ``running_balance`` (not ``balance``) — the scalar
# typed-core ``balance`` is the account's current balance; the per-row balance is the running one.
_PAYMENT_LEDGER_ROW: CoreSpec = (
    ("date", coerce_str),
    ("description", coerce_str),
    ("charge", coerce_str),
    ("paid", coerce_str),
    ("running_balance", coerce_str),
)


def _parse_hoa_statement_json(text: str) -> HOAStatementExtractionResult | None:
    """Defensively parse a model response into an HOA-statement result. Never raises."""
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
    special_assessment_items = parse_flat_rows(
        payload.get("special_assessment_items"), _SPECIAL_ASSESSMENT_ITEMS_ROW
    )
    payment_ledger = parse_flat_rows(payload.get("payment_ledger"), _PAYMENT_LEDGER_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = HOAStatementExtraction.model_validate(
            {
                **core_payload,
                "special_assessment_items": special_assessment_items,
                "payment_ledger": payment_ledger,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(
        non_null + len(special_assessment_items) + len(payment_ledger), coercion_lost
    )
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return HOAStatementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_hoa_statement(content: bytes, media_type: str) -> HOAStatementExtractionResult:
    """Extract HOA-statement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return HOAStatementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return HOAStatementExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="hoa_statement",
    )
    if call.text is None:
        return HOAStatementExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_hoa_statement_json(call.text)
    if result is None:
        logger.warning("hoa_statement_extraction_parse_failed")  # no raw response logged
        return HOAStatementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "hoa_statement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.special_assessment_items) + len(result.data.payment_ledger),
    )
    return result
