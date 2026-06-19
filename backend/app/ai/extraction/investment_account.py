"""Investment account extraction (LP-61) — Tier 1 asset, following the LP-39a shape.

A brokerage/investment statement (stocks, bonds, funds) is a non-cash asset toward
**reserves** (the lender-required cushion). The decision figure is the account's
**total market value**; the individual holdings (if itemized) land in the grouped
catch-all — a flat typed core + catch-all, like the W-2, not the bank statement's
first-class transactions list.

Mirrors :mod:`app.ai.extraction.bank_statement` (the closest template — an asset
doc with a masked account number, a statement period, and balances): typed core
(each a ``TypedField`` with source) + ``additional_sections`` catch-all, Sonnet
full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging.

**Account number (ADR-149).** ``account_number_masked`` is captured masked (last 4),
**never logged**, and displayed masked. Typed core is a **V1 starter — refine with
Priya**; accuracy is validated as real statements flow through (no samples were
available when this was built).
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

_PROMPT_PATH = "extraction/investment_account.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class InvestmentAccountExtraction(BaseModel):
    """An investment statement in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the institution + holder + masked account + period +
    ``total_value`` (the reserves figure). **Grouped catch-all** — the individual
    holdings (ticker/shares/value), cost basis, gain/loss, etc. — nothing lost.

    ``account_number_masked`` is **sensitive** — never logged; masked in display.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    institution_name: TypedField[str] = Field(default_factory=TypedField)
    account_holder: TypedField[str] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    account_type: TypedField[str] = Field(default_factory=TypedField)  # brokerage / 529 / ...
    statement_period_start: TypedField[date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[date] = Field(default_factory=TypedField)
    total_value: TypedField[Decimal] = Field(default_factory=TypedField)  # KEY reserves figure

    # --- Grouped catch-all — everything else (holdings, etc.) --------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class InvestmentAccountExtractionResult(BaseModel):
    """An investment-account extraction plus its outcome (mirrors the other results)."""

    data: InvestmentAccountExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "InvestmentAccountExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=InvestmentAccountExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("institution_name", coerce_str),
    ("account_holder", coerce_str),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("statement_period_start", coerce_date),
    ("statement_period_end", coerce_date),
    ("total_value", coerce_decimal),
)


def _parse_investment_json(text: str) -> InvestmentAccountExtractionResult | None:
    """Defensively parse a model response into an investment result. Never raises."""
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
        data = InvestmentAccountExtraction.model_validate(
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
    return InvestmentAccountExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_investment_account(
    content: bytes, media_type: str
) -> InvestmentAccountExtractionResult:
    """Extract investment-account values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.bank_statement.extract_bank_statement`. The
    bytes/base64, raw response, extracted values, and the **account number** are
    never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return InvestmentAccountExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return InvestmentAccountExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("investment_account_extraction_ai_failed")  # metadata only
        return InvestmentAccountExtractionResult.failed("AI call failed")

    result = _parse_investment_json(resp.text)
    if result is None:
        logger.warning("investment_account_extraction_parse_failed")  # no raw response logged
        return InvestmentAccountExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values/account number.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "investment_account_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
