"""Divorce decree extraction (LP-63) — Tier 1 borrower-info/legal, the LP-39a shape.

A divorce decree establishes legal **obligations** (alimony / child support) and
**property awards** that affect the loan. The support obligations are the canonical
"undisclosed obligation" feedstock — exactly what Phase 3 cross-checks against the
borrower's stated liabilities. Because a decree can set more than one obligation
(alimony AND child support, possibly each way), the schema extends the LP-39a shape
with **first-class typed lists** for ``support_obligations`` and ``property_awards``
— the same structured-rows extension the bank statement uses for transactions
(ADR-061), not a new shape:

    typed core (parties + effective date) + support_obligations[] + property_awards[]
    + grouped catch-all

**Findings sequencing (deliberate).** The obligations are **captured now** in the
typed list. Surfacing them as formal *findings* — the structured observations the
implications engine + Phase 3 read — is **wired when the findings infrastructure
exists (LP-66/67)**. Nothing is lost; this ticket does not build findings
infrastructure prematurely.

Mirrors the existing extractors for the result interface / graceful failure /
metadata-only logging. **V1 starter — refine with Priya**; accuracy validated as
real (redacted) decrees flow through (no samples were available when built).
"""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
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
from app.ai.extraction.shape import CatchAllSection, SourceLocation, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/divorce_decree.txt"
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A decree is prose and can be long; allow generous room (still fails gracefully
# on a truncated/malformed response).
_MAX_TOKENS = 6144


class SupportObligation(BaseModel):
    """One support obligation from the decree (the findings feedstock for Phase 3).

    ``obligation_type`` is alimony / child_support / etc.; ``payer`` is which party
    pays. Money as ``Decimal``; ``frequency`` is monthly / etc. (free string).
    """

    obligation_type: str | None = None  # alimony / child_support / spousal_support / ...
    amount: Decimal | None = None
    frequency: str | None = None  # monthly / weekly / annual / ...
    payer: str | None = None  # which party pays
    source: SourceLocation | None = None


class PropertyAward(BaseModel):
    """One property award from the decree (who is awarded what)."""

    description: str | None = None  # what property / asset
    awarded_to: str | None = None  # which party receives it
    source: SourceLocation | None = None


class DivorceDecreeExtraction(BaseModel):
    """A divorce decree: typed core + typed obligation/award lists + grouped catch-all.

    **Typed core** — the two parties + the ``effective_date``. **Support obligations**
    — the structured list (type/amount/frequency/payer), the Phase-3 cross-check
    feedstock. **Property awards** — the structured list (what / to whom). **Catch-all**
    — everything else (custody, legal recitals, case number, etc.).
    """

    # --- Typed core (value + source) ---------------------------------------- #
    party_1_name: TypedField[str] = Field(default_factory=TypedField)
    party_2_name: TypedField[str] = Field(default_factory=TypedField)
    effective_date: TypedField[date] = Field(default_factory=TypedField)

    # --- Structured lists (the obligation/award rows, ADR-061 extension) ----- #
    support_obligations: list[SupportObligation] = Field(default_factory=list)
    property_awards: list[PropertyAward] = Field(default_factory=list)

    # --- Grouped catch-all — everything else -------------------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class DivorceDecreeExtractionResult(BaseModel):
    """A divorce-decree extraction plus its outcome (mirrors the other results)."""

    data: DivorceDecreeExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "DivorceDecreeExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=DivorceDecreeExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


_CORE_SPEC: CoreSpec = (
    ("party_1_name", coerce_str),
    ("party_2_name", coerce_str),
    ("effective_date", coerce_date),
)


def _parse_support_obligations(raw: Any) -> list[dict[str, Any]]:
    """Coerce the support-obligations list (amount→Decimal; source kept). No hallucination.

    Only the rows the model returned are kept; a fully-empty row is dropped; a bad
    field → ``None`` (the row is kept). Non-dict entries are skipped.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row = {
            "obligation_type": coerce_str(entry.get("obligation_type")),
            "amount": coerce_decimal(entry.get("amount")),
            "frequency": coerce_str(entry.get("frequency")),
            "payer": coerce_str(entry.get("payer")),
            "source": source_payload(entry),
        }
        if any(row[k] is not None for k in ("obligation_type", "amount", "frequency", "payer")):
            rows.append(row)
    return rows


def _parse_property_awards(raw: Any) -> list[dict[str, Any]]:
    """Coerce the property-awards list (source kept). No hallucination (see above)."""
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        row = {
            "description": coerce_str(entry.get("description")),
            "awarded_to": coerce_str(entry.get("awarded_to")),
            "source": source_payload(entry),
        }
        if any(row[k] is not None for k in ("description", "awarded_to")):
            rows.append(row)
    return rows


def _parse_divorce_decree_json(text: str) -> DivorceDecreeExtractionResult | None:
    """Defensively parse a model response into a divorce-decree result. Never raises."""
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
    obligations = _parse_support_obligations(payload.get("support_obligations"))
    awards = _parse_property_awards(payload.get("property_awards"))
    sections = parse_catch_all(payload.get("additional_sections"))

    try:
        data = DivorceDecreeExtraction.model_validate(
            {
                **core_payload,
                "support_obligations": obligations,
                "property_awards": awards,
                "additional_sections": sections,
            }
        )
    except ValidationError:
        return None

    # Obligations + awards count as extracted content (a decree may be mostly these).
    status = derive_status(non_null + len(obligations) + len(awards), coercion_lost)
    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )
    return DivorceDecreeExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_divorce_decree(content: bytes, media_type: str) -> DivorceDecreeExtractionResult:
    """Extract divorce-decree values from a document's bytes (PDF/image). Never raises.

    Mirrors the existing extractors. The bytes/base64, raw response, and extracted
    values (parties, obligations, awards) are never logged — only metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return DivorceDecreeExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return DivorceDecreeExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("divorce_decree_extraction_ai_failed")  # metadata only
        return DivorceDecreeExtractionResult.failed("AI call failed")

    result = _parse_divorce_decree_json(resp.text)
    if result is None:
        logger.warning("divorce_decree_extraction_parse_failed")  # truncated/malformed
        return DivorceDecreeExtractionResult.failed("could not parse extraction")

    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, COUNTS — never values (parties/obligations).
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "divorce_decree_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        support_obligations=len(result.data.support_obligations),
        property_awards=len(result.data.property_awards),
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
