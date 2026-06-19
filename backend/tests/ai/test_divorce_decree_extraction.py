"""Tests for divorce decree extraction (LP-63) — the AI wrapper is MOCKED.

The decree's support obligations are the Phase-3 undisclosed-obligation feedstock,
so the focus is the **support_obligations list** (type + amount + frequency +
payer, each captured separately, even multiple) and the **property_awards list** —
the structured-rows extension (like bank-statement transactions). Also covers the
typed core, source locations, status (obligations count as content), and graceful
failure. (Formal *findings* are wired in LP-66/67; this ticket captures the data.)

No real decree samples were available — these verify the mechanism/shape, not
accuracy against real decrees (validated as real documents flow through; field set
refined with Priya).
"""

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog
from app.ai.client import AIClientError
from app.ai.extraction import divorce_decree as dd_module
from app.ai.extraction.divorce_decree import (
    DivorceDecreeExtraction,
    DivorceDecreeExtractionResult,
    _parse_divorce_decree_json,
    extract_divorce_decree,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy decree bytes"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "party_1_name": _core("Jane Doe", snippet="Petitioner Jane Doe"),
        "party_2_name": _core("John Doe"),
        "effective_date": _core("2022-06-01", snippet="entered June 1, 2022"),
    },
    "support_obligations": [
        {
            "obligation_type": "child_support",
            "amount": "$1,200.00",
            "frequency": "monthly",
            "payer": "John Doe",
            "page": 3,
            "snippet": "Respondent shall pay $1,200/month child support",
        },
        {
            "obligation_type": "alimony",
            "amount": "800.00",
            "frequency": "monthly",
            "payer": "John Doe",
            "page": 3,
        },
    ],
    "property_awards": [{"description": "marital residence", "awarded_to": "Jane Doe", "page": 4}],
    "additional_sections": [
        {"section": "Case Info", "fields": [{"label": "Case number", "value": "FD-2022-1234"}]}
    ],
    "confidence": 0.88,
    "reasoning": "Dissolution decree.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(text=text, input_tokens=200, output_tokens=120, model="m")
        )
    monkeypatch.setattr(dd_module, "complete", mock)
    return mock


def test_support_obligations_captured_amount_frequency_payer() -> None:
    """Each obligation is captured separately with amount + frequency + payer."""
    result = _parse_divorce_decree_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    obligations = result.data.support_obligations
    assert len(obligations) == 2  # child support AND alimony — not merged
    cs = obligations[0]
    assert cs.obligation_type == "child_support"
    assert cs.amount == Decimal("1200.00")  # "$1,200.00" coerced
    assert cs.frequency == "monthly"
    assert cs.payer == "John Doe"
    assert cs.source is not None and cs.source.page == 3  # source on each row


def test_property_awards_captured() -> None:
    d = _parse_divorce_decree_json(FULL_JSON).data  # type: ignore[union-attr]
    assert len(d.property_awards) == 1
    assert d.property_awards[0].description == "marital residence"
    assert d.property_awards[0].awarded_to == "Jane Doe"


def test_typed_core_and_parties() -> None:
    d = _parse_divorce_decree_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.party_1_name.value == "Jane Doe"
    assert d.effective_date.value == date(2022, 6, 1)


def test_obligations_count_as_content_for_status() -> None:
    """A decree with only obligations (no typed-core scalars) is still SUCCEEDED."""
    payload = {
        "support_obligations": [{"obligation_type": "alimony", "amount": "500", "page": 2}],
        "confidence": 0.7,
    }
    result = _parse_divorce_decree_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    assert len(result.data.support_obligations) == 1


def test_empty_obligation_rows_dropped() -> None:
    payload = {
        "typed_core": {"party_1_name": _core("Jane Doe")},
        "support_obligations": [{"obligation_type": None, "amount": None}, "junk", 5],
        "confidence": 0.6,
    }
    d = _parse_divorce_decree_json(json.dumps(payload)).data  # type: ignore[union-attr]
    assert d.support_obligations == []  # fully-empty / non-dict rows dropped


def test_all_null_is_failed() -> None:
    payload = {"typed_core": {"party_1_name": _core(None)}, "support_obligations": []}
    result = _parse_divorce_decree_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_divorce_decree_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_divorce_decree(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert len(result.data.support_obligations) == 2


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_divorce_decree(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


async def test_does_not_log_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    with structlog.testing.capture_logs() as logs:
        await extract_divorce_decree(PDF_BYTES, "application/pdf")
    blob = " ".join(repr(e) for e in logs)
    assert "Jane Doe" not in blob and "1200" not in blob and "John Doe" not in blob
    done = [e for e in logs if e["event"] == "divorce_decree_extraction_done"]
    assert len(done) == 1
    assert done[0]["support_obligations"] == 2  # only COUNTS are logged
    assert done[0]["property_awards"] == 1


def test_failed_factory() -> None:
    result = DivorceDecreeExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == DivorceDecreeExtraction()
