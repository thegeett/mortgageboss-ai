"""Tests for document summarization (LP-65) — the AI wrapper is MOCKED.

The Tier 2 summary is a lightweight, forgiving gist (1-2 sentences), so the focus
is the module's contract: it reads the document natively, returns a trimmed short
string, uses the CHEAP (classification/Haiku) model, never raises (``None`` on any
failure — empty/unsupported document, AI error, empty output), caps a rambling
response, and never logs the document bytes or the summary text (PII).
"""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai import summarization as summarization_module
from app.ai.client import AIClientError
from app.ai.summarization import _MAX_SUMMARY_CHARS, summarize_document

PDF_BYTES = b"%PDF-1.7 dummy document"
PNG_BYTES = b"\x89PNG\r\n\x1a\n dummy image"


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=200, output_tokens=30, model="m")
        )
    monkeypatch.setattr(summarization_module, "complete", mock)
    return mock


async def test_returns_trimmed_gist(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(
        monkeypatch, text="  Flood zone determination for 60 North Street — Zone X.  \n"
    )
    summary = await summarize_document(PDF_BYTES, "application/pdf")
    assert summary == "Flood zone determination for 60 North Street — Zone X."
    # Uses the CHEAP classification (Haiku-class) model — not the extraction model.
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == summarization_module.settings.anthropic_model_classification
    block = kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"  # reads the document natively (no OCR)


async def test_image_input(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text="A short gist.")
    await summarize_document(PNG_BYTES, "image/png")
    block = mock.await_args.kwargs["messages"][0]["content"][0]
    assert block["type"] == "image"


async def test_empty_document_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text="x")
    assert await summarize_document(b"", "application/pdf") is None
    assert mock.call_count == 0


@pytest.mark.parametrize("media_type", ["text/plain", "image/gif", ""])
async def test_unsupported_media_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text="x")
    assert await summarize_document(PDF_BYTES, media_type) is None
    assert mock.call_count == 0


async def test_ai_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    assert await summarize_document(PDF_BYTES, "application/pdf") is None


async def test_empty_response_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="   \n  ")
    assert await summarize_document(PDF_BYTES, "application/pdf") is None


async def test_rambling_response_is_capped_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "word " * 500  # ~2500 chars
    _mock_complete(monkeypatch, text=long_text)
    summary = await summarize_document(PDF_BYTES, "application/pdf")
    assert summary is not None
    assert len(summary) <= _MAX_SUMMARY_CHARS  # capped, but still returned


async def test_never_logs_content_or_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_bytes = b"%PDF SECRET borrower 123-45-6789"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    pii_summary = "Credit report for SECRETBORROWER showing SSN 123-45-6789."
    _mock_complete(monkeypatch, text=pii_summary)

    with structlog.testing.capture_logs() as logs:
        result = await summarize_document(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert pii_b64 not in blob  # the document bytes
    assert "SECRETBORROWER" not in blob and "123-45-6789" not in blob  # the summary text (PII)
    done = [e for e in logs if e["event"] == "summarization_succeeded"]
    assert len(done) == 1 and done[0]["summary_chars"] == len(pii_summary)  # only a length
    assert result == pii_summary  # the gist is still returned to the caller
