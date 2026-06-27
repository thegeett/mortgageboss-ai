"""Mortgage statement extraction (LP-62) — Tier 1 property, the LP-39a shape.

A mortgage statement documents an **existing mortgage obligation** — typically on
another property the borrower owns (it could also be the subject property on a
refinance). Its ``monthly_payment`` is a DTI obligation and it cross-checks the
stated MISMO mortgage liabilities. **The ``property_address`` is captured** so
Phase 3 can match subject-vs-other — this extractor only captures the address;
Phase 3 decides which property it is.

Mirrors the existing extractors: typed core + ``additional_sections`` catch-all,
Sonnet full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging. Typed core is a **V1 starter — refine with
Priya**; accuracy is validated as real statements flow through (no samples).
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
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
from app.core.config import settings
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/mortgage_statement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class MortgageStatementExtraction(BaseModel):
    """A mortgage statement in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the lender, the ``property_address`` (captured for Phase 3
    subject-vs-other matching), ``monthly_payment`` (a DTI obligation),
    ``unpaid_balance``, ``escrow_amount``, and the ``due_date``. **Grouped catch-all**
    — principal/interest split, past-due/late info, year-to-date, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    lender_name: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)  # subject-vs-other: P3
    monthly_payment: TypedField[Decimal] = Field(default_factory=TypedField)  # DTI obligation
    unpaid_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    escrow_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    due_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class MortgageStatementExtractionResult(BaseModel):
    """A mortgage-statement extraction plus its outcome (mirrors the other results)."""

    data: MortgageStatementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "MortgageStatementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=MortgageStatementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("lender_name", coerce_str),
    ("property_address", coerce_str),
    ("monthly_payment", coerce_decimal),
    ("unpaid_balance", coerce_decimal),
    ("escrow_amount", coerce_decimal),
    ("due_date", coerce_date),
)


def _parse_mortgage_statement_json(text: str) -> MortgageStatementExtractionResult | None:
    """Defensively parse a model response into a mortgage-statement result. Never raises."""
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
        data = MortgageStatementExtraction.model_validate(
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
    return MortgageStatementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_mortgage_statement(
    content: bytes, media_type: str
) -> MortgageStatementExtractionResult:
    """Extract mortgage-statement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return MortgageStatementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return MortgageStatementExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("mortgage_statement_extraction_ai_failed")  # metadata only
        return MortgageStatementExtractionResult.failed("AI call failed")

    result = _parse_mortgage_statement_json(resp.text)
    if result is None:
        logger.warning("mortgage_statement_extraction_parse_failed")  # no raw response logged
        return MortgageStatementExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "mortgage_statement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
