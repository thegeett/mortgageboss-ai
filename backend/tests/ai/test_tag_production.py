"""The Stage-A AI boundary (LP-313) — defensive parsing + the wrapped-call honesty.

Keyless: the parser is pure, and the reasoner tests patch ``complete`` so no API key is
needed. Covers array/fenced/wrapped JSON, dropping malformed entries, the truncation flag,
and the added timeout failing closed as an AIClientError.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.ai import tag_production
from app.ai.client import AIClientError, AICompletion
from app.ai.tag_production import _parse_judgments, reason_stage_a_transactions

_ARRAY = """
[
  {"index": 1,
   "is_money_in": {"value": "in", "confidence": 0.9, "reasoning": "payroll deposit"},
   "apparent_category": {"value": "payroll", "confidence": 0.8, "reasoning": "DES:PAYROLL"}},
  {"index": 2,
   "is_money_in": {"value": "out", "confidence": 0.7, "reasoning": "card purchase"},
   "apparent_category": {"value": "vendor", "confidence": 0.6, "reasoning": "merchant"}}
]
"""


def test_parses_a_bare_json_array() -> None:
    judgments = _parse_judgments(_ARRAY)
    assert [j.index for j in judgments] == [1, 2]
    assert judgments[0].is_money_in is not None and judgments[0].is_money_in.value == "in"
    assert judgments[1].apparent_category is not None
    assert judgments[1].apparent_category.value == "vendor"


def test_parses_fenced_and_wrapped_shapes() -> None:
    fenced = f"Here you go:\n```json\n{_ARRAY}\n```\nDone."
    assert len(_parse_judgments(fenced)) == 2
    wrapped = '{"transactions": ' + _ARRAY + "}"
    assert len(_parse_judgments(wrapped)) == 2


def test_drops_malformed_entries_and_missing_index() -> None:
    # The first entry has no "index" → it is dropped; the second is well-formed.
    text = """
    [
      {"is_money_in": {"value": "in"}},
      {"index": 5, "is_money_in": {"value": "in", "confidence": 0.5, "reasoning": "x"},
       "apparent_category": {"value": "gift", "confidence": 0.5, "reasoning": "y"}}
    ]
    """
    judgments = _parse_judgments(text)
    assert [j.index for j in judgments] == [5]


def test_a_tag_missing_a_value_becomes_none() -> None:
    text = (
        '[{"index": 1, "is_money_in": {"confidence": 0.9}, "apparent_category": {"value": "fee"}}]'
    )
    j = _parse_judgments(text)[0]
    assert j.is_money_in is None  # no "value" → unresolved (orchestrator makes it unknown)
    assert j.apparent_category is not None and j.apparent_category.value == "fee"


def test_unparseable_response_yields_no_judgments() -> None:
    assert _parse_judgments("the model apologised and wrote prose") == []


async def _completion(text: str, *, stop_reason: str = "end_turn") -> AICompletion:
    return AICompletion(
        text=text, input_tokens=100, output_tokens=50, model="stub", stop_reason=stop_reason
    )


async def test_reasoner_parses_and_reports_tokens() -> None:
    with patch.object(
        tag_production, "complete", AsyncMock(return_value=await _completion(_ARRAY))
    ):
        result = await reason_stage_a_transactions('{"transactions": []}')
    assert len(result.judgments) == 2
    assert result.input_tokens == 100 and result.output_tokens == 50
    assert result.truncated is False


async def test_reasoner_flags_truncation() -> None:
    with patch.object(
        tag_production,
        "complete",
        AsyncMock(return_value=await _completion(_ARRAY, stop_reason="max_tokens")),
    ):
        result = await reason_stage_a_transactions('{"transactions": []}')
    assert result.truncated is True


async def test_timeout_fails_closed_as_ai_client_error() -> None:
    with (
        patch.object(tag_production, "complete", AsyncMock(side_effect=TimeoutError())),
        pytest.raises(AIClientError, match="timed out"),
    ):
        await reason_stage_a_transactions('{"transactions": []}')


async def test_transport_error_propagates_as_ai_client_error() -> None:
    with (
        patch.object(tag_production, "complete", AsyncMock(side_effect=AIClientError("boom"))),
        pytest.raises(AIClientError),
    ):
        await reason_stage_a_transactions('{"transactions": []}')
