"""Document classification (LP-38).

Given a document's **bytes** (PDF or image), decide what KIND of document it is
— ``pay_stub``, ``bank_statement``, ``w2``, … — with a confidence and a short
reasoning. The **full document** is sent to the Haiku-class model for **native
reading** (no OCR, no pre-extracted text) via the LP-37 document/image content
block (LP-37 revision, ADR-126). This is the first act of the system
"understanding" a document; classification routes extraction (LP-39 extracts
type-specifically, so the type must be known first).

Two design rules matter here:

  * **Graceful failure** — AI is probabilistic and its dependencies fail.
    :func:`classify_document` NEVER raises: any failure (AI error, malformed
    output, empty/unsupported document) returns ``ClassificationResult.unknown(...)``
    at **zero** confidence, which the pipeline (LP-42) routes to ``NEEDS_REVIEW``
    — a far better outcome than crashing on one document. Note the distinction
    (LP-59): a *low-confidence* result (the model is unsure which known type) →
    ``NEEDS_REVIEW``; a *high-confidence* ``unknown`` (the model is confident it
    is none of the known types) → Tier 3 (the generic analyzer). Confidence, not
    the ``unknown`` slug alone, decides.
  * **Privacy** — the document bytes (and their base64) and the model's raw
    response carry borrower PII, so they are **never** logged. Only metadata (the
    classified type and confidence) is logged here; the wrapper logs call
    metadata (tokens/latency).

``document_type`` is a flexible string (LP-15), not an enum — the taxonomy is
large and evolving (Phase 2). This module returns a result; persisting it onto
the ``Document`` is the pipeline's job (LP-42).
"""

import json
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

from app.ai.classification_prompt import render_classification_prompt
from app.ai.client import (
    AIClientError,
    build_document_message,
    complete,
    infra_failure_kind,
)
from app.ai.parsing import coerce_confidence, extract_json_object
from app.core.config import settings
from app.services.pdf_utils import fit_pdf_to_payload_budget

logger = structlog.get_logger(__name__)

# Media types we can send to the model (matches the LP-36 upload allowlist and
# the LP-37 document-block support); ``image/jpg`` is normalized to image/jpeg.
_SUPPORTED_MEDIA_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/jpg"})
# Classification output is a tiny JSON object; cap tokens low.
_MAX_TOKENS = 512


class ClassificationResult(BaseModel):
    """The outcome of classifying one document.

    ``document_type`` is a flexible lowercase slug (``"unknown"`` when unsure);
    ``confidence`` is clamped to ``[0, 1]``; ``reasoning`` is a short human note.
    ``category`` is the model's ADVISORY category (LP-59) — the authoritative
    category persisted on the document is the catalog's (``get_category``), so the
    two never drift; this is kept for observability/cross-check and may be ``None``.
    """

    document_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    category: str | None = None
    #: LP-463 — the model's free-text name for what the document ACTUALLY is, produced BEFORE it picks a
    #: type (a more reliable signal than the constrained pick; on 158 the name "wiring instructions from a
    #: law firm" was right while the pick was not). On an ``unknown`` this names the missing catalog type.
    document_name: str | None = None
    #: LP-463 — the model's self-check: does ``document_type`` faithfully describe ``document_name``? False =
    #: the model applied a type it knows does NOT fit (the T4→w2 harm). The pipeline flags a False for review
    #: rather than trusting the label. Defaults True (no contradiction) when the model didn't answer, so an
    #: older/degraded response never spuriously flags.
    type_matches_document: bool = True
    #: LP-462 — set ONLY when the model call never completed for an infrastructure reason: "rate_limited"
    #: (throttled) or "oversized" (payload over the 100-page/32 MB document limit), else "failed" for another
    #: AI error, else None (a genuine classification, including a low-confidence/unknown JUDGMENT). This is
    #: the throttled-vs-failed distinction: a throttled document must NEVER be recorded as a low-confidence
    #: judgment — that reads as a coverage gap and corrupts every downstream audit. The document is
    #: re-runnable, not a schema finding.
    infra_failure: str | None = None

    @classmethod
    def unknown(cls, reason: str, *, infra_failure: str | None = None) -> "ClassificationResult":
        """The graceful fallback: an ``unknown`` type at zero confidence (LP-462: with an optional
        infrastructure-outcome tag when the call never completed — throttle / oversize / other AI error)."""
        return cls(
            document_type="unknown", confidence=0.0, reasoning=reason, infra_failure=infra_failure
        )


def _parse_classification_json(text: str) -> ClassificationResult | None:
    """Defensively parse a model response into a :class:`ClassificationResult`.

    Handles fenced / preambled JSON (``extract_json_object``), clamps
    ``confidence`` into ``[0, 1]``, and treats a missing/empty ``document_type``
    as ``"unknown"``. Returns ``None`` (→ the caller produces the unknown
    fallback) on any malformed input; never raises.
    """
    snippet = extract_json_object(text)
    if snippet is None:
        return None
    try:
        data: Any = json.loads(snippet)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    raw_type = data.get("document_type")
    document_type = (
        raw_type.strip() if isinstance(raw_type, str) and raw_type.strip() else "unknown"
    )

    confidence = coerce_confidence(data.get("confidence"))

    raw_reasoning = data.get("reasoning")
    reasoning = raw_reasoning if isinstance(raw_reasoning, str) else ""

    raw_category = data.get("category")
    category = (
        raw_category.strip().lower()
        if isinstance(raw_category, str) and raw_category.strip()
        else None
    )

    # LP-463 — the free-text document name (named first) + the self-check.
    raw_name = data.get("document_name")
    document_name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    # ``type_matches_document`` flags an admitted mismatch. Default TRUE and only an EXPLICIT negative flags:
    # a missing/garbled value must not spuriously send a good classification to review (the guard fails SAFE
    # toward trusting the label, since the mismatch case is the model volunteering "this does not fit"). Accept
    # the negative in any common shape — JSON ``false``, or a stringified ``"false"``/``"no"``/``"0"`` — so a
    # model formatting slip cannot silently defeat the guard (the T4→w2 harm it exists to catch).
    raw_match = data.get("type_matches_document")
    if isinstance(raw_match, str):
        type_matches_document = raw_match.strip().lower() not in {"false", "no", "n", "0"}
    else:
        type_matches_document = raw_match not in (False, 0)

    try:
        return ClassificationResult(
            document_type=document_type,
            confidence=confidence,
            reasoning=reasoning,
            category=category,
            document_name=document_name,
            type_matches_document=type_matches_document,
        )
    except ValidationError:
        return None


async def classify_document(content: bytes, media_type: str) -> ClassificationResult:
    """Classify a document from its raw bytes (PDF/image). Never raises.

    An empty or unsupported document short-circuits to ``unknown`` without an API
    call. Otherwise it builds the comprehensive classification prompt from the
    document-type catalog (LP-59 ``render_classification_prompt`` — all ~80 types
    + their indicators), sends the **full document** to the Haiku-class model as a
    document/image content block (LP-37 ``build_document_message``), and parses
    the response defensively. Any AI error or unparseable output returns
    ``ClassificationResult.unknown``. The document bytes/base64 and raw response
    are never logged (PII).
    """
    if not content or media_type.lower().strip() not in _SUPPORTED_MEDIA_TYPES:
        return ClassificationResult.unknown("empty or unsupported document")

    # LP-462 — classification identifies the LEAD document and needs only its first pages; sending the whole
    # PDF made a >100-page package exceed the document-block limit (Bedrock → BadRequestError). Trim to the
    # first ``classification_max_pages`` pages (classification-only — extraction still reads the whole doc).
    # LP-636 defect 4 — the page cap alone was not enough. LF-ZE9N's 23.8 MB contract was already
    # INSIDE this 15-page cap (a high-DPI scan), so the cap was a no-op and the call was rejected
    # on encoded SIZE with HTTP 400. Pages first, then bytes.
    fit = await fit_pdf_to_payload_budget(
        content, media_type, max_pages=settings.classification_max_pages
    )
    payload = fit.payload

    system_prompt = render_classification_prompt()
    try:
        # build_document_message base64-encodes the bytes into a document/image
        # block; it raises ValueError on an unsupported type (already filtered).
        message = build_document_message(content=payload, media_type=media_type)
    except ValueError:
        return ClassificationResult.unknown("unsupported document media type")

    try:
        result = await complete(
            model=settings.anthropic_model_classification,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError as err:
        # LP-462 — distinguish a call that never COMPLETED (throttle / oversize / other AI error) from a
        # judgment. A throttled document recorded as low-confidence would look like a coverage gap; here it
        # is tagged infrastructure and stays re-runnable. Metadata only — never bytes/content.
        kind = infra_failure_kind(err)
        logger.warning("classification_ai_failed", infra_failure=kind)
        return ClassificationResult.unknown("AI call failed", infra_failure=kind)

    parsed = _parse_classification_json(result.text)
    if parsed is None:
        logger.warning("classification_parse_failed")  # no raw response logged
        return ClassificationResult.unknown("could not parse classification")

    # Metadata only: the classified type, confidence, + advisory category, + the LP-463 self-check flag
    # (a boolean, safe to log) — never the bytes/response, and never ``document_name`` (free text that may
    # name a party, PII-adjacent like ``reasoning``).
    logger.info(
        "classification_succeeded",
        document_type=parsed.document_type,
        confidence=parsed.confidence,
        model_category=parsed.category,
        type_matches_document=parsed.type_matches_document,
    )
    return parsed
