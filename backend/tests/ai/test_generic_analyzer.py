"""Tests for the Tier 3 generic analyzer (LP-66) — the AI wrapper is MOCKED.

The analyzer is the flexible "understand anything" fallback, so the focus is the
structured-but-flexible parse (generic slots; bad/empty entries dropped; amounts
coerced; honest nulls), the Sonnet model + generous budget, graceful failure
(``None`` on any failure), and that the document bytes / full text / values are
never logged.

No real Tier 3 sample documents were available — these verify the mechanism/shape,
not accuracy against real varied documents (validated as real documents flow
through; moderate-stakes / human-in-the-loop).
"""

import base64
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai import generic_analyzer as analyzer_module
from app.ai.client import AIClientError
from app.ai.generic_analyzer import _parse_analysis_json, analyze_document

PDF_BYTES = b"%PDF-1.7 dummy unknown document"

FULL_PAYLOAD = {
    "document_type_guess": "civil court judgment",
    "key_parties": [
        {"name": "Acme Bank", "role": "plaintiff"},
        {"name": None, "role": None},
        "junk",
    ],
    "key_dates": [{"date": "2024-03-10", "description": "judgment entered"}],
    "key_amounts": [{"value": "$8,200.00", "context": "judgment amount"}],
    "key_findings": [
        {
            "finding_type": "obligation",
            "description": "Outstanding civil judgment",
            "amount": "8200.00",
            "frequency": None,
            "details": {"creditor": "Acme Bank"},
        },
        {"finding_type": None, "description": None},  # empty → dropped
    ],
    "summary": "A civil judgment against the borrower for $8,200.",
    "full_text": "IN THE CIRCUIT COURT ... judgment is entered ...",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=400, output_tokens=300, model="m")
        )
    monkeypatch.setattr(analyzer_module, "complete", mock)
    return mock


def test_parse_structured_but_flexible_output() -> None:
    a = _parse_analysis_json(FULL_JSON)
    assert a is not None
    assert a.document_type_guess == "civil court judgment"
    # Bad / empty entries dropped; the real ones kept.
    assert [(p.name, p.role) for p in a.key_parties] == [("Acme Bank", "plaintiff")]
    assert a.key_amounts[0].value == Decimal("8200.00")  # "$8,200.00" coerced
    assert len(a.key_findings) == 1  # the empty finding was dropped
    assert a.key_findings[0].finding_type == "obligation"
    assert a.key_findings[0].amount == Decimal("8200.00")
    assert a.key_findings[0].details == {"creditor": "Acme Bank"}
    assert a.full_text and "CIRCUIT COURT" in a.full_text


@pytest.mark.parametrize("raw", ["not json", "", "{ broken", "[1,2,3]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_analysis_json(raw) is None


async def test_analyze_success_uses_sonnet_and_generous_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    a = await analyze_document(PDF_BYTES, "application/pdf")
    assert a is not None and a.document_type_guess == "civil court judgment"
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == analyzer_module.settings.anthropic_model_extraction  # Sonnet
    assert kwargs["max_tokens"] >= 8000  # generous (the analysis incl. full text)
    block = kwargs["messages"][0]["content"][0]
    assert block["type"] == "document"  # reads the doc natively


async def test_analyze_ai_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    assert await analyze_document(PDF_BYTES, "application/pdf") is None


async def test_analyze_malformed_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text="I read a court document about a judgment.")
    assert await analyze_document(PDF_BYTES, "application/pdf") is None


@pytest.mark.parametrize("media_type", ["text/plain", ""])
async def test_analyze_unsupported_skips_api(
    monkeypatch: pytest.MonkeyPatch, media_type: str
) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    assert await analyze_document(PDF_BYTES, media_type) is None
    assert mock.call_count == 0


async def test_analyze_empty_skips_api(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = _mock_complete(monkeypatch, text=FULL_JSON)
    assert await analyze_document(b"", "application/pdf") is None
    assert mock.call_count == 0


async def test_never_logs_content_or_values(monkeypatch: pytest.MonkeyPatch) -> None:
    pii_bytes = b"%PDF SECRET judgment Acme Bank 8200"
    pii_b64 = base64.standard_b64encode(pii_bytes).decode("utf-8")
    _mock_complete(monkeypatch, text=FULL_JSON)

    with structlog.testing.capture_logs() as logs:
        await analyze_document(pii_bytes, "application/pdf")

    blob = " ".join(repr(e) for e in logs)
    assert pii_b64 not in blob  # the document bytes
    assert "Acme Bank" not in blob and "8200" not in blob  # extracted values
    assert "CIRCUIT COURT" not in blob  # the full text
    done = [e for e in logs if e["event"] == "generic_analysis_done"]
    assert len(done) == 1 and done[0]["findings"] == 1  # only counts
