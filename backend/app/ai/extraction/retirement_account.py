"""Retirement account extraction (LP-61) — Tier 1 asset, following the LP-39a shape.

A retirement statement (401(k) / IRA / pension) is an asset toward **reserves**.
Two balances matter and are tracked separately: ``total_balance`` and
``vested_balance`` — the **vested** figure is what the borrower can actually access
(early withdrawal of unvested funds isn't available; even vested funds carry
penalties), so it is the reserves-relevant number. Holdings, if itemized, land in
the grouped catch-all.

Mirrors :mod:`app.ai.extraction.bank_statement` (the closest template — masked
account, period, balances): typed core + ``additional_sections`` catch-all, Sonnet
full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging.

**Account number (ADR-149).** ``account_number_masked`` is masked (last 4), never
logged, displayed masked. Typed core is a **V1 starter — refine with Priya**;
accuracy is validated as real statements flow through (no samples were available).
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

_PROMPT_PATH = "extraction/retirement_account.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class RetirementAccountExtraction(BaseModel):
    """A retirement statement in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — institution + holder + masked account + account type + period
    + ``vested_balance`` (the accessible/reserves figure) + ``total_balance``.
    **Grouped catch-all** — holdings, contributions, employer match, loan balances,
    vesting schedule, etc. — nothing lost.

    ``account_number_masked`` is **sensitive** — never logged; masked in display.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    institution_name: TypedField[str] = Field(default_factory=TypedField)
    account_holder: TypedField[str] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    account_type: TypedField[str] = Field(default_factory=TypedField)  # 401k / IRA / pension / ...
    statement_period_start: TypedField[date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[date] = Field(default_factory=TypedField)
    vested_balance: TypedField[Decimal] = Field(default_factory=TypedField)  # accessible figure
    total_balance: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class RetirementAccountExtractionResult(BaseModel):
    """A retirement-account extraction plus its outcome (mirrors the other results)."""

    data: RetirementAccountExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "RetirementAccountExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=RetirementAccountExtraction(),
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
    ("vested_balance", coerce_decimal),
    ("total_balance", coerce_decimal),
)


def _parse_retirement_json(text: str) -> RetirementAccountExtractionResult | None:
    """Defensively parse a model response into a retirement result. Never raises."""
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
        data = RetirementAccountExtraction.model_validate(
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
    return RetirementAccountExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_retirement_account(
    content: bytes, media_type: str
) -> RetirementAccountExtractionResult:
    """Extract retirement-account values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.bank_statement.extract_bank_statement`. The
    bytes/base64, raw response, extracted values, and the **account number** are
    never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return RetirementAccountExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return RetirementAccountExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("retirement_account_extraction_ai_failed")  # metadata only
        return RetirementAccountExtractionResult.failed("AI call failed")

    result = _parse_retirement_json(resp.text)
    if result is None:
        logger.warning("retirement_account_extraction_parse_failed")  # no raw response logged
        return RetirementAccountExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values/account number.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "retirement_account_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
