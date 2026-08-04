"""Statement Of Account extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/statement_of_account.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 8192 (guide §7 sizing rule; 1 nested list(s)).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 8192


class StatementOfAccountExtraction(BaseModel):
    """A statement of account in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    creditor_or_servicer_name: TypedField[str] = Field(default_factory=TypedField)
    customer_or_debtor_name: TypedField[str] = Field(default_factory=TypedField)
    customer_or_debtor_name_2: TypedField[str] = Field(default_factory=TypedField)
    customer_or_debtor_count: TypedField[int] = Field(default_factory=TypedField)
    account_number_masked: TypedField[str] = Field(default_factory=TypedField)
    account_type: TypedField[str] = Field(default_factory=TypedField)
    statement_date: TypedField[date] = Field(default_factory=TypedField)
    statement_period_start: TypedField[date] = Field(default_factory=TypedField)
    statement_period_end: TypedField[date] = Field(default_factory=TypedField)
    previous_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    current_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    minimum_or_scheduled_payment: TypedField[Decimal] = Field(default_factory=TypedField)
    payment_due_date: TypedField[date] = Field(default_factory=TypedField)
    past_due_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    days_past_due: TypedField[int] = Field(default_factory=TypedField)
    delinquency_or_collection_stage: TypedField[str] = Field(default_factory=TypedField)
    current_account_status: TypedField[str] = Field(default_factory=TypedField)
    credit_limit_or_original_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payoff_or_settlement_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    payoff_good_through_date: TypedField[date] = Field(default_factory=TypedField)
    property_address: TypedField[str] = Field(default_factory=TypedField)
    loan_number: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    transactions_or_activity: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class StatementOfAccountExtractionResult(BaseModel):
    """A statement of account extraction plus its outcome (mirrors the other extractor results)."""

    data: StatementOfAccountExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "StatementOfAccountExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=StatementOfAccountExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("creditor_or_servicer_name", coerce_str),
    ("customer_or_debtor_name", coerce_str),
    ("customer_or_debtor_name_2", coerce_str),
    ("customer_or_debtor_count", coerce_int),
    ("account_number_masked", coerce_str),
    ("account_type", coerce_str),
    ("statement_date", coerce_date),
    ("statement_period_start", coerce_date),
    ("statement_period_end", coerce_date),
    ("previous_balance", coerce_decimal),
    ("current_balance", coerce_decimal),
    ("minimum_or_scheduled_payment", coerce_decimal),
    ("payment_due_date", coerce_date),
    ("past_due_amount", coerce_decimal),
    ("days_past_due", coerce_int),
    ("delinquency_or_collection_stage", coerce_str),
    ("current_account_status", coerce_str),
    ("credit_limit_or_original_amount", coerce_decimal),
    ("payoff_or_settlement_amount", coerce_decimal),
    ("payoff_good_through_date", coerce_date),
    ("property_address", coerce_str),
    ("loan_number", coerce_str),
)


_TRANSACTIONS_OR_ACTIVITY_ROW: CoreSpec = (
    ("date", coerce_date),
    ("description", coerce_str),
    ("amount", coerce_decimal),
    ("type", coerce_str),
    ("running_balance", coerce_decimal),
)


def _parse_transactions_or_activity(raw: Any) -> list[dict[str, Any]]:
    """Coerce the transactions_or_activity rows — bare scalars + a per-row page/snippet source (LP-443 capture).

    Mirrors bank_statement's transactions parse: each declared field is coerced, a per-row source is
    kept, and a fully-empty row is dropped (no hallucinated rows)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {
            name: coerce(entry.get(name)) for name, coerce in _TRANSACTIONS_OR_ACTIVITY_ROW
        }
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in _TRANSACTIONS_OR_ACTIVITY_ROW):
            rows.append(row)
    return rows


def _parse_statement_of_account_json(text: str) -> StatementOfAccountExtractionResult | None:
    """Defensively parse a model response into a statement of account result. Never raises."""
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
    transactions_or_activity = _parse_transactions_or_activity(
        payload.get("transactions_or_activity")
    )
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = StatementOfAccountExtraction.model_validate(
            {
                **core_payload,
                "transactions_or_activity": transactions_or_activity,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(transactions_or_activity), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return StatementOfAccountExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_statement_of_account(
    content: bytes, media_type: str
) -> StatementOfAccountExtractionResult:
    """Extract statement of account values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return StatementOfAccountExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return StatementOfAccountExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="statement_of_account",
    )
    if call.text is None:
        return StatementOfAccountExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_statement_of_account_json(call.text)
    if result is None:
        logger.warning("statement_of_account_extraction_parse_failed")  # no raw response logged
        return StatementOfAccountExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "statement_of_account_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.transactions_or_activity),
    )
    return result
