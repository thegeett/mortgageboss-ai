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
    AsyncAnthropicBedrock,
)

# LP-625 — the worker's out-of-time signal, so it can be let through rather than retyped (see the
# handler in `complete`). This is the only Celery coupling in the AI layer, and it is a deliberate one:
# the signal ORIGINATES in the worker that runs these calls, and a module that swallows it silently
# defeats its own task's time limit. Importing it costs nothing outside a worker — the request path
# simply never raises it.
from celery.exceptions import SoftTimeLimitExceeded

from app.ai.rate_limit import get_rate_limiter
from app.core.config import ModelResolutionError, resolve_model, settings

logger = structlog.get_logger(__name__)

# HTTP status codes we treat as transient (worth retrying). 429 = rate limited;
# anything >= 500 is a server-side error. Everything else (400/401/403/404/422…)
# is a deterministic client error and is NOT retried.
_RATE_LIMIT_STATUS = 429
_SERVER_ERROR_FLOOR = 500
_BAD_REQUEST_STATUS = (
    400  # LP-462: an over-limit document payload comes back as a 400 BadRequestError
)


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
    # LP-628 review — THE CACHED HALVES OF THE PROMPT, carried rather than only logged.
    #
    # `input_tokens` is the UNCACHED REMAINDER once caching is in play, so on the chunked path — the
    # one caching was introduced for — it excludes almost the entire document: chunk 1 bills its bytes
    # as a cache WRITE and every later chunk as a cache READ, and neither appeared here. The caller
    # computes `tokens_used` and `cost_estimate` from `input_tokens` alone, so a 3-chunk statement
    # stored a cost roughly an order of magnitude below what it actually cost. The diff that added
    # caching also fixed a token-summing bug for exactly this reason; this is the same bug one layer
    # down.
    #
    # Zero on both is the honest reading for an uncached call, and also for a cached one whose prefix
    # fell under the model's cache minimum — which is a real no-op worth being able to see.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def billed_input_tokens(self) -> int:
        """Every input token the provider charged for, at any rate — the size a cost must start from.

        Kept as a property rather than folded into `input_tokens`: the three are billed at DIFFERENT
        rates (a cache write is ~1.25x, a read ~0.1x), so a consumer that needs a cost has to see them
        apart, and one that only needs a payload size has one number to ask for.
        """
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens


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


def build_document_block(*, content: bytes, media_type: str, cache: bool = False) -> dict[str, Any]:
    """Build a base64 ``document`` (PDF) or ``image`` (JPEG/PNG) content block.

    The block shape is verified against the installed anthropic SDK (0.109.1):
    a PDF becomes ``{"type": "document", "source": {"type": "base64",
    "media_type": "application/pdf", "data": <b64>}}`` and an image the
    equivalent ``{"type": "image", ...}``. ``image/jpg`` is normalized to
    ``image/jpeg``. An unsupported media type raises :class:`ValueError`.

    The bytes are base64-encoded (utf-8 decoded for JSON). The base64 payload is
    document content (borrower PII) — it is **never** logged.

    ``cache=True`` marks this block as a prompt-cache breakpoint (LP-628), so the prefix
    ``system`` + this document is written to cache on the first call and read back on
    later calls that repeat it byte-for-byte. Only the CHUNKED extraction path sets it,
    because that is the only path that deliberately sends one document more than once
    (once per page range, with only the trailing instruction differing).

    Placement is deliberate and load-bearing. Bedrock evaluates the cache minimum against
    the CUMULATIVE ``tools`` → ``system`` → ``messages`` prefix, not per section, and for
    Haiku 4.5 that minimum is **4,096 tokens**. Our largest extraction system prompt is
    ~3,120 tokens, so a breakpoint on the system block alone would be under the minimum and
    would silently cache NOTHING — no error, ``cache_creation_input_tokens: 0``. Marking the
    document block instead puts system + document (~34K) behind one breakpoint, far above
    the minimum, and leaves the per-chunk instruction after it where it belongs.
    """
    mt = _normalize_media_type(media_type)
    data = base64.standard_b64encode(content).decode("utf-8")
    if mt == _PDF_MEDIA_TYPE:
        block: dict[str, Any] = {
            "type": "document",
            "source": {"type": "base64", "media_type": _PDF_MEDIA_TYPE, "data": data},
        }
    elif mt in _IMAGE_MEDIA_TYPES:
        block = {
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": data},
        }
    else:
        raise ValueError(f"Unsupported media type for AI document input: {media_type!r}")
    if cache:
        # Explicit per-block marker, NOT the top-level auto-placement convenience field — that
        # field is exposed only on the newest Bedrock models and is rejected on Haiku 4.5.
        block["cache_control"] = {"type": "ephemeral"}
    return block


def build_document_message(
    *, content: bytes, media_type: str, instruction: str | None = None, cache: bool = False
) -> dict[str, Any]:
    """Assemble a ``user`` message carrying a document/image block + optional text.

    The content is a list ``[<document/image block>, {"type": "text", "text":
    instruction}]`` (the text block is omitted when ``instruction`` is empty/None).
    Callers pass the returned dict straight into ``complete(messages=[...])``;
    standalone instructions can also go in ``complete(system=...)``.

    ``cache=True`` puts a prompt-cache breakpoint on the document block (see
    :func:`build_document_block`). The instruction block deliberately sits AFTER it, so a
    per-chunk instruction can vary freely without invalidating the cached prefix.
    """
    blocks: list[dict[str, Any]] = [
        build_document_block(content=content, media_type=media_type, cache=cache)
    ]
    if instruction:
        blocks.append({"type": "text", "text": instruction})
    return {"role": "user", "content": blocks}


@lru_cache(maxsize=1)
def get_anthropic_client() -> AsyncAnthropic | AsyncAnthropicBedrock:
    """The shared singleton async client for the ACTIVE provider (lazy, cached — LP-35 style).

    ``settings.ai_provider`` selects the construction and nothing else changes: both
    clients expose the same ``messages.create`` surface and return the same response
    shape, so :func:`complete` and all 13 callers are provider-agnostic.

    The missing-key check below is now **defence in depth, not the primary gate**. It used
    to be the only check, firing at first *use*; B1's ``Settings._require_provider_credentials``
    moved the real one to settings construction, so under ``ai_provider="anthropic"`` a
    missing key refuses to start the app and this branch is unreachable in production. It is
    kept for tests and any direct construction that bypasses that validator — but a reader
    chasing "where does a missing key surface?" should look at the settings validator first.

    Under ``bedrock`` there is no key at all: credentials come from the AWS provider chain
    (SSO locally, task role on ECS), which is why ``anthropic_api_key`` is only conditionally
    required.

    The wrapper owns retries, so the SDK's built-in retries stay disabled
    (``max_retries=0``) for BOTH providers — otherwise the SDK would retry inside our
    retry, multiplying attempts invisibly and, on Bedrock, burning a 10 RPM quota.

    **Caching is safe for both providers, verified rather than assumed (B1):**

    * *Event loops.* The original measurement here was too gentle, and it shipped a bug
      (LP-636 defect 1). It read: "httpx re-establishes a pooled connection whose loop has
      gone rather than raising. Measured: one client instance issuing SUCCESSFUL requests
      across three separate ``asyncio.run()`` loops returned 200 each time."

      httpx does NOT re-establish it. A pooled keep-alive connection whose loop has been
      closed raises ``RuntimeError: Event loop is closed`` when the next caller takes it,
      which the SDK surfaces as ``APIConnectionError``. The three-loop test passed because
      the SDK pool sets ``keepalive_expiry=5.0``: three sequential calls, each slow enough
      to clear five seconds, never reuse a connection. The bug needs consecutive calls
      INSIDE that window — a burst, which is exactly when it matters. On staging it cost
      5 of 44 documents in one upload.

      **The cache is scoped to the TASK, not the process.** :func:`run_async`
      (``app/tasks/base.py``) closes and clears this client inside the loop it belongs to,
      before that loop ends, so a client never outlives its loop — while pooling stays ON
      WITHIN a task, which is where it earns its keep: one verification run makes hundreds
      of calls on a single loop, and a handshake per call would be paid hundreds of times.

      This is the shape ``task_session`` already uses for the database — a fresh engine per
      task, disposed at the end — rather than one cached forever with pooling disabled.
      ``tests/ai/test_client_event_loops_lp636.py`` fails if the boundary is removed.
    * *Credential refresh.* ``AsyncAnthropicBedrock`` signs **per request** (its
      ``_prepare_request`` calls the SigV4 signer), and the cached ``boto3.Session`` it
      signs with resolves credentials through the provider chain, so a rotating ECS task
      role refreshes normally. A cached client does not pin expiring credentials.
    * *Fork.* The factory is lazy, and Celery forks before any task runs, so each child
      builds its own client — as today.

    Tests that flip ``ai_provider`` must call ``get_anthropic_client.cache_clear()``; the
    cache is keyed on nothing, so a stale client would otherwise survive the flip.
    """
    if settings.ai_provider == "bedrock":
        # ⚠️ PASS THE PROFILE EXPLICITLY (LP-491). The SDK otherwise resolves credentials from the
        # default chain, which reads AWS_PROFILE from the ENVIRONMENT — it does not know about
        # `settings.aws_profile`. Until now only the bench engine exported it (dev/bench/engine.py), so
        # EVERY OTHER ENTRY POINT — a script, a Celery task, a self-consistency harness — got
        # "could not resolve credentials from session", the AI call failed, and the producer failed
        # CLOSED to `unknown` for every subject. That is silent: a broken pipeline and a
        # confidently-abstaining one look identical downstream, and it cost LP-490a four derivation runs
        # that scored a perfect 1.0000 while calling nothing at all.
        #
        # ⚠️ PASSED AS AN ARGUMENT, NOT EXPORTED TO os.environ — the first fix did the latter and broke
        # 22 tests: a process-wide AWS_PROFILE leaks into every other boto3 client (S3 storage included)
        # and persists across tests. Scope the credential to the client that needs it.
        return AsyncAnthropicBedrock(
            aws_region=settings.bedrock_region,
            aws_profile=settings.aws_profile,  # None → the default chain, unchanged
            max_retries=0,
        )
    if not settings.anthropic_api_key:
        raise AIClientError("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=0)


async def close_anthropic_client() -> None:
    """Close the cached client and forget it. **Await this INSIDE the loop that built it.**

    LP-636 defect 1. The client is cached for reuse, but its connection pool belongs to the event
    loop that opened those connections. ``run_async`` gives every Celery task a fresh loop and
    closes it at the end, so a client that survives the task hands the next one a dead socket:
    ``RuntimeError: Event loop is closed``, surfaced as ``APIConnectionError`` in 1-5ms.

    Called from ``run_async``'s ``finally``, still inside the loop — ``close()`` is a coroutine and
    has to shut its transports down while their loop is alive. Closing after ``asyncio.run``
    returns would be too late, and would leak the sockets it meant to release.

    A no-op when nothing was cached, so the many tasks that never make an AI call pay nothing —
    and it must not CONSTRUCT a client merely to close one.
    """
    if get_anthropic_client.cache_info().currsize == 0:
        return
    client = get_anthropic_client()
    get_anthropic_client.cache_clear()
    await client.close()


#: Bedrock error codes that mean "try again shortly", matched on the SDK exception's
#: message/body when the HTTP status alone does not already say so (B1, task 4).
#:
#: ``ThrottlingException`` is the quota case — at a 10 RPM account it is the COMMON path,
#: not an edge case, so misclassifying it as a hard client error would fail the majority
#: of a burst instead of retrying it. ``ModelNotReadyException`` and
#: ``ServiceUnavailableException`` are capacity pressure, equally retryable.
#:
#: This is a NARROW addition on purpose: it does not relax the 4xx-fails-fast rule for
#: genuine client errors (a malformed request, a bad model id, a denied IAM action all
#: still fail immediately). Only these named codes are promoted.
_BEDROCK_TRANSIENT_CODES = (
    "throttlingexception",
    "modelnotreadyexception",
    "serviceunavailableexception",
    "toomanyrequestsexception",
)


def _looks_like_bedrock_throttle(exc: BaseException) -> bool:
    """True when an SDK exception carries one of the retryable Bedrock error codes.

    Bedrock's throttle SHOULD arrive as HTTP 429, which ``_is_transient`` already treats
    as transient. This is the belt-and-braces path for the case where it does not — the
    exact behaviour is pending empirical confirmation (``scripts/verify-bedrock.py``
    step 3 prints the real type and status). Matching on the code string means the
    classification is correct either way, rather than resting on an assumption about the
    status code.
    """
    # The exception TYPE name and message, plus — for an APIStatusError — the response
    # body. Bedrock puts the error code in the body (``{"message": "ThrottlingException:
    # ..."}``) while ``str(exc)`` is only the SDK's summary line, so matching on the
    # message alone would miss the very case this exists for.
    parts = [type(exc).__name__, str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(str(body))
    text = " ".join(parts).lower()
    return any(code in text for code in _BEDROCK_TRANSIENT_CODES)


def _is_transient(exc: Exception) -> bool:
    """True for retryable errors: rate limit (429), 5xx, connection, or timeout.

    Uses the SDK's exception hierarchy: :class:`APIConnectionError` (which
    includes ``APITimeoutError``) is always transient; an :class:`APIStatusError`
    is transient only for 429 or a 5xx status. Any other error — including the
    4xx client errors (``BadRequestError`` 400, ``AuthenticationError`` 401,
    ``PermissionDeniedError`` 403, ``NotFoundError`` 404) — is NOT transient and
    fails fast.

    Two additions (B1):

    * :class:`TimeoutError` — :func:`complete` now bounds every attempt with
      ``asyncio.wait_for``, and a timeout is a network-class failure, so the existing
      retry loop should cover it exactly as it covers a connection error.
    * Bedrock throttling / capacity codes — see :func:`_looks_like_bedrock_throttle`.
    """
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        if exc.status_code == _RATE_LIMIT_STATUS or exc.status_code >= _SERVER_ERROR_FLOOR:
            return True
        return _looks_like_bedrock_throttle(exc)
    return _looks_like_bedrock_throttle(exc)


#: The infrastructure-outcome tags :func:`infra_failure_kind` returns — a call that never completed, by cause.
INFRA_RATE_LIMITED = "rate_limited"
INFRA_OVERSIZED = "oversized"
INFRA_FAILED = "failed"


def infra_failure_kind(err: AIClientError) -> str:
    """Classify a caught :class:`AIClientError` by its underlying cause, for observability + routing (LP-462).

    ``complete`` raises ``AIClientError(...) from exc``, so the ORIGINAL SDK exception is on ``__cause__``.
    Returns ``INFRA_RATE_LIMITED`` for a throttle/transient cause (429, Bedrock throttle codes, 5xx,
    connection/timeout — the same test the retry loop and the bench use), ``INFRA_OVERSIZED`` for an HTTP 400
    (a payload/bad-request rejection — an over-limit document is the case LP-462 fixes), or ``INFRA_FAILED``
    for anything else (auth, permission, an exhausted non-throttle, …). This lets a caller record a THROTTLE
    distinctly from a JUDGMENT: a throttled document persisted as "low confidence" would read as a coverage
    gap and corrupt every downstream audit. Keeps SDK-exception knowledge in this module, beside
    ``_is_transient``.
    """
    cause = err.__cause__
    if isinstance(cause, Exception) and _is_transient(cause):
        return INFRA_RATE_LIMITED
    # An HTTP 400 is a request-shape rejection; for a document call that is an over-limit payload (>100 pages
    # / >32 MB). Not transient — the page cap is the fix, not a retry.
    if isinstance(cause, APIStatusError) and cause.status_code == _BAD_REQUEST_STATUS:
        return INFRA_OVERSIZED
    return INFRA_FAILED


#: Canonical truncation marker. ``app/ai/extraction/model_call.py`` compares
#: ``stop_reason == "max_tokens"`` to fire the LP-102 truncation guard; if a provider
#: spelled it differently the guard would silently stop working and a cut-off response
#: would be misreported as "could not parse extraction" — the exact bug LP-102 exists to
#: prevent.
TRUNCATED_STOP_REASON = "max_tokens"

#: Provider spellings folded onto the canonical values. Normalising HERE — at the one
#: place an SDK response becomes an :class:`AICompletion` — keeps provider knowledge out
#: of ``model_call.py`` and out of all 13 callers.
#:
#: ⚠️ PENDING EMPIRICAL CONFIRMATION (B1 task 5). The Anthropic SDK's Bedrock client
#: returns the Messages API shape, so ``stop_reason`` is EXPECTED to be identical
#: ("max_tokens" / "end_turn" / "stop_sequence" / "tool_use"). That expectation is not
#: yet verified against a live call — ``scripts/verify-bedrock.py`` step 2 forces a
#: truncation and prints the exact string. If it differs, add the alias here and nowhere
#: else; the map is empty today because inventing speculative aliases would be a guess
#: dressed as a fix.
_STOP_REASON_ALIASES: dict[str, str] = {}


def _normalize_stop_reason(raw: str | None) -> str | None:
    """Fold a provider's stop reason onto the canonical vocabulary (B1)."""
    if raw is None:
        return None
    return _STOP_REASON_ALIASES.get(raw, raw)


def _backoff_delay(*, attempt: int, base_delay: float) -> float:
    """Exponential backoff with full jitter for ``attempt`` (1-based).

    ``base_delay * 2**(attempt-1)`` scaled by a random factor in ``[0.5, 1.5)`` so
    concurrent callers don't retry in lockstep (thundering herd).
    """
    delay = base_delay * (2 ** (attempt - 1))
    return float(delay * (0.5 + random.random()))


async def _stream_final_message(client: Any, kwargs: dict[str, Any]) -> Any:
    """Open a streamed completion and return the assembled final ``Message`` — identical in shape to a
    non-streaming response (``.content`` / ``.usage`` / ``.stop_reason``). Isolated so ``complete`` can
    wrap it in a single ``asyncio.wait_for`` bound and so the test seam can replace it wholesale."""
    async with client.messages.stream(**kwargs) as stream:
        return await stream.get_final_message()


def _stream_timeout(max_tokens: int) -> float:
    """Per-attempt wall-clock bound for a STREAMING call.

    Streaming removes the SDK's non-streaming ceiling (it refuses a one-shot request whose worst-case
    time could exceed 10 min — ``max_tokens > 21,333``), but we still bound each attempt so a genuinely
    hung stream cannot hold a worker forever. Scale the bound to ``max_tokens`` using the SDK's own
    conservative rate (128K tokens/hour) plus margin, floored at the configured request timeout — so a
    small call keeps a tight ~60 s bound while a dense extraction/retry gets the minutes it needs."""
    est_seconds = max_tokens / 128_000 * 3600
    return max(settings.ai_request_timeout_seconds, est_seconds + 30.0)


async def complete(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    system: str | None = None,
    temperature: float | None = None,
) -> AICompletion:
    """Make a Claude completion call through the wrapper, using the SDK's STREAMING API.

    Streaming (rather than one-shot) is deliberate: the SDK refuses a non-streaming request whose
    worst-case duration could exceed 10 minutes (``max_tokens > 21,333`` → ``ValueError``), which the
    LP-102 truncation guard's high-ceiling retry (``RETRY_MAX_TOKENS``) trips on dense documents. A
    streamed connection never idles, so there is no such ceiling; the assembled final message is
    identical to the one-shot response, so callers see no difference.

    Retries transient failures with exponential backoff + jitter up to ``settings.ai_max_retries``
    attempts; fails fast on non-transient errors. Logs metadata only (never prompt/response content).
    Raises :class:`AIClientError` on a non-retryable error or once retries are exhausted, wrapping the
    underlying SDK exception as the cause.

    ``model`` is the caller's TIER value (one of the three ``anthropic_model_*`` settings). Under
    ``ai_provider="bedrock"`` it is translated to that tier's Bedrock inference-profile id here, so no
    caller knows which provider is active (B1).

    Every ATTEMPT — not merely every call — is paced by the process-local rate limiter and bounded by
    :func:`_stream_timeout` (scaled by ``max_tokens``). Per attempt because a retry is a fresh request
    that counts against the provider quota just as the first did, and because a hung attempt would
    otherwise hold a Celery worker slot indefinitely.
    """
    client = get_anthropic_client()
    max_attempts = max(1, settings.ai_max_retries)
    base_delay = settings.ai_base_retry_delay_seconds
    timeout_s = _stream_timeout(max_tokens)
    limiter = get_rate_limiter()

    try:
        resolved_model = resolve_model(model)
    except ModelResolutionError as exc:
        # Fail before spending an attempt: under Bedrock an unmapped model is rejected at
        # invoke time anyway, and this says why instead of surfacing a validation error.
        raise AIClientError(str(exc)) from exc

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if system is not None:
        kwargs["system"] = system
    if temperature is not None:
        kwargs["temperature"] = temperature

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        # Bound before the try so the handler below can always compute a latency, even if
        # pacing itself is what failed.
        start = time.perf_counter()
        try:
            # Pace BEFORE sending: a rejected request still counts against the provider's
            # quota, so retry-after-throttle spends allowance to learn nothing.
            #
            # INSIDE the try deliberately. Callers are written against the contract that
            # everything leaving complete() is an AIClientError — rule_engine/judgment.py
            # catches only that, in order to fail ONE subject closed. A raw exception from
            # pacing would slip past that handler and abort the whole verification run.
            await limiter.acquire(label="complete")
            # Re-stamp so the latency metric measures the provider call, not the queueing.
            start = time.perf_counter()
            # STREAMING: assemble the final message from a streamed connection (no non-streaming
            # 10-min/max_tokens ceiling). The final Message is identical to a one-shot response.
            resp = await asyncio.wait_for(_stream_final_message(client, kwargs), timeout=timeout_s)
        except SoftTimeLimitExceeded:
            # LP-625 (corrected) — THE ONE EXCEPTION TO THE "everything leaves as AIClientError"
            # CONTRACT ABOVE, and it has to be, because this is not an error at all: it is the worker
            # telling us the task is out of time. Wrapping it as an AIClientError made it indistinguishable
            # from a provider failure, so the caller recorded a failed extraction and the task returned
            # SUCCESS — which is precisely why `terminal_on=(SoftTimeLimitExceeded,)` on the document
            # tasks could never fire. A soft limit is most likely to land mid-extraction, i.e. here.
            #
            # Retrying is equally wrong: the deadline has passed, so an attempt made after it cannot
            # finish either, and `_is_transient` had no opinion on a class it never expected to see.
            # Re-raised BEFORE the handler below so neither the retype nor the backoff can reach it.
            raise
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
        stop_reason = _normalize_stop_reason(getattr(resp, "stop_reason", None))
        # LP-628 — prompt-cache accounting. Absent on responses that used no caching, and absent
        # from older/stub usage objects, so both read through getattr with a 0 default rather than
        # assuming the fields exist. NOTE `input_tokens` is the UNCACHED REMAINDER once caching is
        # in play: the true prompt size is input + cache_read + cache_creation. Anything reasoning
        # about payload size (or comparing against a previous run) must add all three.
        cache_read = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
        # METADATA ONLY — token counts, timing, finish reason; never the content.
        logger.info(
            "ai_call_succeeded",
            model=resolved_model,
            provider=settings.ai_provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # Zero on BOTH when a marker was sent means the prefix fell under the model's cache
            # minimum — the silent no-op this path is designed to make visible.
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            latency_ms=latency_ms,
            attempt=attempt,
            stop_reason=stop_reason,
        )
        return AICompletion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # The model that ACTUALLY ran, not the tier value the caller asked for — this
            # is what a cost estimate and a persisted ``model_used`` should reflect.
            model=resolved_model,
            stop_reason=stop_reason,
            # LP-628 review — carried, not merely logged. These were read for the log line and then
            # dropped, so every consumer's cost estimate excluded the bulk of a cached call's input.
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )

    # Unreachable: the loop either returns or raises. Belt-and-suspenders for mypy.
    raise AIClientError("AI call failed: retries exhausted") from last_exc
