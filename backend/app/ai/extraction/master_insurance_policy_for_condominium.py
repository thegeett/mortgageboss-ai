"""Master Insurance Policy For Condominium extraction — GENERATED from a schema spec by the LP-434 generator.

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

_PROMPT_PATH = "extraction/master_insurance_policy_for_condominium.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Unbounded list output → 16384 (guide §7 sizing rule; 2 nested list(s) — building_limits + coverage_lines).
# The test_extraction_budget_sizing CI guard enforces the sizing rule (derived from the spec's list count).
_MAX_TOKENS = 16384


class MasterInsurancePolicyForCondominiumExtraction(BaseModel):
    """A master insurance policy for condominium in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    association_or_named_insured: TypedField[str] = Field(default_factory=TypedField)
    condominium_project_name: TypedField[str] = Field(default_factory=TypedField)
    insurance_carrier: TypedField[str] = Field(default_factory=TypedField)
    policy_number: TypedField[str] = Field(default_factory=TypedField)
    policy_form_and_coverage_basis: TypedField[str] = Field(default_factory=TypedField)
    effective_date: TypedField[date] = Field(default_factory=TypedField)
    expiration_date: TypedField[date] = Field(default_factory=TypedField)
    blanket_or_scheduled_coverage: TypedField[str] = Field(default_factory=TypedField)
    replacement_cost_indicator: TypedField[str] = Field(default_factory=TypedField)
    coinsurance_percentage: TypedField[str] = Field(default_factory=TypedField)
    walls_in_bare_walls_or_single_entity_scope: TypedField[str] = Field(default_factory=TypedField)
    water_damage_or_master_policy_exclusions: TypedField[str] = Field(default_factory=TypedField)
    general_liability_each_occurrence_limit: TypedField[Decimal] = Field(default_factory=TypedField)
    fidelity_crime_coverage_present: TypedField[str] = Field(default_factory=TypedField)
    fidelity_crime_coverage_amount: TypedField[Decimal] = Field(default_factory=TypedField)
    flood_coverage_present: TypedField[str] = Field(default_factory=TypedField)
    agent_contact_and_certificate_date: TypedField[str] = Field(default_factory=TypedField)

    # --- Captured nested lists (LP-443) — bare rows, snapshot-read generically ------- #
    building_limits: list[dict[str, Any]] = Field(default_factory=list)
    # --- LP-460 diff — the coverage lines of the master policy. On an ACORD 24/25 cert these are the
    # TYPE-OF-INSURANCE rows (Property / Crime-Fidelity / Boiler & Machinery / General Liability) — coverage
    # LINES of one policy, not separate policies (they share one policy number). ----------------------- #
    coverage_lines: list[dict[str, Any]] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class MasterInsurancePolicyForCondominiumExtractionResult(BaseModel):
    """A master insurance policy for condominium extraction plus its outcome (mirrors the other extractor results)."""

    data: MasterInsurancePolicyForCondominiumExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "MasterInsurancePolicyForCondominiumExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=MasterInsurancePolicyForCondominiumExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("association_or_named_insured", coerce_str),
    ("condominium_project_name", coerce_str),
    ("insurance_carrier", coerce_str),
    ("policy_number", coerce_str),
    ("policy_form_and_coverage_basis", coerce_str),
    ("effective_date", coerce_date),
    ("expiration_date", coerce_date),
    ("blanket_or_scheduled_coverage", coerce_str),
    ("replacement_cost_indicator", coerce_str),
    ("coinsurance_percentage", coerce_str),
    ("walls_in_bare_walls_or_single_entity_scope", coerce_str),
    ("water_damage_or_master_policy_exclusions", coerce_str),
    ("general_liability_each_occurrence_limit", coerce_decimal),
    ("fidelity_crime_coverage_present", coerce_str),
    ("fidelity_crime_coverage_amount", coerce_decimal),
    ("flood_coverage_present", coerce_str),
    ("agent_contact_and_certificate_date", coerce_str),
)


_BUILDING_LIMITS_ROW: CoreSpec = (
    ("building_identifier_or_address", coerce_str),
    ("coverage_limit", coerce_decimal),
    ("deductible", coerce_decimal),
    ("wind_hail_named_storm_deductible", coerce_str),
    ("source", coerce_str),
)

# LP-460 — the master policy's coverage LINES (one row per TYPE OF INSURANCE on the cert: Property, Crime /
# Fidelity, Boiler & Machinery, General Liability, …). ``policy_number`` is captured per row for the
# multi-insurer ACORD case; the master prompt masks it, mirroring the typed-core policy_number.
_COVERAGE_LINES_ROW: CoreSpec = (
    ("type_of_insurance", coerce_str),
    ("policy_number", coerce_str),
    ("limit", coerce_decimal),
    ("deductible", coerce_decimal),
    ("causes_of_loss", coerce_str),
)


def _parse_rows(raw: Any, row_spec: CoreSpec) -> list[dict[str, Any]]:
    """Coerce a bare-row list — each declared field coerced, a per-row page/snippet source kept, a
    fully-empty row dropped (no hallucinated rows). Mirrors bank_statement's transactions parse."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {name: coerce(entry.get(name)) for name, coerce in row_spec}
        if (
            "source" not in row
        ):  # never clobber a declared 'source' data field; else keep provenance
            row["source"] = source_payload(entry)
        if any(row[name] is not None for name, _ in row_spec):
            rows.append(row)
    return rows


def _parse_building_limits(raw: Any) -> list[dict[str, Any]]:
    """Coerce the building_limits rows (LP-443 capture) via the shared bare-row parser."""
    return _parse_rows(raw, _BUILDING_LIMITS_ROW)


def _parse_master_insurance_policy_for_condominium_json(
    text: str,
) -> MasterInsurancePolicyForCondominiumExtractionResult | None:
    """Defensively parse a model response into a master insurance policy for condominium result. Never raises."""
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
    building_limits = _parse_building_limits(payload.get("building_limits"))
    coverage_lines = _parse_rows(payload.get("coverage_lines"), _COVERAGE_LINES_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = MasterInsurancePolicyForCondominiumExtraction.model_validate(
            {
                **core_payload,
                "building_limits": building_limits,
                "coverage_lines": coverage_lines,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(building_limits) + len(coverage_lines), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return MasterInsurancePolicyForCondominiumExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_master_insurance_policy_for_condominium(
    content: bytes, media_type: str
) -> MasterInsurancePolicyForCondominiumExtractionResult:
    """Extract master insurance policy for condominium values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return MasterInsurancePolicyForCondominiumExtractionResult.failed(
            "empty or unsupported document"
        )

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return MasterInsurancePolicyForCondominiumExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="master_insurance_policy_for_condominium",
    )
    if call.text is None:
        return MasterInsurancePolicyForCondominiumExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_master_insurance_policy_for_condominium_json(call.text)
    if result is None:
        logger.warning(
            "master_insurance_policy_for_condominium_extraction_parse_failed"
        )  # no raw response logged
        return MasterInsurancePolicyForCondominiumExtractionResult.failed(
            "could not parse extraction"
        )

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "master_insurance_policy_for_condominium_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        list_rows_total=len(result.data.building_limits) + len(result.data.coverage_lines),
    )
    return result
