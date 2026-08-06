"""Retirement account extraction (LP-61) — Tier 1 asset, following the LP-39a shape.

A retirement statement (401(k) / IRA / pension) is an asset toward **reserves**.
Two balances matter and are tracked separately: ``total_balance`` and
``vested_balance`` — the **vested** figure is what the borrower can actually access
(early withdrawal of unvested funds isn't available; even vested funds carry
penalties), so it is the reserves-relevant number. Holdings, if itemized, land in
the grouped catch-all.

Mirrors :mod:`app.ai.extraction.bank_statement` (the closest template — masked
account, period, balances): typed core + ``additional_sections`` catch-all, Opus
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
    source_payload,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/retirement_account.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A 401(k)/IRA statement itemizes an UNBOUNDED holdings list (same shape as investment_account),
# each with a verbatim snippet → a long list = long JSON. 8192 like bank_statement so a dense fund
# list isn't truncated (LP-103). The LP-102 shared guard (model_call) is the backstop for overflow.
_MAX_TOKENS = 8192


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
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    retiree_or_account_owner_name_2: TypedField[str] = Field(default_factory=TypedField)
    statement_date: TypedField[date] = Field(default_factory=TypedField)
    vested_percentage: TypedField[Decimal] = Field(default_factory=TypedField)
    beginning_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    remaining_available_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    outstanding_loan_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    withdrawal_or_liquidation_terms: TypedField[str] = Field(default_factory=TypedField)
    gross_distribution_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    net_distribution_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    distribution_frequency: TypedField[str] = Field(default_factory=TypedField)
    distribution_date_or_schedule: TypedField[str] = Field(default_factory=TypedField)
    year_to_date_distributions: TypedField[Decimal] = Field(default_factory=TypedField)
    required_minimum_distribution_indicator: TypedField[str] = Field(default_factory=TypedField)
    fixed_period_or_lifetime_indicator: TypedField[str] = Field(default_factory=TypedField)
    scheduled_end_date: TypedField[date] = Field(default_factory=TypedField)

    # --- LP-460 diff — captured nested list(s) (bare rows) ------------------- #
    # The securities positions table (Positions - Equities / ETFs / Cash). No per-row account number -
    # the masked account number stays in its typed-core slot; a holdings row is symbol/qty/value only.
    holdings: list[dict[str, Any]] = Field(default_factory=list)

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
    # LP-446 diff additions
    ("retiree_or_account_owner_name_2", coerce_str),
    ("statement_date", coerce_date),
    ("vested_percentage", coerce_decimal),
    ("beginning_balance", coerce_decimal),
    ("remaining_available_balance", coerce_decimal),
    ("outstanding_loan_balance", coerce_decimal),
    ("withdrawal_or_liquidation_terms", coerce_str),
    ("gross_distribution_amount", coerce_decimal),
    ("net_distribution_amount", coerce_decimal),
    ("distribution_frequency", coerce_str),
    ("distribution_date_or_schedule", coerce_str),
    ("year_to_date_distributions", coerce_decimal),
    ("required_minimum_distribution_indicator", coerce_str),
    ("fixed_period_or_lifetime_indicator", coerce_str),
    ("scheduled_end_date", coerce_date),
)

# LP-460 — the holdings list: bare rows (mirrors bank_statement's transactions parse). Row values are read
# as strings by the snapshot, so each is kept verbatim (coerce_str) — an "N/A" yield or a blank cost basis
# is preserved rather than dropped by numeric coercion.
_HOLDINGS_ROW: CoreSpec = (
    ("symbol", coerce_str),
    ("description", coerce_str),
    ("quantity", coerce_str),
    ("price", coerce_str),
    ("market_value", coerce_str),
    ("cost_basis", coerce_str),
    ("unrealized_gain_loss", coerce_str),
)


def _parse_rows(raw: Any, row_spec: CoreSpec) -> list[dict[str, Any]]:
    """Coerce a bare-row list (each declared field coerced, a per-row page/snippet source kept, empty rows
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
    holdings = _parse_rows(payload.get("holdings"), _HOLDINGS_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = RetirementAccountExtraction.model_validate(
            {**core_payload, "holdings": holdings, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(holdings), coercion_lost)
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

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="retirement_account",
    )
    if call.text is None:
        return RetirementAccountExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_retirement_json(call.text)
    if result is None:
        logger.warning("retirement_account_extraction_parse_failed")  # no raw response logged
        return RetirementAccountExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values/account number.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "retirement_account_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.holdings),
    )
    return result
