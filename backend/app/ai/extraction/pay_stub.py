"""Pay stub extraction (LP-39) — Phase 1, pay stub only.

Where classification (LP-38) answered "what kind of document is this?",
extraction answers "what does it say?". This builds **one** document type
end-to-end — the pay stub — to establish the per-type pattern (typed schema +
prompt + module) that Phase 2 replicates for the other ~100 types.

Core principles:

  * **Typed, document-specific — not a generic field bag.** :class:`PayStubExtraction`
    has named, typed, mostly-nullable fields. This is the deliberate departure from
    the POC's generic ``ExtractedField`` approach (LP-16, ADR-057): typed values are
    what make extracted data verifiable downstream (Phase 3 checks ``gross_pay`` /
    ``pay_period_end`` as a ``Decimal`` / ``date``). The result serializes to JSON for
    ``Extraction.extracted_data`` (persisted/versioned by LP-42, not here).
  * **Honest nulls, no hallucination.** A value not present/legible on the document is
    ``None`` — never fabricated. The prompt forbids guessing; a hallucinated income
    figure is worse than a missing one (it could falsely pass verification).
  * **Reads, doesn't judge.** Extraction reports faithfully what's on the document,
    including absences. Whether the income is plausible / sufficient is the
    verification engine's job (Phase 3) — this module does not compute or editorialize.
  * **Graceful failure.** :func:`extract_pay_stub` never raises: an empty/unsupported
    document, an AI error, or unparseable output all return
    ``PayStubExtractionResult.failed(...)``.
  * **Privacy.** The document bytes (and their base64), the raw response, and the
    extracted *values* are borrower PII and are **never** logged — only metadata
    (status, confidence, and a count of non-null fields).

Input is the **full document** (PDF/image bytes), sent to the Sonnet-class model for
**native reading** (no OCR, no pre-extracted text) via the LP-37 document/image
content block (LP-37 revision, ADR-126; this change ADR-128). Reuses the LP-38
patterns: the file-based prompt (``load_prompt``), the shared defensive parser
(``app.ai.parsing``), graceful failure, and metadata-only logging. Uses
``settings.anthropic_model_extraction`` — a more capable Sonnet-class model, versus
classification's cheaper one.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.extraction.shape import CatchAllSection, TypedField
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/pay_stub.txt"
# Media types we can send to the model (matches the LP-36 upload allowlist and the
# LP-37 document-block support); ``image/jpg`` is normalized to image/jpeg.
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# The response now captures EVERYTHING on the stub (typed core + grouped catch-all
# with per-field source), so it can be sizeable — give the model room.
_MAX_TOKENS = 4096

# Date formats accepted from the model, tried in order (ISO first).
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
)


class PayStubExtraction(BaseModel):
    """A pay stub in the LP-39a shape: typed core + grouped catch-all.

    **Typed core** — the mortgage-decision-relevant fields, each a
    :class:`TypedField` carrying the coerced value + its :class:`SourceLocation`
    (page + verbatim snippet). Feeds DTI (income) + recency (dates). This core is a
    **V1 starter — refine with Priya; grows in Phase 3** as deterministic rules
    need fields (promoted from the catch-all).

    **Grouped catch-all** (``additional_sections``) — *everything else* on the
    stub (specific deductions, tax line items, employer address, check number, …),
    grouped by the document's sections. Nothing on the document is lost; catch-all
    values stay strings (not coerced).
    """

    # --- Typed core (value + source) ---------------------------------------- #
    employer_name: TypedField[str] = Field(default_factory=TypedField)
    employee_name: TypedField[str] = Field(default_factory=TypedField)
    pay_period_start: TypedField[date] = Field(default_factory=TypedField)
    pay_period_end: TypedField[date] = Field(default_factory=TypedField)
    pay_date: TypedField[date] = Field(default_factory=TypedField)
    gross_pay: TypedField[Decimal] = Field(default_factory=TypedField)  # period gross
    net_pay: TypedField[Decimal] = Field(default_factory=TypedField)
    ytd_gross: TypedField[Decimal] = Field(default_factory=TypedField)
    pay_frequency: TypedField[str] = Field(default_factory=TypedField)
    hours: TypedField[Decimal] = Field(default_factory=TypedField)
    rate: TypedField[Decimal] = Field(default_factory=TypedField)

    # --- Grouped catch-all — everything else, by section -------------------- #
    additional_sections: list[CatchAllSection] = Field(default_factory=list)


class PayStubExtractionResult(BaseModel):
    """A pay stub extraction plus its outcome.

    ``status`` reuses LP-16's :class:`ExtractionStatus` so the pipeline (LP-42)
    can persist it directly: ``SUCCEEDED`` (fields read cleanly), ``PARTIAL`` (a
    model-provided value couldn't be coerced and was dropped to null), or
    ``FAILED`` (nothing extracted, or the call/parse failed). ``confidence`` is
    the model's overall confidence clamped to ``[0, 1]``.
    """

    data: PayStubExtraction
    status: ExtractionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
    # Token usage from the AI call (LP-42 records cost from these). None when no
    # call was made (empty/unsupported input) or it failed before a response.
    input_tokens: int | None = None
    output_tokens: int | None = None

    @classmethod
    def failed(cls, reason: str) -> "PayStubExtractionResult":
        """The graceful fallback: all-null data, ``FAILED``, zero confidence."""
        return cls(
            data=PayStubExtraction(),
            status=ExtractionStatus.FAILED,
            confidence=0.0,
            reasoning=reason,
        )


def _coerce_decimal(value: Any) -> Decimal | None:
    """Coerce a model value to ``Decimal``; junk/empty/``None`` → ``None``.

    Tolerates currency strings like ``"$4,200.00"`` and bare numbers. A single
    uncoercible value returns ``None`` (the caller marks the run PARTIAL) rather
    than failing the whole extraction.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        cleaned = value.strip().replace("$", "").replace(",", "").replace(" ", "")
        if not cleaned:
            return None
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
    return None


def _coerce_date(value: Any) -> date | None:
    """Coerce a model value to ``date``; junk/empty/``None`` → ``None``.

    Accepts ISO and common US formats; anything unparseable returns ``None``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def _coerce_str(value: Any) -> str | None:
    """Coerce a model value to a non-empty trimmed string, else ``None``."""
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


# The typed-core fields and the coercer for each (everything else → catch-all).
_CORE_SPEC: tuple[tuple[str, Callable[[Any], Any]], ...] = (
    ("employer_name", _coerce_str),
    ("employee_name", _coerce_str),
    ("pay_period_start", _coerce_date),
    ("pay_period_end", _coerce_date),
    ("pay_date", _coerce_date),
    ("gross_pay", _coerce_decimal),
    ("net_pay", _coerce_decimal),
    ("ytd_gross", _coerce_decimal),
    ("pay_frequency", _coerce_str),
    ("hours", _coerce_decimal),
    ("rate", _coerce_decimal),
)


def _coerce_page(value: Any) -> int | None:
    """A page number → int; junk/absent → None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _source_payload(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Build a SourceLocation dict from an entry's page/snippet, or None if neither."""
    page = _coerce_page(entry.get("page"))
    raw_snippet = entry.get("snippet")
    snippet = raw_snippet.strip() if isinstance(raw_snippet, str) and raw_snippet.strip() else None
    if page is None and snippet is None:
        return None
    return {"page": page, "snippet": snippet}


def _parse_catch_all(raw: Any) -> list[dict[str, Any]]:
    """Pass through the grouped catch-all as section/field dicts (values stay strings).

    Defensive: skips non-dict sections/fields and fields without a label; drops
    empty sections; coerces only ``page`` (to int) and keeps ``snippet`` verbatim.
    """
    sections: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return sections
    for sec in raw:
        if not isinstance(sec, dict):
            continue
        name = sec.get("section")
        section_name = name.strip() if isinstance(name, str) and name.strip() else "Other"
        fields_out: list[dict[str, Any]] = []
        raw_fields = sec.get("fields")
        if isinstance(raw_fields, list):
            for field in raw_fields:
                if not isinstance(field, dict):
                    continue
                label = field.get("label")
                if not isinstance(label, str) or not label.strip():
                    continue
                value = field.get("value")
                value_str = None if value is None else (str(value).strip() or None)
                fields_out.append(
                    {"label": label.strip(), "value": value_str, "source": _source_payload(field)}
                )
        if fields_out:
            sections.append({"section": section_name, "fields": fields_out})
    return sections


def _parse_pay_stub_json(text: str) -> PayStubExtractionResult | None:
    """Defensively parse a model response into the new-shape result. Never raises.

    Reads the documented JSON contract — ``typed_core`` (per-field
    ``{value, page, snippet}``) + ``additional_sections`` (grouped catch-all) —
    tolerating fences/prose and a flat fallback. The typed core is **coerced**
    (currency/date/string; a present-but-uncoercible value → ``None``, source
    kept); the catch-all is **passed through** as strings. Status is derived from
    the typed core: no field read → ``FAILED``; a coercion loss → ``PARTIAL``;
    else ``SUCCEEDED`` (the catch-all doesn't affect status). Returns ``None`` only
    when no JSON object can be parsed.
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

    # Typed core under "typed_core" (the contract); fall back to top-level keys.
    core = payload.get("typed_core")
    if not isinstance(core, dict):
        core = payload

    coercion_lost = False
    core_payload: dict[str, Any] = {}
    non_null = 0
    for key, coercer in _CORE_SPEC:
        entry = core.get(key)
        if isinstance(entry, dict):
            raw = entry.get("value")
            source = _source_payload(entry)
        else:
            raw = entry  # tolerant: a bare value with no source
            source = None
        coerced = coercer(raw)
        if coerced is None and raw not in (None, "") and not isinstance(raw, bool):
            coercion_lost = True  # a present value we couldn't coerce → data loss
        if coerced is not None:
            non_null += 1
        core_payload[key] = {"value": coerced, "source": source}

    sections = _parse_catch_all(payload.get("additional_sections"))

    try:
        data = PayStubExtraction.model_validate({**core_payload, "additional_sections": sections})
    except ValidationError:
        return None

    if non_null == 0:
        status = ExtractionStatus.FAILED
    elif coercion_lost:
        status = ExtractionStatus.PARTIAL
    else:
        status = ExtractionStatus.SUCCEEDED

    confidence = coerce_confidence(payload.get("confidence"))
    raw_reasoning = payload.get("reasoning")
    reasoning = (
        raw_reasoning.strip() if isinstance(raw_reasoning, str) and raw_reasoning.strip() else None
    )

    return PayStubExtractionResult(
        data=data, status=status, confidence=confidence, reasoning=reasoning
    )


async def extract_pay_stub(content: bytes, media_type: str) -> PayStubExtractionResult:
    """Extract structured pay stub values from a document's bytes (PDF/image). Never raises.

    An empty or unsupported document fails without an API call. Otherwise it loads
    the file-based prompt (the ``system`` instruction), sends the **full document**
    to the Sonnet-class model as a document/image content block (LP-37
    ``build_document_message``), and parses defensively/tolerantly. Any AI error or
    unparseable output returns ``PayStubExtractionResult.failed(...)``. The document
    bytes/base64, raw response, and extracted values are never logged (PII) — only
    metadata.
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return PayStubExtractionResult.failed("empty or unsupported document")

    system_prompt = load_prompt(_PROMPT_PATH)
    try:
        # build_document_message base64-encodes the bytes into a document/image
        # block; it raises ValueError on an unsupported type (already filtered).
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return PayStubExtractionResult.failed("unsupported document media type")

    try:
        resp = await complete(
            model=settings.anthropic_model_extraction,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("paystub_extraction_ai_failed")  # metadata only — no bytes/content
        return PayStubExtractionResult.failed("AI call failed")

    result = _parse_pay_stub_json(resp.text)
    if result is None:
        logger.warning("paystub_extraction_parse_failed")  # no raw response logged
        return PayStubExtractionResult.failed("could not parse extraction")

    # Surface the call's token usage so the pipeline (LP-42) can record cost.
    result.input_tokens = resp.input_tokens
    result.output_tokens = resp.output_tokens

    # Metadata only: status, confidence, and COUNTS — never the extracted values
    # (income, employer, names are all PII). Counts: typed-core fields populated,
    # and catch-all sections captured.
    core_present = sum(1 for key, _ in _CORE_SPEC if getattr(result.data, key).value is not None)
    logger.info(
        "paystub_extraction_done",
        status=result.status,
        confidence=result.confidence,
        core_fields_present=core_present,
        catch_all_sections=len(result.data.additional_sections),
    )
    return result
