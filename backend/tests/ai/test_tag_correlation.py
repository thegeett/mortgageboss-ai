"""The Stage-B sourcing-judge AI boundary (LP-314) — defensive parsing + wrapped-call honesty.

Keyless: the parser is pure and the reasoner tests patch ``complete``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.ai import tag_correlation
from app.ai.client import AIClientError, AICompletion
from app.ai.tag_correlation import _parse_judgment, reason_stage_b_sourcing

_OBJECT = """
{"value": "yes", "source_index": 2, "confidence": 0.9,
 "reasoning": "transfer from savings of the same amount two days prior"}
"""


def test_parses_a_json_object() -> None:
    j = _parse_judgment(_OBJECT)
    assert j is not None
    assert j.value == "yes" and j.source_index == 2 and j.confidence == 0.9
    assert j.reasoning is not None


def test_parses_fenced_and_ignores_prose() -> None:
    j = _parse_judgment(f"Sure:\n```json\n{_OBJECT}\n```\nthanks")
    assert j is not None and j.value == "yes"


def test_null_source_index_is_none() -> None:
    j = _parse_judgment(
        '{"value": "yes", "source_index": null, "confidence": 0.7, "reasoning": "payroll"}'
    )
    assert j is not None and j.source_index is None


def test_missing_value_yields_none() -> None:
    assert _parse_judgment('{"source_index": 1, "confidence": 0.5}') is None


def test_unparseable_yields_none() -> None:
    assert _parse_judgment("the model wrote prose and no JSON") is None


async def _completion(text: str, *, stop_reason: str = "end_turn") -> AICompletion:
    return AICompletion(
        text=text, input_tokens=40, output_tokens=20, model="stub", stop_reason=stop_reason
    )


async def test_reasoner_parses_and_reports_tokens() -> None:
    with patch.object(
        tag_correlation, "complete", AsyncMock(return_value=await _completion(_OBJECT))
    ):
        result = await reason_stage_b_sourcing('{"deposit": {}, "candidates": []}')
    assert result.judgment is not None and result.judgment.value == "yes"
    assert result.input_tokens == 40 and result.truncated is False


async def test_reasoner_flags_truncation() -> None:
    with patch.object(
        tag_correlation,
        "complete",
        AsyncMock(return_value=await _completion(_OBJECT, stop_reason="max_tokens")),
    ):
        result = await reason_stage_b_sourcing('{"deposit": {}, "candidates": []}')
    assert result.truncated is True


async def test_timeout_fails_closed_as_ai_client_error() -> None:
    with (
        patch.object(tag_correlation, "complete", AsyncMock(side_effect=TimeoutError())),
        pytest.raises(AIClientError, match="timed out"),
    ):
        await reason_stage_b_sourcing('{"deposit": {}, "candidates": []}')


async def test_transport_error_propagates() -> None:
    with (
        patch.object(tag_correlation, "complete", AsyncMock(side_effect=AIClientError("boom"))),
        pytest.raises(AIClientError),
    ):
        await reason_stage_b_sourcing('{"deposit": {}, "candidates": []}')
