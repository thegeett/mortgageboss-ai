"""Anthropic async client wrapper (LP-37).

The single gateway for every Claude API call. It owns the cross-cutting
concerns so the AI features — document classification (LP-38) and extraction
(LP-39) — call :func:`complete` and focus on their own logic:

  * a lazily-initialized, shared singleton :class:`AsyncAnthropic` (mirroring the
    LP-35 storage factory style);
  * **transient-only** retries with exponential backoff + jitter and a max-attempts
    cap — rate limits (429), server errors (5xx), and connection/timeout errors are
    retried; other 4xx (400/401/403/404/422) fail fast;
  * latency timing and **structured logging of call METADATA only** — model, token
    counts, latency, attempt, outcome, error type. The prompt and response CONTENT
    are **never** logged: they carry borrower PII (pay-stub / bank-statement data).
    Content logging, if ever added, would be a redacted, debug-only option.
  * surfacing token **usage** so callers can record an estimated cost
    (:mod:`app.ai.cost`).

The wrapper owns the retry policy: the SDK's own retries are disabled
(``max_retries=0``) so there is a single, observable retry authority here.

**Document/image input (LP-37 revision).** Classification (LP-38) and extraction
(LP-39) send the **full document** (PDF / image bytes) for native reading — no
OCR, no pre-extracted text. :func:`build_document_block` / :func:`build_document_message`
build the base64 content blocks; :func:`complete` forwards ``messages`` to the SDK
unchanged, so document-bearing messages use the **same** retry/logging/timing path
as text-only ones. The metadata-only logging covers this too: document bytes,
base64 data, message content, and response text are **never** logged.
"""

import asyncio
import base64
import random
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import structlog
from anthropic import (
    APIConnectionError,
    APIStatusError,
    AsyncAnthropic,
)

from app.core.config import settings

logger = structlog.get_logger(__name__)

# HTTP status codes we treat as transient (worth retrying). 429 = rate limited;
# anything >= 500 is a server-side error. Everything else (400/401/403/404/422…)
# is a deterministic client error and is NOT retried.
_RATE_LIMIT_STATUS = 429
_SERVER_ERROR_FLOOR = 500


class AIClientError(Exception):
    """An AI call failed — either non-retryably, or after exhausting retries.

    Wraps the underlying SDK exception as ``__cause__`` (via ``raise ... from``)
    so callers (LP-38/39) can inspect the cause while catching one wrapper type.
    """


@dataclass(frozen=True)
class AICompletion:
    """The result of a successful completion call.

    Carries the concatenated text plus token usage so callers can both use the
    output and record an estimated cost. ``stop_reason`` is the model's finish
    reason (e.g. ``"end_turn"``, ``"max_tokens"``) so callers can detect a
    truncated response instead of silently parsing a cut-off body. No raw SDK
    objects leak out.
    """

    text: str
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str | None = None


# --------------------------------------------------------------------------- #
# Document / image content blocks (LP-37 revision)
# --------------------------------------------------------------------------- #

_PDF_MEDIA_TYPE = "application/pdf"
# Image media types we accept — matches the LP-36 upload allowlist (PDF/JPEG/PNG).
# The SDK also accepts image/gif and image/webp, but we don't ingest those.
_IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png"})


def _normalize_media_type(media_type: str) -> str:
    """Lowercase/trim a media type and fold the ``image/jpg`` alias to ``image/jpeg``."""
    mt = media_type.lower().strip()
    return "image/jpeg" if mt == "image/jpg" else mt


def build_document_block(*, content: bytes, media_type: str) -> dict[str, Any]:
    """Build a base64 ``document`` (PDF) or ``image`` (JPEG/PNG) content block.

    The block shape is verified against the installed anthropic SDK (0.109.1):
    a PDF becomes ``{"type": "document", "source": {"type": "base64",
    "media_type": "application/pdf", "data": <b64>}}`` and an image the
    equivalent ``{"type": "image", ...}``. ``image/jpg`` is normalized to
    ``image/jpeg``. An unsupported media type raises :class:`ValueError`.

    The bytes are base64-encoded (utf-8 decoded for JSON). The base64 payload is
    document content (borrower PII) — it is **never** logged.
    """
    mt = _normalize_media_type(media_type)
    data = base64.standard_b64encode(content).decode("utf-8")
    if mt == _PDF_MEDIA_TYPE:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": _PDF_MEDIA_TYPE, "data": data},
        }
    if mt in _IMAGE_MEDIA_TYPES:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": data},
        }
    raise ValueError(f"Unsupported media type for AI document input: {media_type!r}")


def build_document_message(
    *, content: bytes, media_type: str, instruction: str | None = None
) -> dict[str, Any]:
    """Assemble a ``user`` message carrying a document/image block + optional text.

    The content is a list ``[<document/image block>, {"type": "text", "text":
    instruction}]`` (the text block is omitted when ``instruction`` is empty/None).
    Callers pass the returned dict straight into ``complete(messages=[...])``;
    standalone instructions can also go in ``complete(system=...)``.
    """
    blocks: list[dict[str, Any]] = [build_document_block(content=content, media_type=media_type)]
    if instruction:
        blocks.append({"type": "text", "text": instruction})
    return {"role": "user", "content": blocks}


@lru_cache(maxsize=1)
def get_anthropic_client() -> AsyncAnthropic:
    """The shared singleton async client (lazy, cached — LP-35 factory style).

    The missing-key check fires here, at first *use*, not at import — so the app
    and the test suite load without a key, and only an actual AI call requires
    one. The wrapper owns retries, so the SDK's built-in retries are disabled
    (``max_retries=0``).
    """
    if not settings.anthropic_api_key:
        raise AIClientError("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)


def _is_transient(exc: Exception) -> bool:
    """True for retryable errors: rate limit (429), 5xx, or connection/timeout.

    Uses the SDK's exception hierarchy: :class:`APIConnectionError` (which
    includes ``APITimeoutError``) is always transient; an :class:`APIStatusError`
    is transient only for 429 or a 5xx status. Any other error — including the
    4xx client errors (``BadRequestError`` 400, ``AuthenticationError`` 401,
    ``PermissionDeniedError`` 403, ``NotFoundError`` 404) — is NOT transient and
    fails fast.
    """
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == _RATE_LIMIT_STATUS or exc.status_code >= _SERVER_ERROR_FLOOR
    return False


def _backoff_delay(*, attempt: int, base_delay: float) -> float:
    """Exponential backoff with full jitter for ``attempt`` (1-based).

    ``base_delay * 2**(attempt-1)`` scaled by a random factor in ``[0.5, 1.5)`` so
    concurrent callers don't retry in lockstep (thundering herd).
    """
    delay = base_delay * (2 ** (attempt - 1))
    return float(delay * (0.5 + random.random()))


async def complete(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    system: str | None = None,
    temperature: float | None = None,
) -> AICompletion:
    """Make a (non-streaming) Claude completion call through the wrapper.

    Retries transient failures with exponential backoff + jitter up to
    ``settings.ai_max_retries`` attempts; fails fast on non-transient errors.
    Logs metadata only (never prompt/response content). Raises
    :class:`AIClientError` on a non-retryable error or once retries are
    exhausted, wrapping the underlying SDK exception as the cause.
    """
    client = get_anthropic_client()
    max_attempts = max(1, settings.ai_max_retries)
    base_delay = settings.ai_base_retry_delay_seconds

    kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if system is not None:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        try:
            resp = await client.messages.create(**kwargs)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            transient = _is_transient(exc)
            # METADATA ONLY — never the prompt/response content (borrower PII).
            logger.warning(
                "ai_call_failed",
                model=model,
                latency_ms=latency_ms,
                attempt=attempt,
                max_attempts=max_attempts,
                error_type=type(exc).__name__,
                transient=transient,
            )
            last_exc = exc
            if not transient or attempt == max_attempts:
                raise AIClientError(f"AI call failed: {type(exc).__name__}") from exc
            await asyncio.sleep(_backoff_delay(attempt=attempt, base_delay=base_delay))
            continue

        latency_ms = int((time.perf_counter() - start) * 1000)
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        input_tokens = resp.usage.input_tokens
        output_tokens = resp.usage.output_tokens
        stop_reason = getattr(resp, "stop_reason", None)
        # METADATA ONLY — token counts, timing, finish reason; never the content.
        logger.info(
            "ai_call_succeeded",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            attempt=attempt,
            stop_reason=stop_reason,
        )
        return AICompletion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=stop_reason,
        )

    # Unreachable: the loop either returns or raises. Belt-and-suspenders for mypy.
    raise AIClientError("AI call failed: retries exhausted") from last_exc
