"""Shared identity-document extraction (LP-472).

ONE extractor for the whole government-identity family — ``passport``,
``permanent_resident_card``, ``work_visa_ead_card`` and ``government_issued_id``.
The four classify precisely (they stay distinct catalog types with distinct
indicators — ID-8 needs citizenship vs. work-authorization-with-expiry) but they
**extract in common**: one superset field set, one prompt, one module. All four
``EXTRACTORS`` keys point here, so the family's identity fields cannot drift — there
is a single thing to change. ``drivers_license`` is deliberately NOT part of this
family; it keeps its own tuned extractor (spec 014).

Field names reuse the already-registered ``_PII_FIELDS`` slots (``document_number``,
``uscis_or_a_number``) so no new PII wiring is needed. The MRZ is deliberately NOT a
typed field — it re-encodes name/DOB/number/expiry already captured and its
contiguous digit run would trip the at-rest ``_LONG_DIGITS`` guard; anything unread
lands in ``additional_sections``.

Shape mirrors the hand-written flat extractors (``property_tax_bill`` is the
reference): a typed core (each field a ``TypedField`` with source) + a grouped
catch-all, honest nulls, graceful ``.failed()``, metadata-only logging.
"""

import json
from datetime import date
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
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
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/identity_document.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output (no nested lists) → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class IdentityDocumentExtraction(BaseModel):
    """A government identity document in the LP-39a shape: typed core + grouped catch-all.

    The typed core is the SHARED superset for the whole family. A given document fills
    only the fields printed on it (a passport leaves ``category_code`` null; an EAD
    leaves ``place_of_issue`` null) — the classifier fixes the type, the schema is common.
    """

    # --- Typed core (value + source) — the shared identity superset ---------- #
    document_type_as_printed: TypedField[str] = Field(default_factory=TypedField)
    surname: TypedField[str] = Field(default_factory=TypedField)
    given_names: TypedField[str] = Field(default_factory=TypedField)
    full_name: TypedField[str] = Field(default_factory=TypedField)
    date_of_birth: TypedField[date] = Field(default_factory=TypedField)
    document_number: TypedField[str] = Field(default_factory=TypedField)
    uscis_or_a_number: TypedField[str] = Field(default_factory=TypedField)
    issue_date: TypedField[date] = Field(default_factory=TypedField)
    expiry_date: TypedField[date] = Field(default_factory=TypedField)
    valid_from_date: TypedField[date] = Field(default_factory=TypedField)
    resident_since_date: TypedField[date] = Field(default_factory=TypedField)
    category_code: TypedField[str] = Field(default_factory=TypedField)
    employment_terms_or_restriction: TypedField[str] = Field(default_factory=TypedField)
    issuing_country_or_state: TypedField[str] = Field(default_factory=TypedField)
    issuing_authority: TypedField[str] = Field(default_factory=TypedField)
    place_or_country_of_birth: TypedField[str] = Field(default_factory=TypedField)
    nationality_or_citizenship: TypedField[str] = Field(default_factory=TypedField)
    place_of_issue: TypedField[str] = Field(default_factory=TypedField)
    government_id_type: TypedField[str] = Field(default_factory=TypedField)
    residential_address: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else (incl. any MRZ) ---------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class IdentityDocumentExtractionResult(BaseModel):
    """An identity-document extraction plus its outcome (mirrors the other extractor results)."""

    data: IdentityDocumentExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "IdentityDocumentExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=IdentityDocumentExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("document_type_as_printed", coerce_str),
    ("surname", coerce_str),
    ("given_names", coerce_str),
    ("full_name", coerce_str),
    ("date_of_birth", coerce_date),
    ("document_number", coerce_str),
    ("uscis_or_a_number", coerce_str),
    ("issue_date", coerce_date),
    ("expiry_date", coerce_date),
    ("valid_from_date", coerce_date),
    ("resident_since_date", coerce_date),
    ("category_code", coerce_str),
    ("employment_terms_or_restriction", coerce_str),
    ("issuing_country_or_state", coerce_str),
    ("issuing_authority", coerce_str),
    ("place_or_country_of_birth", coerce_str),
    ("nationality_or_citizenship", coerce_str),
    ("place_of_issue", coerce_str),
    ("government_id_type", coerce_str),
    ("residential_address", coerce_str),
)


def _parse_identity_document_json(text: str) -> IdentityDocumentExtractionResult | None:
    """Defensively parse a model response into an identity-document result. Never raises."""
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
        data = IdentityDocumentExtraction.model_validate(
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
    return IdentityDocumentExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_identity_document(
    content: bytes, media_type: str
) -> IdentityDocumentExtractionResult:
    """Extract identity-document values from a document's bytes (PDF/image). Never raises.

    Shared by passport / permanent_resident_card / work_visa_ead_card /
    government_issued_id. The bytes/base64, raw response, and extracted values are
    never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return IdentityDocumentExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return IdentityDocumentExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="identity_document",
    )
    if call.text is None:
        return IdentityDocumentExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_identity_document_json(call.text)
    if result is None:
        logger.warning("identity_document_extraction_parse_failed")  # no raw response logged
        return IdentityDocumentExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "identity_document_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
