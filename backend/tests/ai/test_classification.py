"""Tests for document classification (LP-38) — the AI wrapper is MOCKED.

No real API calls and no key: ``complete`` is patched to return canned text or
raise. The focus is the module's contract — defensive JSON parsing, graceful
``unknown`` on every failure, the empty-text short-circuit, confidence clamping,
and the privacy rule that the document text / raw response are never logged.
"""

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

# A realistic-length document text (clears the _MIN_TEXT_LEN short-circuit).
SAMPLE_TEXT = "ACME CORP  Pay period 06/01-06/15  Gross 5,000.00  Net 3,812.44  YTD 60,000"


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


# --------------------------------------------------------------------------- #
# classify_document
# --------------------------------------------------------------------------- #


async def test_success_returns_parsed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(
        monkeypatch,
        text='{"document_type": "pay_stub", "confidence": 0.95, "reasoning": "earnings + YTD"}',
    )
    result = await classify_document(SAMPLE_TEXT)
    assert result.document_type == "pay_stub"
    assert result.confidence == 0.95
    assert mock.call_count == 1
    # Uses the classification model + passes the text as the user message.
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == classification_module.settings.anthropic_model_classification
    assert kwargs["messages"][0]["content"] == SAMPLE_TEXT
    assert "system" in kwargs  # the prompt loaded from file


async def test_success_with_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(
        monkeypatch,
        text='```json\n{"document_type": "bank_statement", "confidence": 0.7, "reasoning": "transactions"}\n```',
    )
    result = await classify_document(SAMPLE_TEXT)
    assert result.document_type == "bank_statement"
    assert result.confidence == 0.7


async def test_low_confidence_returned_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """Low confidence is a valid result — the pipeline (not this module) flags review."""
    _mock_complete(
        monkeypatch,
        text='{"document_type": "w2", "confidence": 0.3, "reasoning": "uncertain"}',
    )
    result = await classify_document(SAMPLE_TEXT)
    assert result.document_type == "w2"
    assert result.confidence == 0.3


async def test_malformed_response_returns_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I think this is a pay stub, definitely.")
    result = await classify_document(SAMPLE_TEXT)
    assert result.document_type == "unknown"
    assert result.confidence == 0.0
    assert "parse" in result.reasoning.lower()


async def test_ai_failure_returns_unknown_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await classify_document(SAMPLE_TEXT)
    assert result.document_type == "unknown"
    assert result.confidence == 0.0
    assert "ai call failed" in result.reasoning.lower()


@pytest.mark.parametrize("text", ["", "   ", "\n\t ", "short"])
async def test_empty_or_short_text_skips_api(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    mock = _mock_complete(monkeypatch, text="{}")
    result = await classify_document(text)
    assert result.document_type == "unknown"
    assert mock.call_count == 0  # never called the API


async def test_confidence_clamped_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(
        monkeypatch,
        text='{"document_type": "pay_stub", "confidence": 1.5, "reasoning": "over"}',
    )
    result = await classify_document(SAMPLE_TEXT)
    assert result.confidence == 1.0


# --------------------------------------------------------------------------- #
# PRIVACY: never log document text or raw response content
# --------------------------------------------------------------------------- #


async def test_does_not_log_text_or_response_content(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_text = "John Q Borrower SSN 123-45-6789 gross 5000 account 111-222-333 " * 2
    response_reasoning = "borrower address 42 Private Lane revealed here"
    _mock_complete(
        monkeypatch,
        text=f'{{"document_type": "pay_stub", "confidence": 0.9, "reasoning": "{response_reasoning}"}}',
    )
    with structlog.testing.capture_logs() as logs:
        await classify_document(pii_text)

    blob = " ".join(repr(e) for e in logs)
    assert "123-45-6789" not in blob
    assert pii_text not in blob
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
