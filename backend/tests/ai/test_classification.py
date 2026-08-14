"""Tests for document classification (LP-38) — the AI wrapper is MOCKED.

No real API calls and no key: ``complete`` is patched to return canned text or
raise. Classification now reads the **full document** (PDF/image bytes) natively
(LP-38 modification, LP-37 revision), so the tests pass bytes + a media type. The
focus is the module's contract — defensive JSON parsing, graceful ``unknown`` on
every failure, the empty/unsupported-document short-circuit, confidence clamping,
and the privacy rule that the document bytes/base64 / raw response are never
logged. Dummy bytes are fine (the SDK/wrapper is mocked).
"""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai import classification as classification_module
from app.ai.classification import (
    ClassificationResult,
    _parse_classification_json,
    classify_document,
)
from app.ai.client import AIClientError

# Dummy document bytes — the wrapper is mocked, so these need not be real files.
PDF_BYTES = b"%PDF-1.7 dummy pay stub bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy image bytes"


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    """Patch ``classify_document``'s ``complete`` with a canned response or error."""
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=100, output_tokens=20, model="m")
        )
    monkeypatch.setattr(classification_module, "complete", mock)
    return mock


# --------------------------------------------------------------------------- #
# _parse_classification_json (defensive parser)
# --------------------------------------------------------------------------- #


def test_parse_plain_json() -> None:
    result = _parse_classification_json(
        '{"document_type": "pay_stub", "confidence": 0.95, "reasoning": "has earnings"}'
    )
    assert result is not None
    assert result.document_type == "pay_stub"
    assert result.confidence == 0.95


def test_parse_json_in_markdown_fences() -> None:
    raw = 'Here you go:\n```json\n{"document_type": "w2", "confidence": 0.8, "reasoning": "boxes"}\n```\nThanks!'
    result = _parse_classification_json(raw)
    assert result is not None
    assert result.document_type == "w2"


@pytest.mark.parametrize("raw", ["not json at all", "", "{ broken", "[1, 2, 3]", "{}"])
def test_parse_malformed_returns_none_or_unknown(raw: str) -> None:
    result = _parse_classification_json(raw)
    # Either unparseable (None) or an empty object → document_type defaults unknown.
    assert result is None or result.document_type == "unknown"


@pytest.mark.parametrize(
    ("raw_conf", "expected"),
    [(1.5, 1.0), (-0.2, 0.0), ("0.42", 0.42), ("not a number", 0.0), (True, 0.0)],
)
def test_parse_clamps_and_coerces_confidence(raw_conf: object, expected: float) -> None:
    import json

    raw = json.dumps({"document_type": "pay_stub", "confidence": raw_conf, "reasoning": "x"})
    result = _parse_classification_json(raw)
    assert result is not None
    assert result.confidence == expected


def test_parse_missing_type_becomes_unknown() -> None:
    result = _parse_classification_json('{"confidence": 0.9, "reasoning": "no type field"}')
    assert result is not None
    assert result.document_type == "unknown"


def test_parse_captures_advisory_category() -> None:
    """LP-59: the model's category is parsed (advisory; the catalog is authoritative)."""
    result = _parse_classification_json(
        '{"document_type": "w2", "category": "Income_Employment", "confidence": 0.9,'
        ' "reasoning": "boxes 1-6"}'
    )
    assert result is not None
    assert result.category == "income_employment"  # stripped + lowercased


def test_parse_missing_category_is_none() -> None:
    result = _parse_classification_json(
        '{"document_type": "w2", "confidence": 0.9, "reasoning": "boxes"}'
    )
    assert result is not None
    assert result.category is None


# --------------------------------------------------------------------------- #
# classify_document
# --------------------------------------------------------------------------- #


async def test_success_returns_parsed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(
        monkeypatch,
        text='{"document_type": "pay_stub", "confidence": 0.95, "reasoning": "earnings + YTD"}',
    )
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.document_type == "pay_stub"
    assert result.confidence == 0.95
    assert mock.call_count == 1
    # Uses the classification model + sends a document block (not a text string).
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == classification_module.settings.anthropic_model_classification
    assert "system" in kwargs  # the prompt loaded from file
    message = kwargs["messages"][0]
    assert message["role"] == "user"
    block = message["content"][0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    # The forwarded base64 round-trips back to the original bytes.
    assert base64.standard_b64decode(block["source"]["data"]) == PDF_BYTES


async def test_image_input_uses_image_block(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(
        monkeypatch,
        text='{"document_type": "drivers_license", "confidence": 0.8, "reasoning": "photo id"}',
    )
    result = await classify_document(PNG_BYTES, "image/png")
    assert result.document_type == "drivers_license"
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"


async def test_success_with_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(
        monkeypatch,
        text='```json\n{"document_type": "bank_statement", "confidence": 0.7, "reasoning": "transactions"}\n```',
    )
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.document_type == "bank_statement"
    assert result.confidence == 0.7


async def test_low_confidence_returned_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """Low confidence is a valid result — the pipeline (not this module) flags review."""
    _mock_complete(
        monkeypatch,
        text='{"document_type": "w2", "confidence": 0.3, "reasoning": "uncertain"}',
    )
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.document_type == "w2"
    assert result.confidence == 0.3


async def test_malformed_response_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I think this is a pay stub, definitely.")
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.document_type == "unknown"
    assert result.confidence == 0.0
    assert "parse" in result.reasoning.lower()


async def test_ai_failure_returns_unknown_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.document_type == "unknown"
    assert result.confidence == 0.0
    assert "ai call failed" in result.reasoning.lower()


# --------------------------------------------------------------------------- #
# LP-462 — infrastructure-failure surfacing (throttled vs failed) + the page cap
# --------------------------------------------------------------------------- #


def _client_error(cause: Exception) -> AIClientError:
    """An AIClientError carrying ``cause`` on __cause__, as ``complete`` raises it (``from exc``)."""
    err = AIClientError(f"AI call failed: {type(cause).__name__}")
    err.__cause__ = cause
    return err


def _sdk_error(kind: str, status: int) -> Exception:
    """A real anthropic SDK error with the given HTTP status (for infra_failure_kind classification)."""
    import anthropic
    import httpx

    resp = httpx.Response(status, request=httpx.Request("POST", "http://x"))
    cls = {
        "rate": anthropic.RateLimitError,
        "bad": anthropic.BadRequestError,
        "auth": anthropic.AuthenticationError,
    }[kind]
    return cls(kind, response=resp, body=None)


async def test_throttle_tagged_rate_limited_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠️ A throttled classification must be DISTINGUISHABLE from a judgment — the corrupting bug LP-462
    fixes. It returns unknown/0.0 like any failure, but infra_failure='rate_limited' marks it re-runnable."""
    _mock_complete(monkeypatch, exc=_client_error(_sdk_error("rate", 429)))
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.document_type == "unknown" and result.confidence == 0.0
    assert result.infra_failure == "rate_limited"  # NOT a low-confidence judgment


async def test_oversized_tagged_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=_client_error(_sdk_error("bad", 400)))
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.infra_failure == "oversized"


async def test_other_ai_error_tagged_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=_client_error(_sdk_error("auth", 401)))
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.infra_failure == "failed"  # a real failure, but still not a judgment


async def test_throttle_log_carries_infra_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=_client_error(_sdk_error("rate", 429)))
    with structlog.testing.capture_logs() as logs:
        await classify_document(PDF_BYTES, "application/pdf")
    failed = [e for e in logs if e["event"] == "classification_ai_failed"]
    assert len(failed) == 1 and failed[0]["infra_failure"] == "rate_limited"


def _make_pdf(pages: int) -> bytes:
    """A real ``pages``-page PDF (each page carries a little text)."""
    import pymupdf

    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    return bytes(doc.tobytes())


def _payload_pages(mock: AsyncMock) -> int:
    """Decode the document block that was actually sent to ``complete`` and count its pages."""
    import base64 as _b64

    import pymupdf

    message = mock.await_args.kwargs["messages"][0]
    block = message["content"][0]
    data = _b64.b64decode(block["source"]["data"])
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return int(doc.page_count)
    finally:
        doc.close()


async def test_pdf_over_cap_is_sliced_to_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A >cap PDF is trimmed to classification_max_pages before the call — the BadRequestError fix."""
    monkeypatch.setattr(classification_module.settings, "classification_max_pages", 15)
    mock = _mock_complete(
        monkeypatch,
        text='{"document_type": "closing_disclosure", "confidence": 0.9, "reasoning": "x"}',
    )
    await classify_document(
        _make_pdf(120), "application/pdf"
    )  # a 120-page package (would exceed 100)
    assert _payload_pages(mock) == 15  # only the first 15 pages were sent


async def test_pdf_within_cap_sent_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classification_module.settings, "classification_max_pages", 15)
    mock = _mock_complete(
        monkeypatch, text='{"document_type": "w2", "confidence": 0.9, "reasoning": "x"}'
    )
    original = _make_pdf(3)
    await classify_document(original, "application/pdf")
    import base64 as _b64

    sent = _b64.b64decode(mock.await_args.kwargs["messages"][0]["content"][0]["source"]["data"])
    assert sent == original  # byte-identical — no re-encode for an under-cap document


async def test_image_is_not_page_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap is PDF-only; an image (single page) is sent unchanged (first_n_pages returns None)."""
    mock = _mock_complete(
        monkeypatch,
        text='{"document_type": "drivers_license", "confidence": 0.9, "reasoning": "x"}',
    )
    await classify_document(PNG_BYTES, "image/png")
    import base64 as _b64

    sent = _b64.b64decode(mock.await_args.kwargs["messages"][0]["content"][0]["source"]["data"])
    assert sent == PNG_BYTES


# --------------------------------------------------------------------------- #
# LP-463 — document_name (named first) + type_matches_document (the guard)
# --------------------------------------------------------------------------- #


async def test_document_name_and_self_check_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(
        monkeypatch,
        text=(
            '{"document_name": "wiring instructions from a law firm", "document_type": "unknown", '
            '"type_matches_document": true, "confidence": 0.9, "reasoning": "law-firm wire"}'
        ),
    )
    r = await classify_document(PDF_BYTES, "application/pdf")
    assert r.document_name == "wiring instructions from a law firm"
    assert r.type_matches_document is True
    assert r.document_type == "unknown"


async def test_type_mismatch_false_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 158/T4 shape: the model picks a type but flags it as NOT matching the document it named."""
    _mock_complete(
        monkeypatch,
        text=(
            '{"document_name": "a Canadian T4 slip", "document_type": "w2", '
            '"type_matches_document": false, "confidence": 0.85, "reasoning": "T4, closest is w2"}'
        ),
    )
    r = await classify_document(PDF_BYTES, "application/pdf")
    assert r.type_matches_document is False  # flagged; the pipeline will not apply the w2 label
    assert r.document_name == "a Canadian T4 slip"


async def test_self_check_defaults_true_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """A response without the field (older/degraded) must NOT spuriously flag — default True (fail safe)."""
    _mock_complete(
        monkeypatch, text='{"document_type": "pay_stub", "confidence": 0.9, "reasoning": "x"}'
    )
    r = await classify_document(PDF_BYTES, "application/pdf")
    assert r.type_matches_document is True and r.document_name is None


async def test_self_check_log_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(
        monkeypatch,
        text=(
            '{"document_name": "wire instructions", "document_type": "general_correspondence", '
            '"type_matches_document": false, "confidence": 0.85, "reasoning": "x"}'
        ),
    )
    with structlog.testing.capture_logs() as logs:
        await classify_document(PDF_BYTES, "application/pdf")
    ok = [e for e in logs if e["event"] == "classification_succeeded"]
    assert len(ok) == 1 and ok[0]["type_matches_document"] is False
    # ⚠️ the free-text document_name (PII-adjacent) is NEVER logged
    assert "wire instructions" not in " ".join(repr(e) for e in logs)


async def test_empty_document_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text="{}")
    result = await classify_document(b"", "application/pdf")
    assert result.document_type == "unknown"
    assert mock.call_count == 0  # never called the API


@pytest.mark.parametrize("media_type", ["text/plain", "application/zip", "image/gif", ""])
async def test_unsupported_media_type_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text="{}")
    result = await classify_document(PDF_BYTES, media_type)
    assert result.document_type == "unknown"
    assert mock.call_count == 0  # unsupported type → no API call


async def test_confidence_clamped_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(
        monkeypatch,
        text='{"document_type": "pay_stub", "confidence": 1.5, "reasoning": "over"}',
    )
    result = await classify_document(PDF_BYTES, "application/pdf")
    assert result.confidence == 1.0


# --------------------------------------------------------------------------- #
# PRIVACY: never log document bytes/base64 or raw response content
# --------------------------------------------------------------------------- #


async def test_does_not_log_bytes_base64_or_response_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pii_bytes = b"%PDF John Q Borrower SSN 123-45-6789 gross 5000 account 111-222-333"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    response_reasoning = "borrower address 42 Private Lane revealed here"
    _mock_complete(
        monkeypatch,
        text=f'{{"document_type": "pay_stub", "confidence": 0.9, "reasoning": "{response_reasoning}"}}',
    )
    with structlog.testing.capture_logs() as logs:
        await classify_document(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert "123-45-6789" not in blob  # raw document bytes content
    assert pii_b64 not in blob  # base64 payload never logged
    assert response_reasoning not in blob  # raw response content not logged
    # But a metadata success log IS emitted (type + confidence only).
    success = [e for e in logs if e["event"] == "classification_succeeded"]
    assert len(success) == 1
    assert success[0]["document_type"] == "pay_stub"
    assert success[0]["confidence"] == 0.9


def test_unknown_factory() -> None:
    result = ClassificationResult.unknown("because reasons")
    assert result.document_type == "unknown"
    assert result.confidence == 0.0
    assert result.reasoning == "because reasons"
