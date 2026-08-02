"""Condo Questionnaire extraction — GENERATED from a schema spec by the LP-434 generator.

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
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/condo_questionnaire.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class CondoQuestionnaireExtraction(BaseModel):
    """A condo questionnaire in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    project_name: TypedField[str] = Field(default_factory=TypedField)
    project_address: TypedField[str] = Field(default_factory=TypedField)
    hoa_name: TypedField[str] = Field(default_factory=TypedField)
    management_company: TypedField[str] = Field(default_factory=TypedField)
    questionnaire_form_type: TypedField[str] = Field(default_factory=TypedField)
    completed_by_name: TypedField[str] = Field(default_factory=TypedField)
    completed_date: TypedField[date] = Field(default_factory=TypedField)
    is_signed: TypedField[str] = Field(default_factory=TypedField)
    total_units: TypedField[int] = Field(default_factory=TypedField)
    units_sold_and_closed: TypedField[int] = Field(default_factory=TypedField)
    owner_occupied_units: TypedField[int] = Field(default_factory=TypedField)
    owner_occupancy_percentage: TypedField[Decimal] = Field(default_factory=TypedField)
    investor_owned_units: TypedField[int] = Field(default_factory=TypedField)
    single_entity_owned_units: TypedField[int] = Field(default_factory=TypedField)
    single_entity_max_percentage: TypedField[Decimal] = Field(default_factory=TypedField)
    commercial_space_percentage: TypedField[Decimal] = Field(default_factory=TypedField)
    project_type: TypedField[str] = Field(default_factory=TypedField)
    is_project_complete: TypedField[str] = Field(default_factory=TypedField)
    hoa_dues_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    hoa_dues_frequency: TypedField[str] = Field(default_factory=TypedField)
    units_delinquent_over_60_days: TypedField[int] = Field(default_factory=TypedField)
    delinquency_percentage: TypedField[Decimal] = Field(default_factory=TypedField)
    annual_budget_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    reserve_fund_balance: TypedField[Decimal] = Field(default_factory=TypedField)
    reserve_contribution_percentage: TypedField[Decimal] = Field(default_factory=TypedField)
    special_assessment_indicator: TypedField[str] = Field(default_factory=TypedField)
    special_assessment_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    master_policy_carrier: TypedField[str] = Field(default_factory=TypedField)
    master_policy_number: TypedField[str] = Field(default_factory=TypedField)
    master_policy_coverage_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    master_policy_replacement_cost_basis: TypedField[str] = Field(default_factory=TypedField)
    fidelity_bond_indicator: TypedField[str] = Field(default_factory=TypedField)
    fidelity_bond_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    litigation_indicator: TypedField[str] = Field(default_factory=TypedField)
    litigation_description: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class CondoQuestionnaireExtractionResult(BaseModel):
    """A condo questionnaire extraction plus its outcome (mirrors the other extractor results)."""

    data: CondoQuestionnaireExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "CondoQuestionnaireExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=CondoQuestionnaireExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("project_name", coerce_str),
    ("project_address", coerce_str),
    ("hoa_name", coerce_str),
    ("management_company", coerce_str),
    ("questionnaire_form_type", coerce_str),
    ("completed_by_name", coerce_str),
    ("completed_date", coerce_date),
    ("is_signed", coerce_str),
    ("total_units", coerce_int),
    ("units_sold_and_closed", coerce_int),
    ("owner_occupied_units", coerce_int),
    ("owner_occupancy_percentage", coerce_decimal),
    ("investor_owned_units", coerce_int),
    ("single_entity_owned_units", coerce_int),
    ("single_entity_max_percentage", coerce_decimal),
    ("commercial_space_percentage", coerce_decimal),
    ("project_type", coerce_str),
    ("is_project_complete", coerce_str),
    ("hoa_dues_amount", coerce_decimal),
    ("hoa_dues_frequency", coerce_str),
    ("units_delinquent_over_60_days", coerce_int),
    ("delinquency_percentage", coerce_decimal),
    ("annual_budget_amount", coerce_decimal),
    ("reserve_fund_balance", coerce_decimal),
    ("reserve_contribution_percentage", coerce_decimal),
    ("special_assessment_indicator", coerce_str),
    ("special_assessment_amount", coerce_decimal),
    ("master_policy_carrier", coerce_str),
    ("master_policy_number", coerce_str),
    ("master_policy_coverage_amount", coerce_decimal),
    ("master_policy_replacement_cost_basis", coerce_str),
    ("fidelity_bond_indicator", coerce_str),
    ("fidelity_bond_amount", coerce_decimal),
    ("litigation_indicator", coerce_str),
    ("litigation_description", coerce_str),
)


def _parse_condo_questionnaire_json(text: str) -> CondoQuestionnaireExtractionResult | None:
    """Defensively parse a model response into a condo questionnaire result. Never raises."""
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
        data = CondoQuestionnaireExtraction.model_validate(
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
    return CondoQuestionnaireExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_condo_questionnaire(
    content: bytes, media_type: str
) -> CondoQuestionnaireExtractionResult:
    """Extract condo questionnaire values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return CondoQuestionnaireExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return CondoQuestionnaireExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="condo_questionnaire",
    )
    if call.text is None:
        return CondoQuestionnaireExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_condo_questionnaire_json(call.text)
    if result is None:
        logger.warning("condo_questionnaire_extraction_parse_failed")  # no raw response logged
        return CondoQuestionnaireExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "condo_questionnaire_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
