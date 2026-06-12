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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.client import AIClientError, build_document_message, complete
from app.ai.parsing import coerce_confidence, extract_json_object
from app.ai.prompt_loader import load_prompt
from app.core.config import settings
from app.models.extraction import ExtractionStatus

logger = structlog.get_logger(__name__)

_PROMPT_PATH = "extraction/pay_stub.txt"
# Media types we can send to the model (matches the LP-36 upload allowlist and the
# LP-37 document-block support); ``image/jpg`` is normalized to image/jpeg.
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# A pay stub's JSON object is small but has ~11 fields + reasoning; give it room.
_MAX_TOKENS = 1024

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
    """The structured values read from a pay stub.

    **V1 STARTER field set — refine with Priya (domain expert).** Every field is
    nullable: a missing/illegible value is an honest ``None``, never fabricated.
    Money is ``Decimal``; dates are ``date``; ``pay_frequency`` is a free string
    for V1 (could become an enum later).
    """

    employer_name: str | None = None
    employee_name: str | None = None
    pay_period_start: date | None = None
    pay_period_end: date | None = None
    pay_date: date | None = None
    gross_pay: Decimal | None = None  # period gross
    net_pay: Decimal | None = None
    ytd_gross: Decimal | None = None
    pay_frequency: str | None = None  # e.g. "weekly" / "biweekly" / "semimonthly" / "monthly"
    hours: Decimal | None = None
    rate: Decimal | None = None


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


def _parse_pay_stub_json(text: str) -> PayStubExtractionResult | None:
    """Defensively parse a model response into a :class:`PayStubExtractionResult`.

    Extracts the JSON object (tolerating fences/prose), coerces each field
    tolerantly (currency/date/string), and derives the status: ``FAILED`` if no
    field was read, ``PARTIAL`` if a model-provided value couldn't be coerced
    (data loss), else ``SUCCEEDED``. Returns ``None`` only when no JSON object can
    be parsed at all (→ the caller produces the failed fallback). Never raises.
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

    # The model may nest the fields under "data"/"fields", or put them at the top
    # level — accept either so a reasonable response shape isn't rejected.
    fields = payload.get("data")
    if not isinstance(fields, dict):
        fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = payload

    coercion_lost = False

    def take(key: str, coercer: Any) -> Any:
        nonlocal coercion_lost
        raw = fields.get(key)
        coerced = coercer(raw)
        # A non-empty model value that coerced to None is lost data → PARTIAL.
        if coerced is None and raw not in (None, "") and not isinstance(raw, bool):
            coercion_lost = True
        return coerced

    try:
        data = PayStubExtraction(
            employer_name=_coerce_str(fields.get("employer_name")),
            employee_name=_coerce_str(fields.get("employee_name")),
            pay_period_start=take("pay_period_start", _coerce_date),
            pay_period_end=take("pay_period_end", _coerce_date),
            pay_date=take("pay_date", _coerce_date),
            gross_pay=take("gross_pay", _coerce_decimal),
            net_pay=take("net_pay", _coerce_decimal),
            ytd_gross=take("ytd_gross", _coerce_decimal),
            pay_frequency=_coerce_str(fields.get("pay_frequency")),
            hours=take("hours", _coerce_decimal),
            rate=take("rate", _coerce_decimal),
        )
    except ValidationError:
        return None

    non_null = sum(1 for v in data.model_dump().values() if v is not None)
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

    # Metadata only: status, confidence, and a count of non-null fields — NEVER
    # the extracted values (income, employer, names are all PII).
    fields_present = sum(1 for v in result.data.model_dump().values() if v is not None)
    logger.info(
        "paystub_extraction_done",
        status=result.status,
        confidence=result.confidence,
        fields_present=fields_present,
    )
    return result
