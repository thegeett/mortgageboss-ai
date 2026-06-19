"""Gift letter extraction (LP-61) — Tier 1 asset, attestation-oriented (LP-39a shape).

A gift letter documents that funds given to the borrower are a **genuine gift, not
a loan** — so the funds count toward assets and don't add an undisclosed debt. It
is attestation prose (closer to the LOE than to a financial statement), so the
typed core captures the parties + amount + the **no-repayment attestation** (the
statement that makes it a gift vs. a debt). Anything else (donor account/source of
funds, signatures, dates) lands in the grouped catch-all.

Mirrors the existing extractors for the result interface / graceful failure /
metadata-only logging. No account number is present (no masking needed here).
Typed core is a **V1 starter — refine with Priya**; accuracy is validated as real
gift letters flow through (no samples were available when this was built).
"""

import json
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.extraction.parsing import (
    CoreSpec,
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

_PROMPT_PATH = "extraction/gift_letter.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class GiftLetterExtraction(BaseModel):
    """A gift letter in the LP-39a shape: an attestation-oriented typed core + catch-all.

    **Typed core** — the donor (name + relationship to the borrower), the recipient
    (the borrower), the ``gift_amount``, the subject ``property_address``, and the
    ``no_repayment_attestation`` (the verbatim/closely-summarized statement that the
    funds are a gift with NO expectation of repayment — what distinguishes a gift
    from undisclosed debt). **Grouped catch-all** — donor account / source of funds,
    signatures, dates, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    donor_name: TypedField[str] = Field(default_factory=TypedField)
    donor_relationship: TypedField[str] = Field(default_factory=TypedField)  # to the borrower
    recipient_name: TypedField[str] = Field(default_factory=TypedField)  # the borrower
    gift_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    no_repayment_attestation: TypedField[str] = Field(default_factory=TypedField)  # gift vs. debt

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class GiftLetterExtractionResult(BaseModel):
    """A gift-letter extraction plus its outcome (mirrors the other results)."""

    data: GiftLetterExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "GiftLetterExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=GiftLetterExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("donor_name", coerce_str),
    ("donor_relationship", coerce_str),
    ("recipient_name", coerce_str),
    ("gift_amount", coerce_decimal),
    ("property_address", coerce_str),
    ("no_repayment_attestation", coerce_str),
)


def _parse_gift_letter_json(text: str) -> GiftLetterExtractionResult | None:
    """Defensively parse a model response into a gift-letter result. Never raises."""
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
        data = GiftLetterExtraction.model_validate(
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
    return GiftLetterExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_gift_letter(content: bytes, media_type: str) -> GiftLetterExtractionResult:
    """Extract gift-letter values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`. The bytes/base64, raw
    response, and extracted values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return GiftLetterExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return GiftLetterExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("gift_letter_extraction_ai_failed")  # metadata only
        return GiftLetterExtractionResult.failed("AI call failed")

    result = _parse_gift_letter_json(resp.text)
    if result is None:
        logger.warning("gift_letter_extraction_parse_failed")  # no raw response logged
        return GiftLetterExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "gift_letter_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
