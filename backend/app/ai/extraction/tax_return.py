"""Tax return extraction (LP-64) — the hardest Tier 1 extractor: a NESTED bundle.

A "tax return" is not one form — it is **Form 1040 + a variable set of schedules**
(Schedule C self-employment, Schedule E rental/supplemental, K-1 partnership/S-corp
share, plus B/D/1/2/3 and attachments). WHICH schedules are present depends on the
borrower. So this extends the LP-39a shape into a **nested** one:

    1040 typed core
      + typed income-critical schedule sub-structures (present-or-null, repeatable):
          schedule_c[]   (self-employment — THE heart)
          schedule_e     (rental — with a properties[] list)
          k1s[]          (partnership/S-corp share)
      + grouped catch-all (other schedules B/D/1/2/3, attachments, anything else)

**The self-employed case is the point.** For a W-2 employee the return is largely
redundant (income is on the pay stubs / W-2s); for a **self-employed** borrower the
tax return is THE primary income document — Schedule C ``net_profit`` is the
qualifying-income figure. Schedule C extraction is the high-value heart.

This **captures the figures**; Phase 3 derives qualifying income from them (the
income math + the two-year comparison) — not here. Type the income-critical
schedules; catch-all the rest. The result interface is the **same** as every other
extractor (``data`` / ``status`` / ``confidence`` / ``.failed()``), so the pipeline
+ ``create_extraction_version`` handle the nested data uniformly.

**PII (ADR-147).** The taxpayer SSN is captured **masked** (last 4) and **never
logged** — tax returns are among the most sensitive documents; metadata-only
logging, no return values in logs.

**Accuracy — read this honestly.** A tax return is the most varied, multi-schedule
document of any extractor here. With **no real sample returns available** when this
was built, the tests verify the **nested mechanism/shape** (the 1040 core + the
present-or-null + repeatable schedules + Schedule C ``net_profit`` + the catch-all +
graceful failure) — **NOT** extraction accuracy against real returns. A
multi-schedule extractor tested only against constructed inputs is **especially
unproven**; accuracy must be validated against real (synthetic/redacted)
self-employed returns over time and the field set refined with Priya.
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
    coerce_int,
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

_PROMPT_PATH = "extraction/tax_return.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A tax return is a multi-page, multi-schedule BUNDLE — the most content of any
# extractor. Budget generously so the schedules aren't truncated; a truncated /
# malformed response still fails gracefully (``.failed()``).
_MAX_TOKENS = 16384


# --------------------------------------------------------------------------- #
# Typed schedule sub-structures (each field a TypedField with source)
# --------------------------------------------------------------------------- #


class ScheduleC(BaseModel):
    """One Schedule C (self-employment business). ``net_profit`` is the KEY figure."""

    business_name: TypedField[str] = Field(default_factory=TypedField)
    gross_receipts: TypedField[Decimal] = Field(default_factory=TypedField)
    total_expenses: TypedField[Decimal] = Field(default_factory=TypedField)
    net_profit: TypedField[Decimal] = Field(default_factory=TypedField)  # the self-employment heart


class ScheduleEProperty(BaseModel):
    """One rental property on Schedule E."""

    address: TypedField[str] = Field(default_factory=TypedField)
    rents_received: TypedField[Decimal] = Field(default_factory=TypedField)
    total_expenses: TypedField[Decimal] = Field(default_factory=TypedField)
    net_income: TypedField[Decimal] = Field(default_factory=TypedField)


class ScheduleE(BaseModel):
    """Schedule E (rental / supplemental income) — a properties list + totals."""

    properties: list[ScheduleEProperty] = Field(default_factory=list)
    total_net_rental_income: TypedField[Decimal] = Field(default_factory=TypedField)
    depreciation: TypedField[Decimal] = Field(default_factory=TypedField)  # added back in P3


class K1(BaseModel):
    """One Schedule K-1 (partner's / shareholder's share of an entity)."""

    entity_name: TypedField[str] = Field(default_factory=TypedField)
    ownership_pct: TypedField[Decimal] = Field(default_factory=TypedField)
    ordinary_income: TypedField[Decimal] = Field(default_factory=TypedField)


class TaxReturnExtraction(BaseModel):
    """A tax return: a 1040 typed core + typed income-critical schedules + catch-all.

    **1040 core** — the essential return figures (year, filing status, parties,
    masked SSN, total/AGI/wages/taxable income). **Schedules** — the income-critical
    ones, present-or-null and repeatable: ``schedule_c`` (self-employment, a list),
    ``schedule_e`` (rental, with a ``properties`` list), ``k1s`` (a list).
    **Catch-all** — every other schedule (B/D/1/2/3), attachments, anything else.

    ``taxpayer_ssn_masked`` is **sensitive** — never logged; masked in display.
    """

    # --- 1040 core (value + source) ----------------------------------------- #
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    filing_status: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_names: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_ssn_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE — masked
    total_income: TypedField[Decimal] = Field(default_factory=TypedField)
    adjusted_gross_income: TypedField[Decimal] = Field(default_factory=TypedField)
    wages: TypedField[Decimal] = Field(default_factory=TypedField)
    taxable_income: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Typed income-critical schedules (present-or-null; repeatable lists) - #
    schedule_c: list[ScheduleC] = Field(default_factory=list)
    schedule_e: ScheduleE | None = None
    k1s: list[K1] = Field(default_factory=list)

    # --- Grouped catch-all — other schedules / attachments / everything else - #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class TaxReturnExtractionResult(BaseModel):
    """A tax-return extraction plus its outcome (mirrors the other result types)."""

    data: TaxReturnExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "TaxReturnExtractionResult":
        """The graceful fallback: empty data, ``FAILED``, zero confidence."""
        return cls(
            data=TaxReturnExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_1040_SPEC: CoreSpec = (
    ("tax_year", coerce_int),
    ("filing_status", coerce_str),
    ("taxpayer_names", coerce_str),
    ("taxpayer_ssn_masked", coerce_str),
    ("total_income", coerce_decimal),
    ("adjusted_gross_income", coerce_decimal),
    ("wages", coerce_decimal),
    ("taxable_income", coerce_decimal),
)
_SCHEDULE_C_SPEC: CoreSpec = (
    ("business_name", coerce_str),
    ("gross_receipts", coerce_decimal),
    ("total_expenses", coerce_decimal),
    ("net_profit", coerce_decimal),
)
_SCHEDULE_E_PROPERTY_SPEC: CoreSpec = (
    ("address", coerce_str),
    ("rents_received", coerce_decimal),
    ("total_expenses", coerce_decimal),
    ("net_income", coerce_decimal),
)
_SCHEDULE_E_SPEC: CoreSpec = (
    ("total_net_rental_income", coerce_decimal),
    ("depreciation", coerce_decimal),
)
_K1_SPEC: CoreSpec = (
    ("entity_name", coerce_str),
    ("ownership_pct", coerce_decimal),
    ("ordinary_income", coerce_decimal),
)


def _parse_schedule_list(raw: Any, spec: CoreSpec) -> tuple[list[dict[str, Any]], int, bool]:
    """Parse a list of repeatable schedule entries via the shared typed-core parser.

    Each entry is coerced through ``parse_typed_core`` (so every field becomes
    ``{value, source}``). A fully-empty entry (no field read) is dropped — no
    hallucinated schedules. Returns ``(rows, non_null_total, coercion_lost)``.
    """
    rows: list[dict[str, Any]] = []
    total_non_null = 0
    coercion_lost = False
    if not isinstance(raw, list):
        return rows, total_non_null, coercion_lost
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        core_payload, non_null, lost = parse_typed_core(entry, spec)
        coercion_lost = coercion_lost or lost
        if non_null > 0:  # keep only entries with at least one read value
            rows.append(core_payload)
            total_non_null += non_null
    return rows, total_non_null, coercion_lost


def _parse_schedule_e(raw: Any) -> tuple[dict[str, Any] | None, int, bool]:
    """Parse the (present-or-null) Schedule E: scalar totals + a properties list."""
    if not isinstance(raw, dict):
        return None, 0, False
    props, prop_nn, prop_lost = _parse_schedule_list(
        raw.get("properties"), _SCHEDULE_E_PROPERTY_SPEC
    )
    core_payload, core_nn, core_lost = parse_typed_core(raw, _SCHEDULE_E_SPEC)
    non_null = prop_nn + core_nn
    if non_null == 0:
        return None, 0, prop_lost or core_lost  # nothing read → treat as absent
    return {**core_payload, "properties": props}, non_null, prop_lost or core_lost


def _parse_tax_return_json(text: str) -> TaxReturnExtractionResult | None:
    """Defensively parse a model response into the nested tax-return result. Never raises.

    Reads the 1040 ``typed_core`` + each schedule (``schedule_c`` / ``schedule_e`` /
    ``k1s``) + ``additional_sections``. Status is derived from the 1040 core AND the
    schedules (a self-employed return may be mostly its schedules). A truncated /
    malformed response → ``None`` (the caller fails gracefully).
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        payload: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    core_payload, core_nn, core_lost = parse_typed_core(payload, _CORE_1040_SPEC)
    sched_c, c_nn, c_lost = _parse_schedule_list(payload.get("schedule_c"), _SCHEDULE_C_SPEC)
    sched_e, e_nn, e_lost = _parse_schedule_e(payload.get("schedule_e"))
    k1s, k_nn, k_lost = _parse_schedule_list(payload.get("k1s"), _K1_SPEC)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = TaxReturnExtraction.model_validate(
            {
                **core_payload,
                "schedule_c": sched_c,
                "schedule_e": sched_e,
                "k1s": k1s,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    non_null = core_nn + c_nn + e_nn + k_nn
    coercion_lost = core_lost or c_lost or e_lost or k_lost
    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return TaxReturnExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_tax_return(content: bytes, media_type: str) -> TaxReturnExtractionResult:
    """Extract a nested tax return (1040 + schedules) from bytes (PDF/image). Never raises.

    Mirrors the other extractors: empty/unsupported → ``failed`` without an API
    call; otherwise loads the prompt, sends the full document to the Sonnet-class
    model with a **generous** token budget (multi-page bundle), and parses
    defensively (a truncated multi-schedule response → ``failed``). The bytes/base64,
    raw response, extracted values, and the **SSN** are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return TaxReturnExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return TaxReturnExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("tax_return_extraction_ai_failed")  # metadata only
        return TaxReturnExtractionResult.failed("AI call failed")

    result = _parse_tax_return_json(resp.text)
    if result is None:
        logger.warning("tax_return_extraction_parse_failed")  # truncated/malformed
        return TaxReturnExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata ONLY: status, confidence, COUNTS (which schedules, how many) — never
    # any value and never the SSN.
    core_present = sum(
        1 for key, _ in _CORE_1040_SPEC if getattr(result.data, key).value is not None
    )
    logger.info(
        "tax_return_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        schedule_c_count=len(result.data.schedule_c),
        schedule_e_present=result.data.schedule_e is not None,
        schedule_e_properties=(
            len(result.data.schedule_e.properties) if result.data.schedule_e else 0
        ),
        k1_count=len(result.data.k1s),
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
