"""Purchase agreement extraction (LP-62) — Tier 1 property, the LP-39a shape.

A purchase (sales) agreement is the contract to buy the **subject property**. Its
key figure is the **sales price** — the basis for LTV (and it cross-checks the
stated MISMO ``SalesContractAmount``). The typed core captures the parties, the
property, the price, and the closing/earnest-money terms; detailed contingencies
and other clauses land in the grouped catch-all.

Mirrors the existing extractors (e.g. :mod:`app.ai.extraction.w2`): typed core
(each a ``TypedField`` with source) + ``additional_sections`` catch-all, Sonnet
full-document reading, the shared tolerant parser, honest nulls, graceful
``.failed()``, metadata-only logging. Typed core is a **V1 starter — refine with
Priya**; accuracy is validated as real contracts flow through (no samples were
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

_PROMPT_PATH = "extraction/purchase_agreement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class PurchaseAgreementExtraction(BaseModel):
    """A purchase agreement in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — buyer/seller, the subject ``property_address``, ``sales_price``
    (the LTV basis), ``closing_date``, and ``earnest_money_amount``. **Grouped
    catch-all** — contingencies, financing terms, included items, addenda, etc.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    buyer_name: TypedField[str] = Field(default_factory=TypedField)
    seller_name: TypedField[str] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    sales_price: TypedField[Decimal] = Field(default_factory=TypedField)  # KEY — LTV basis
    closing_date: TypedField[date] = Field(default_factory=TypedField)
    earnest_money_amount: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else (contingencies, terms) --------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PurchaseAgreementExtractionResult(BaseModel):
    """A purchase-agreement extraction plus its outcome (mirrors the other results)."""

    data: PurchaseAgreementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PurchaseAgreementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PurchaseAgreementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("buyer_name", coerce_str),
    ("seller_name", coerce_str),
    ("property_address", coerce_str),
    ("sales_price", coerce_decimal),
    ("closing_date", coerce_date),
    ("earnest_money_amount", coerce_decimal),
)


def _parse_purchase_agreement_json(text: str) -> PurchaseAgreementExtractionResult | None:
    """Defensively parse a model response into a purchase-agreement result. Never raises."""
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
        data = PurchaseAgreementExtraction.model_validate(
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
    return PurchaseAgreementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_purchase_agreement(
    content: bytes, media_type: str
) -> PurchaseAgreementExtractionResult:
    """Extract purchase-agreement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PurchaseAgreementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PurchaseAgreementExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("purchase_agreement_extraction_ai_failed")  # metadata only
        return PurchaseAgreementExtractionResult.failed("AI call failed")

    result = _parse_purchase_agreement_json(resp.text)
    if result is None:
        logger.warning("purchase_agreement_extraction_parse_failed")  # no raw response logged
        return PurchaseAgreementExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "purchase_agreement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
