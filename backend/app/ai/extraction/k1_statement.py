"""K1 Statement extraction — GENERATED from a schema spec by the LP-434 generator.

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
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
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

_PROMPT_PATH = "extraction/k1_statement.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class K1StatementExtraction(BaseModel):
    """A k1 statement in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    source_form: TypedField[str] = Field(default_factory=TypedField)
    final_or_amended_k1: TypedField[str] = Field(default_factory=TypedField)
    entity_name: TypedField[str] = Field(default_factory=TypedField)
    entity_ein: TypedField[str] = Field(default_factory=TypedField)
    entity_address: TypedField[str] = Field(default_factory=TypedField)
    partner_or_shareholder_name: TypedField[str] = Field(default_factory=TypedField)
    partner_or_shareholder_tin: TypedField[str] = Field(default_factory=TypedField)
    partner_or_shareholder_address: TypedField[str] = Field(default_factory=TypedField)
    partner_type_or_shareholder_status: TypedField[str] = Field(default_factory=TypedField)
    profit_loss_capital_or_ownership_percentages: TypedField[str] = Field(
        default_factory=TypedField
    )
    current_year_net_income_or_loss: TypedField[Decimal] = Field(default_factory=TypedField)
    capital_account_ending: TypedField[Decimal] = Field(default_factory=TypedField)
    withdrawals_and_distributions: TypedField[Decimal] = Field(default_factory=TypedField)
    guaranteed_payments: TypedField[Decimal] = Field(default_factory=TypedField)
    distributions: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    k1_box_items: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class K1StatementExtractionResult(BaseModel):
    """A k1 statement extraction plus its outcome (mirrors the other extractor results)."""

    data: K1StatementExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "K1StatementExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=K1StatementExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("tax_year", coerce_int),
    ("source_form", coerce_str),
    ("final_or_amended_k1", coerce_str),
    ("entity_name", coerce_str),
    ("entity_ein", coerce_str),
    ("entity_address", coerce_str),
    ("partner_or_shareholder_name", coerce_str),
    ("partner_or_shareholder_tin", coerce_str),
    ("partner_or_shareholder_address", coerce_str),
    ("partner_type_or_shareholder_status", coerce_str),
    ("profit_loss_capital_or_ownership_percentages", coerce_str),
    ("current_year_net_income_or_loss", coerce_decimal),
    ("capital_account_ending", coerce_decimal),
    ("withdrawals_and_distributions", coerce_decimal),
    ("guaranteed_payments", coerce_decimal),
    ("distributions", coerce_decimal),
)


_K1_BOX_ITEMS_ROW: CoreSpec = (
    ("box_number", coerce_str),
    ("box_label", coerce_str),
    ("amount", coerce_decimal),
    ("code", coerce_str),
    ("source", coerce_str),
)


def _parse_k1_box_items(raw: Any) -> list[dict[str, Any]]:
    """Coerce the k1_box_items rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {name: coerce(entry.get(name)) for name, coerce in _K1_BOX_ITEMS_ROW}
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _K1_BOX_ITEMS_ROW):
            rows.append(row)
    return rows


def _parse_k1_statement_json(text: str) -> K1StatementExtractionResult | None:
    """Defensively parse a model response into a k1 statement result. Never raises."""
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
    k1_box_items = _parse_k1_box_items(payload.get("k1_box_items"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = K1StatementExtraction.model_validate(
            {**core_payload, "k1_box_items": k1_box_items, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(k1_box_items), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return K1StatementExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_k1_statement(content: bytes, media_type: str) -> K1StatementExtractionResult:
    """Extract k1 statement values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return K1StatementExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return K1StatementExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="k1_statement",
    )
    if call.text is None:
        return K1StatementExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_k1_statement_json(call.text)
    if result is None:
        logger.warning("k1_statement_extraction_parse_failed")  # no raw response logged
        return K1StatementExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "k1_statement_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.k1_box_items),
    )
    return result
