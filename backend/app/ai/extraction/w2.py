"""W-2 extraction (LP-39b) — the first replication of the LP-39a shape.

A W-2 (IRS Form W-2) is a fixed federal form with standardized numbered boxes,
and its decision fields are **annual** figures — a different typed core than the
pay stub's period figures — so this proves "different typed core, **same
shape**", exactly what Phase 2's fan-out needs.

Mirrors :mod:`app.ai.extraction.pay_stub`: a typed core (each a ``TypedField``
with source) + a grouped catch-all (``additional_sections``), full-document
Opus reading via the LP-37 wrapper, the shared defensive/tolerant parser
(:mod:`app.ai.extraction.parsing`), honest nulls, graceful failure (never
raises), and **metadata-only logging** (never bytes/values).

**SSN handling (ADR-147).** ``employee_ssn`` is extracted into the typed core for
the Phase 3 identity cross-check (W-2 SSN vs borrower SSN), but is treated as
sensitive: it is **never logged** (only counts are logged) and is **displayed
masked** (last 4) in the LP-43 drawer. The raw value lives only in the
tenant-scoped extraction JSON.

This module is **not yet wired into the LP-42 pipeline** — routing the fan-out to
all three types is LP-39c.
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
    parse_flat_rows,
    parse_typed_core,
)
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/w2.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A W-2 is a single page, but LP-461 promotes the state/local boxes (15-20) to typed core and adds the
# Box 12 codes as a nested list → one nested list, so the sizing rule's 1-list tier (8192). The shared
# truncation guard (app.ai.extraction.model_call) still backstops any overflow.
_MAX_TOKENS = 8192


class W2Extraction(BaseModel):
    """A W-2 in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the mortgage-decision-relevant W-2 fields, each a
    :class:`TypedField` (value + source): the **tax year**, employee/employer
    identity, and the federal wage/withholding boxes (1-6). Feeds income
    verification + cross-source identity/employer checks. **V1 starter — refine
    with Priya; grows in Phase 3** as deterministic rules need fields.

    **Grouped catch-all** (``additional_sections``) — everything else: state/local
    wages & tax (Boxes 15-20), Box 12 codes, Box 13 checkboxes, Box 14, control
    number, addresses, etc. Nothing on the form is lost; catch-all values stay
    strings.

    ``employee_ssn`` is **sensitive** — never logged; masked in display (ADR-147).
    """

    # --- Typed core (value + source) ---------------------------------------- #
    tax_year: TypedField[int] = Field(default_factory=TypedField)
    employee_name: TypedField[str] = Field(default_factory=TypedField)
    employee_ssn: TypedField[str] = Field(default_factory=TypedField)  # SENSITIVE
    employer_name: TypedField[str] = Field(default_factory=TypedField)
    employer_ein: TypedField[str] = Field(
        default_factory=TypedField
    )  # SENSITIVE — masked in snapshot (LP-206)
    wages_tips_other_comp: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 1
    federal_income_tax_withheld: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 2
    social_security_wages: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 3
    social_security_tax_withheld: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 4
    medicare_wages: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 5
    medicare_tax_withheld: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 6

    # --- Grouped catch-all — everything else, by section -------------------- #
    # --- LP-446 diff — the exists_today:false additions --------------------- #
    employer_address: TypedField[str] = Field(default_factory=TypedField)
    employee_address: TypedField[str] = Field(default_factory=TypedField)
    retirement_plan_checked: TypedField[str] = Field(default_factory=TypedField)
    statutory_employee_checked: TypedField[str] = Field(default_factory=TypedField)
    is_corrected_w2: TypedField[str] = Field(default_factory=TypedField)

    # --- LP-461 diff — verified scalar additions --------------------------- #
    control_number: TypedField[str] = Field(default_factory=TypedField)  # Box d
    # Box 13 checkbox #3 (statutory + retirement already exist). ⚠️ null ≠ "unchecked": the prompt returns
    # "checked"/"unchecked" when the box is VISIBLE, null only when Box 13 is not legible (LP-458 fix,
    # extended to all three Box-13 checkboxes).
    third_party_sick_pay_checked: TypedField[str] = Field(default_factory=TypedField)
    # State boxes 15-17 (single-state; a 2-state W-2's repeating block is future — see LP-461 doc).
    state_code: TypedField[str] = Field(default_factory=TypedField)  # Box 15
    state_employer_id: TypedField[str] = Field(default_factory=TypedField)  # Box 15
    state_wages: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 16
    state_income_tax: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 17
    # Local boxes 18-20.
    local_wages: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 18
    local_income_tax: TypedField[Decimal] = Field(default_factory=TypedField)  # Box 19
    locality_name: TypedField[str] = Field(default_factory=TypedField)  # Box 20

    # --- LP-461 diff — captured nested list (bare rows) -------------------- #
    # Box 12 codes (A-HH) with amounts — typically 0-4 per W-2.
    box_12_items: list[dict[str, Any]] = Field(default_factory=list)

    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class W2ExtractionResult(BaseModel):
    """A W-2 extraction plus its outcome (mirrors ``PayStubExtractionResult``)."""

    data: W2Extraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    # Token usage from the AI call (the pipeline records cost from these, LP-39c).
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "W2ExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=W2Extraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


# Typed-core fields + the coercer for each (everything else → catch-all).
_CORE_SPEC: CoreSpec = (
    ("tax_year", coerce_int),
    ("employee_name", coerce_str),
    ("employee_ssn", coerce_str),
    ("employer_name", coerce_str),
    ("employer_ein", coerce_str),
    ("wages_tips_other_comp", coerce_decimal),
    ("federal_income_tax_withheld", coerce_decimal),
    ("social_security_wages", coerce_decimal),
    ("social_security_tax_withheld", coerce_decimal),
    ("medicare_wages", coerce_decimal),
    ("medicare_tax_withheld", coerce_decimal),
    # LP-446 diff additions
    ("employer_address", coerce_str),
    ("employee_address", coerce_str),
    ("retirement_plan_checked", coerce_str),
    ("statutory_employee_checked", coerce_str),
    ("is_corrected_w2", coerce_str),
    # LP-461 diff additions
    ("control_number", coerce_str),
    ("third_party_sick_pay_checked", coerce_str),
    ("state_code", coerce_str),
    ("state_employer_id", coerce_str),
    ("state_wages", coerce_decimal),
    ("state_income_tax", coerce_decimal),
    ("local_wages", coerce_decimal),
    ("local_income_tax", coerce_decimal),
    ("locality_name", coerce_str),
)

# LP-461 — Box 12 codes as bare rows (mirrors bank_statement's transactions parse).
_BOX_12_ITEMS_ROW: CoreSpec = (
    ("code", coerce_str),
    ("amount", coerce_str),
)


def _parse_w2_json(text: str) -> W2ExtractionResult | None:
    """Defensively parse a model response into a W-2 result. Never raises.

    Uses the shared parser — ``typed_core`` (coerced + source) +
    ``additional_sections`` (passed through) — with status derived from the typed
    core. Returns ``None`` only when no JSON object can be parsed.
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

    core_payload, non_null, coercion_lost = parse_typed_core(payload, _CORE_SPEC)
    box_12_items = parse_flat_rows(payload.get("box_12_items"), _BOX_12_ITEMS_ROW)
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = W2Extraction.model_validate(
            {**core_payload, "box_12_items": box_12_items, "additional_sections": sections}
        )
    except ValidationError:
        return None

    status = derive_status(non_null + len(box_12_items), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return W2ExtractionResult(data=data, status=status, confidence=confidence, reasoning=reasoning)


async def extract_w2(content: bytes, media_type: str) -> W2ExtractionResult:
    """Extract structured W-2 values from a document's bytes (PDF/image). Never raises.

    Mirrors :func:`app.ai.extraction.pay_stub.extract_pay_stub`: empty/unsupported
    document → ``failed`` without an API call; otherwise loads the file-based
    prompt, sends the full document to the Opus-class model, and parses
    defensively. The document bytes/base64, raw response, and extracted values
    (including the **SSN**) are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return W2ExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return W2ExtractionResult.failed("unsupported document media type")

    call = await run_extraction_completion(
        system=system_prompt,
        message=message,
        max_tokens=_MAX_TOKENS,
        log_label="w2",
    )
    if call.text is None:
        return W2ExtractionResult.failed(call.failure_reason or "AI call failed")

    result = _parse_w2_json(call.text)
    if result is None:
        logger.warning("w2_extraction_parse_failed")  # no raw response logged
        return W2ExtractionResult.failed("could not parse extraction")

    result.input_tokens = call.input_tokens
    result.output_tokens = call.output_tokens

    # Metadata only: status, confidence, COUNTS — NEVER the values (and never the
    # SSN). Counts: typed-core fields populated + catch-all sections captured.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "w2_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
        box_12_items=len(result.data.box_12_items),
    )
    return result
