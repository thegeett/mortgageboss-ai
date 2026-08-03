"""Purchase agreement extraction (LP-62) — Tier 1 property, the LP-39a shape.

A purchase (sales) agreement is the contract to buy the **subject property**. Its
key figure is the **sales price** — the basis for LTV (and it cross-checks the
stated MISMO ``SalesContractAmount``). The typed core captures the parties, the
property, the price, and the closing/earnest-money terms; detailed contingencies
and other clauses land in the grouped catch-all.

Mirrors the existing extractors (e.g. :mod:`app.ai.extraction.w2`): typed core
(each a ``TypedField`` with source) + ``additional_sections`` catch-all, Opus
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

_PROMPT_PATH = "extraction/purchase_agreement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A purchase contract carries a SEMI-UNBOUNDED set of terms (contingencies, concessions, addenda,
# dates), each with a verbatim snippet → a long list = long JSON on a heavily-amended deal. LP-446
# added TWO nested lists (addenda + contingencies) → the ≥2-nested-list tier of the sizing rule
# (16384), matching every other 2+-list type. The LP-102 shared guard (model_call) still backstops
# any overflow.
_MAX_TOKENS = 16384


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
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    buyer_name_2: TypedField[str] = Field(default_factory=TypedField)
    buyer_names_raw: TypedField[str] = Field(default_factory=TypedField)
    buyer_count: TypedField[int] = Field(default_factory=TypedField)
    seller_name_2: TypedField[str] = Field(default_factory=TypedField)
    seller_names_raw: TypedField[str] = Field(default_factory=TypedField)
    seller_count: TypedField[int] = Field(default_factory=TypedField)
    parties_relationship_disclosed: TypedField[str] = Field(default_factory=TypedField)
    listing_agent_name: TypedField[str] = Field(default_factory=TypedField)
    selling_agent_name: TypedField[str] = Field(default_factory=TypedField)
    legal_description: TypedField[str] = Field(default_factory=TypedField)
    property_type: TypedField[str] = Field(default_factory=TypedField)
    hoa_indicator: TypedField[str] = Field(default_factory=TypedField)
    hoa_dues_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    annual_property_tax: TypedField[Decimal] = Field(default_factory=TypedField)
    earnest_money_due_date: TypedField[date] = Field(default_factory=TypedField)
    earnest_money_holder: TypedField[str] = Field(default_factory=TypedField)
    seller_credit_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    seller_credit_purpose: TypedField[str] = Field(default_factory=TypedField)
    other_concessions_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    down_payment_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    loan_amount_stated: TypedField[Decimal] = Field(default_factory=TypedField)
    contract_date: TypedField[date] = Field(default_factory=TypedField)
    contract_expiration_date: TypedField[date] = Field(default_factory=TypedField)
    all_parties_signed: TypedField[str] = Field(default_factory=TypedField)
    personal_property_included: TypedField[str] = Field(default_factory=TypedField)
    personal_property_value: TypedField[Decimal] = Field(default_factory=TypedField)
    side_agreements_referenced: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-446 diff — captured nested list(s) (bare rows) --------------------- #
    addenda: list[dict[str, Any]] = Field(default_factory=list)
    contingencies: list[dict[str, Any]] = Field(default_factory=list)

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
    # LP-446 diff additions
    ("buyer_name_2", coerce_str),
    ("buyer_names_raw", coerce_str),
    ("buyer_count", coerce_int),
    ("seller_name_2", coerce_str),
    ("seller_names_raw", coerce_str),
    ("seller_count", coerce_int),
    ("parties_relationship_disclosed", coerce_str),
    ("listing_agent_name", coerce_str),
    ("selling_agent_name", coerce_str),
    ("legal_description", coerce_str),
    ("property_type", coerce_str),
    ("hoa_indicator", coerce_str),
    ("hoa_dues_amount", coerce_decimal),
    ("annual_property_tax", coerce_decimal),
    ("earnest_money_due_date", coerce_date),
    ("earnest_money_holder", coerce_str),
    ("seller_credit_amount", coerce_decimal),
    ("seller_credit_purpose", coerce_str),
    ("other_concessions_amount", coerce_decimal),
    ("down_payment_amount", coerce_decimal),
    ("loan_amount_stated", coerce_decimal),
    ("contract_date", coerce_date),
    ("contract_expiration_date", coerce_date),
    ("all_parties_signed", coerce_str),
    ("personal_property_included", coerce_str),
    ("personal_property_value", coerce_decimal),
    ("side_agreements_referenced", coerce_str),
)

_ADDENDA_ROW: CoreSpec = (
    ("addendum_name", coerce_str),
    ("addendum_type", coerce_str),
    ("addendum_date", coerce_str),
    ("is_signed", coerce_str),
    ("is_attached", coerce_str),
)
_CONTINGENCIES_ROW: CoreSpec = (
    ("contingency_type", coerce_str),
    ("deadline_date", coerce_str),
    ("is_waived", coerce_str),
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
    addenda = _parse_rows(payload.get("addenda"), _ADDENDA_ROW)
    contingencies = _parse_rows(payload.get("contingencies"), _CONTINGENCIES_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = PurchaseAgreementExtraction.model_validate(
            {
                **core_payload,
                "addenda": addenda,
                "contingencies": contingencies,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(addenda) + len(contingencies), coercion_lost)
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

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="purchase_agreement",
    )
    if call.text is None:
        return PurchaseAgreementExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_purchase_agreement_json(call.text)
    if result is None:
        logger.warning("purchase_agreement_extraction_parse_failed")  # no raw response logged
        return PurchaseAgreementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

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
