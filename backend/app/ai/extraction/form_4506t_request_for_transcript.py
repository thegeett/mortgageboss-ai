"""Form 4506T Request For Transcript extraction — GENERATED from a schema spec by the LP-434 generator.

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
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import build_document_message
from app.ai.extraction.model_call import run_extraction_completion
from app.ai.extraction.parsing import (
    CoreSpec,
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

_PROMPT_PATH = "extraction/form_4506t_request_for_transcript.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Bounded fixed-form output → the 4096 scaffold budget (guide §7).
# The test_extraction_budget_sizing CI guard enforces the sizing rule.
_MAX_TOKENS = 4096


class Form4506tRequestForTranscriptExtraction(BaseModel):
    """A form 4506t request for transcript in the LP-39a shape: typed core + grouped catch-all.

    Typed core — the mortgage-decision-relevant fields, each a ``TypedField`` (value +
    source). Grouped catch-all (``additional_sections``) — everything else, so nothing
    on the document is lost. GENERATED STARTER — refine the field set/prompt with Priya.
    """

    # --- Typed core (value + source) ---------------------------------------- #
    issuer_name: TypedField[str] = Field(default_factory=TypedField)
    form_revision: TypedField[str] = Field(default_factory=TypedField)
    tax_form_number_requested: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_name_on_return: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_tin: TypedField[str] = Field(default_factory=TypedField)
    spouse_name_on_joint_return: TypedField[str] = Field(default_factory=TypedField)
    spouse_tin: TypedField[str] = Field(default_factory=TypedField)
    current_address: TypedField[str] = Field(default_factory=TypedField)
    previous_address_on_last_return: TypedField[str] = Field(default_factory=TypedField)
    customer_file_number: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_phone: TypedField[str] = Field(default_factory=TypedField)
    tax_years_or_periods_requested: TypedField[str] = Field(default_factory=TypedField)
    return_transcript_selected: TypedField[str] = Field(default_factory=TypedField)
    account_transcript_selected: TypedField[str] = Field(default_factory=TypedField)
    record_of_account_selected: TypedField[str] = Field(default_factory=TypedField)
    verification_of_nonfiling_selected: TypedField[str] = Field(default_factory=TypedField)
    w2_1099_1098_5498_transcript_selected: TypedField[str] = Field(default_factory=TypedField)
    signatory_attestation_checked: TypedField[str] = Field(default_factory=TypedField)
    taxpayer_signature_and_date: TypedField[str] = Field(default_factory=TypedField)
    spouse_signature_and_date: TypedField[str] = Field(default_factory=TypedField)
    signer_title_or_capacity: TypedField[str] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class Form4506tRequestForTranscriptExtractionResult(BaseModel):
    """A form 4506t request for transcript extraction plus its outcome (mirrors the other extractor results)."""

    data: Form4506tRequestForTranscriptExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "Form4506tRequestForTranscriptExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=Form4506tRequestForTranscriptExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("issuer_name", coerce_str),
    ("form_revision", coerce_str),
    ("tax_form_number_requested", coerce_str),
    ("taxpayer_name_on_return", coerce_str),
    ("taxpayer_tin", coerce_str),
    ("spouse_name_on_joint_return", coerce_str),
    ("spouse_tin", coerce_str),
    ("current_address", coerce_str),
    ("previous_address_on_last_return", coerce_str),
    ("customer_file_number", coerce_str),
    ("taxpayer_phone", coerce_str),
    ("tax_years_or_periods_requested", coerce_str),
    ("return_transcript_selected", coerce_str),
    ("account_transcript_selected", coerce_str),
    ("record_of_account_selected", coerce_str),
    ("verification_of_nonfiling_selected", coerce_str),
    ("w2_1099_1098_5498_transcript_selected", coerce_str),
    ("signatory_attestation_checked", coerce_str),
    ("taxpayer_signature_and_date", coerce_str),
    ("spouse_signature_and_date", coerce_str),
    ("signer_title_or_capacity", coerce_str),
)


def _parse_form_4506t_request_for_transcript_json(
    text: str,
) -> Form4506tRequestForTranscriptExtractionResult | None:
    """Defensively parse a model response into a form 4506t request for transcript result. Never raises."""
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
        data = Form4506tRequestForTranscriptExtraction.model_validate(
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
    return Form4506tRequestForTranscriptExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_form_4506t_request_for_transcript(
    content: bytes, media_type: str
) -> Form4506tRequestForTranscriptExtractionResult:
    """Extract form 4506t request for transcript values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return Form4506tRequestForTranscriptExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return Form4506tRequestForTranscriptExtractionResult.failed(
            "unsupported document media type"
        )

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="form_4506t_request_for_transcript",
    )
    if call.text is None:
        return Form4506tRequestForTranscriptExtractionResult.failed(
            call.failure_reason or "AI call failed"
        )

    result = _parse_form_4506t_request_for_transcript_json(call.text)
    if result is None:
        logger.warning(
            "form_4506t_request_for_transcript_extraction_parse_failed"
        )  # no raw response logged
        return Form4506tRequestForTranscriptExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — never values.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "form_4506t_request_for_transcript_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
