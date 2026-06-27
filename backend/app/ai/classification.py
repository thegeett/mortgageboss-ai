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
from app.ai.client import AIClientError, build_document_message, complete
from app.ai.parsing import coerce_confidence, extract_json_object
from app.core.config import settings

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

    @classmethod
    def unknown(cls, reason: str) -> "ClassificationResult":
        """The graceful fallback: an ``unknown`` type at zero confidence."""
        return cls(document_type="unknown", confidence=0.0, reasoning=reason)


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

    try:
        return ClassificationResult(
            document_type=document_type,
            confidence=confidence,
            reasoning=reasoning,
            category=category,
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

    system_prompt = render_classification_prompt()
    try:
        # build_document_message base64-encodes the bytes into a document/image
        # block; it raises ValueError on an unsupported type (already filtered).
        message = build_document_message(content=content, media_type=media_type)
    except ValueError:
        return ClassificationResult.unknown("unsupported document media type")

    try:
        result = await complete(
            model=settings.anthropic_model_classification,
            system=system_prompt,
            messages=[message],
            max_tokens=_MAX_TOKENS,
        )
    except AIClientError:
        logger.warning("classification_ai_failed")  # metadata only — no bytes/content
        return ClassificationResult.unknown("AI call failed")

    parsed = _parse_classification_json(result.text)
    if parsed is None:
        logger.warning("classification_parse_failed")  # no raw response logged
        return ClassificationResult.unknown("could not parse classification")

    # Metadata only: the classified type, confidence, + advisory category — never
    # the bytes/response.
    logger.info(
        "classification_succeeded",
        document_type=parsed.document_type,
        confidence=parsed.confidence,
        model_category=parsed.category,
    )
    return parsed
