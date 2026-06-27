"""1099 extraction (LP-60) — Tier 1 income/employment, following the LP-39a shape.

A Form 1099 reports non-employee / other income. Unlike the W-2 it is a **series**
— NEC (contractor income), INT (interest), DIV (dividends), MISC, R (retirement
distributions) — each with different relevant boxes. Rather than a separate
extractor per subtype, the typed core carries a ``form_subtype`` plus a single
``income_amount`` (the primary amount *for that subtype*: NEC box 1, INT box 1
interest, DIV box 1a ordinary dividends, R box 1 gross distribution, …); every
specific box lands in the grouped catch-all, so nothing is lost.

Mirrors :mod:`app.ai.extraction.w2`: a typed core (each a ``TypedField`` with
source) + ``additional_sections`` catch-all, full-document Sonnet reading, the
shared tolerant parser, honest nulls, graceful ``.failed()`` (never raises), and
**metadata-only logging**.

**Sensitive TIN (ADR-147 discipline).** ``recipient_tin`` (an SSN for an
individual recipient) is extracted into the typed core for the Phase 3 identity
cross-check, but is **never logged** (only counts) and is **displayed masked** in
the drawer. The raw value lives only in the tenant-scoped extraction JSON.

**Income vs asset income.** NEC is employment-like (self-employment income);
INT/DIV are asset income. The subtype preserves that distinction for Phase 3; this
extractor just reports faithfully.

Typed core is a **V1 starter — refine with Priya**; accuracy is validated as real
1099s flow through (no sample documents were available when this was built).
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

_PROMPT_PATH = "extraction/form_1099.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
_MAX_TOKENS = 4096


class Form1099Extraction(BaseModel):
    """A 1099 in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the subtype + the parties + the primary amount: ``form_subtype``
    (NEC/INT/DIV/MISC/R), ``payer_name``/``payer_tin``, ``recipient_name``/
    ``recipient_tin`` (SENSITIVE), ``tax_year``, and ``income_amount`` (the primary
    figure for the subtype). **Grouped catch-all** (``additional_sections``) — every
    specific box (federal tax withheld, state info, the other subtype boxes).

    ``recipient_tin`` is **sensitive** — never logged; masked in display (ADR-147).
    """

    # --- Typed core (value + source) ---------------------------------------- #
    form_subtype: TypedField[str] = Field(default_factory=TypedField)  # NEC/INT/DIV/MISC/R
    payer_name: TypedField[str] = Field(default_factory=TypedField)
    payer_tin: TypedField[str] = Field(default_factory=TypedField)
    recipient_name: TypedField[str] = Field(default_factory=TypedField)
    recipient_tin: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    income_amount: TypedField[Decimal] = Field(default_factory=TypedField)  # primary, per subtype

    # --- Grouped catch-all — everything else, by section -------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class Form1099ExtractionResult(BaseModel):
    """A 1099 extraction plus its outcome (mirrors ``W2ExtractionResult``)."""

    data: Form1099Extraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "Form1099ExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=Form1099Extraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("form_subtype", coerce_str),
    ("payer_name", coerce_str),
    ("payer_tin", coerce_str),
    ("recipient_name", coerce_str),
    ("recipient_tin", coerce_str),
    ("tax_year", coerce_int),
    ("income_amount", coerce_decimal),
)


def _parse_1099_json(text: str) -> Form1099ExtractionResult | None:
    """Defensively parse a model response into a 1099 result. Never raises."""
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
        data = Form1099Extraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    status = derive_status(non_null, coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return Form1099ExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_1099(content: bytes, media_type: str) -> Form1099ExtractionResult:
    """Extract structured 1099 values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.w2.extract_w2`: empty/unsupported document →
    ``failed`` without an API call; otherwise loads the prompt, sends the full
    document to the Sonnet-class model, and parses defensively. The bytes/base64,
    raw response, and extracted values (including the **recipient TIN**) are never
    logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return Form1099ExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return Form1099ExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("form_1099_extraction_ai_failed")  # metadata only — no bytes/content
        return Form1099ExtractionResult.failed("AI call failed")

    result = _parse_1099_json(resp.text)
    if result is None:
        logger.warning("form_1099_extraction_parse_failed")  # no raw response logged
        return Form1099ExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — NEVER the values (and never the
    # recipient TIN). The subtype is a non-PII category and is safe/useful to log.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "form_1099_extraction_done",
        status=result.status,
        confidence=result.confidence,
        form_subtype=result.data.form_subtype.value,  # e.g. "NEC" — a category, not PII
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
