"""Tests for condo questionnaire extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

Shape/mechanism, not accuracy (guide §10): the typed core is coerced with source, an
all-null core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory
holds. No real samples exist — accuracy is validated as real documents flow through.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import model_call
from app.ai.extraction.condo_questionnaire import (
    CondoQuestionnaireExtraction,
    CondoQuestionnaireExtractionResult,
    _parse_condo_questionnaire_json,
    extract_condo_questionnaire,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy condo_questionnaire"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "project_name": _core("SAMPLE"),
        "project_address": _core("SAMPLE"),
        "hoa_name": _core("SAMPLE"),
        "management_company": _core("SAMPLE"),
        "questionnaire_form_type": _core("SAMPLE"),
        "completed_by_name": _core("SAMPLE"),
        "completed_date": _core("2024-01-15"),
        "is_signed": _core("SAMPLE"),
        "total_units": _core(2024),
        "units_sold_and_closed": _core(2024),
        "owner_occupied_units": _core(2024),
        "owner_occupancy_percentage": _core("1234.56"),
        "investor_owned_units": _core(2024),
        "single_entity_owned_units": _core(2024),
        "single_entity_max_percentage": _core("1234.56"),
        "commercial_space_percentage": _core("1234.56"),
        "project_type": _core("SAMPLE"),
        "is_project_complete": _core("SAMPLE"),
        "hoa_dues_amount": _core("1234.56"),
        "hoa_dues_frequency": _core("SAMPLE"),
        "units_delinquent_over_60_days": _core(2024),
        "delinquency_percentage": _core("1234.56"),
        "annual_budget_amount": _core("1234.56"),
        "reserve_fund_balance": _core("1234.56"),
        "reserve_contribution_percentage": _core("1234.56"),
        "special_assessment_indicator": _core("SAMPLE"),
        "special_assessment_amount": _core("1234.56"),
        "master_policy_carrier": _core("SAMPLE"),
        "master_policy_number": _core("SAMPLE"),
        "master_policy_coverage_amount": _core("1234.56"),
        "master_policy_replacement_cost_basis": _core("SAMPLE"),
        "fidelity_bond_indicator": _core("SAMPLE"),
        "fidelity_bond_amount": _core("1234.56"),
        "litigation_indicator": _core("SAMPLE"),
        "litigation_description": _core("SAMPLE"),
    },
    "additional_sections": [{"section": "Other", "fields": [{"label": "Note", "value": "x"}]}],
    "confidence": 0.9,
    "reasoning": "generated test fixture.",
}
FULL_JSON = json.dumps(FULL_PAYLOAD)


def _mock_complete(
    monkeypatch: pytest.MonkeyPatch, *, text: str | None = None, exc: Exception | None = None
) -> AsyncMock:
    if exc is not None:
        mock = AsyncMock(side_effect=exc)
    else:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                text=text, input_tokens=150, output_tokens=60, model="m", stop_reason="end_turn"
            )
        )
    monkeypatch.setattr(model_call, "complete", mock)
    return mock


def test_typed_core_coerced_with_source() -> None:
    d = _parse_condo_questionnaire_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.project_name.value == "SAMPLE"
    assert d.project_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"project_name": _core(None)}}
    parsed = _parse_condo_questionnaire_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_condo_questionnaire_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_condo_questionnaire(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_condo_questionnaire(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = CondoQuestionnaireExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == CondoQuestionnaireExtraction()
