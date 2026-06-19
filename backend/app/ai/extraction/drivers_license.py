"""Driver's license / government ID extraction (LP-63) — Tier 1, the LP-39a shape.

A driver's license (or other government ID) is the **most identity-dense document**
in the product — lenders verify identity (KYC / USA PATRIOT Act). The typed core
captures the identity fields (name, DOB, address, masked ID number, issuing
state/authority) plus the **expiration date** (an expired ID is invalid → feeds
staleness, LP-71). Anything else (class, endorsements, height/eye color, etc.)
lands in the grouped catch-all.

**HEIGHTENED PII (the W-2 SSN discipline, ADR-147 — generalized).** The whole
document is PII. ``id_number_masked`` is captured **masked** (last 4) and the
``date_of_birth`` is captured for the Phase 3 identity cross-check — but **NO
extracted value is ever logged** (only status / confidence / counts), and the raw
values live only in the tenant-scoped extraction JSON (the ID number masked, the
DOB masked in display). This is the strictest no-logging discipline in the codebase.

Mirrors :mod:`app.ai.extraction.w2`: typed core + ``additional_sections`` catch-all,
the shared tolerant parser, honest nulls, graceful ``.failed()``. Typed core is a
**V1 starter — refine with Priya**; accuracy is validated as real (SYNTHETIC /
redacted — never real) IDs flow through (no samples were available when this was built).
"""

import json
from datetime import date
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.extraction.parsing import (
    CoreSpec,
    coerce_date,
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

_PROMPT_PATH = "extraction/drivers_license.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 2048


class DriversLicenseExtraction(BaseModel):
    """A government ID in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — ``full_name``, ``date_of_birth`` (SENSITIVE), ``address``,
    ``id_number_masked`` (SENSITIVE — masked), ``issuing_state``,
    ``issuing_authority``, and ``expiration_date`` (validity / staleness). **Grouped
    catch-all** — license class, endorsements/restrictions, physical descriptors, etc.

    The entire document is PII. ``id_number_masked`` and ``date_of_birth`` are
    **never logged**; the ID number is masked, the DOB is masked in display.
    """

    # --- Typed core (value + source) — HIGHLY sensitive --------------------- #
    full_name: TypedField[str] = Field(default_factory=TypedField)
    date_of_birth: TypedField[date] = Field(default_factory=TypedField)  # SENSITIVE
    address: TypedField[str] = Field(default_factory=TypedField)
    id_number_masked: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE — masked
    issuing_state: TypedField[str] = Field(default_factory=TypedField)
    issuing_authority: TypedField[str] = Field(default_factory=TypedField)
    expiration_date: TypedField[date] = Field(default_factory=TypedField)  # expired = invalid

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class DriversLicenseExtractionResult(BaseModel):
    """A driver's-license extraction plus its outcome (mirrors the other results)."""

    data: DriversLicenseExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "DriversLicenseExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=DriversLicenseExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("full_name", coerce_str),
    ("date_of_birth", coerce_date),
    ("address", coerce_str),
    ("id_number_masked", coerce_str),
    ("issuing_state", coerce_str),
    ("issuing_authority", coerce_str),
    ("expiration_date", coerce_date),
)


def _parse_drivers_license_json(text: str) -> DriversLicenseExtractionResult | None:
    """Defensively parse a model response into a driver's-license result. Never raises."""
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
        data = DriversLicenseExtraction.model_validate(
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
    return DriversLicenseExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_drivers_license(
    content: bytes, media_type: str
) -> DriversLicenseExtractionResult:
    """Extract government-ID values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`. The bytes/base64, raw response,
    and **all extracted values — especially the DOB and ID number — are never
    logged**; only metadata (status / confidence / counts).
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return DriversLicenseExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return DriversLicenseExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("drivers_license_extraction_ai_failed")  # metadata only — no bytes/content
        return DriversLicenseExtractionResult.failed("AI call failed")

    result = _parse_drivers_license_json(resp.text)
    if result is None:
        logger.warning("drivers_license_extraction_parse_failed")  # no raw response logged
        return DriversLicenseExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata ONLY: status, confidence, COUNTS — NEVER any extracted value (the
    # whole ID is PII: name, DOB, ID number, address are all withheld from logs).
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "drivers_license_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
