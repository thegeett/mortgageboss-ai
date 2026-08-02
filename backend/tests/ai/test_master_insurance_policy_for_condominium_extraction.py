"""Tests for master insurance policy for condominium extraction (GENERATED, LP-434) — the AI wrapper is MOCKED.

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
from app.ai.extraction.master_insurance_policy_for_condominium import (
    MasterInsurancePolicyForCondominiumExtraction,
    MasterInsurancePolicyForCondominiumExtractionResult,
    _parse_master_insurance_policy_for_condominium_json,
    extract_master_insurance_policy_for_condominium,
)
from app.models.extraction import ExtractionStatus

PDF_BYTES = b"%PDF-1.7 dummy master_insurance_policy_for_condominium"


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "association_or_named_insured": _core("SAMPLE"),
        "condominium_project_name": _core("SAMPLE"),
        "insurance_carrier": _core("SAMPLE"),
        "policy_number": _core("SAMPLE"),
        "policy_form_and_coverage_basis": _core("SAMPLE"),
        "effective_date": _core("2024-01-15"),
        "expiration_date": _core("2024-01-15"),
        "blanket_or_scheduled_coverage": _core("SAMPLE"),
        "replacement_cost_indicator": _core("SAMPLE"),
        "coinsurance_percentage": _core("SAMPLE"),
        "walls_in_bare_walls_or_single_entity_scope": _core("SAMPLE"),
        "water_damage_or_master_policy_exclusions": _core("SAMPLE"),
        "general_liability_each_occurrence_limit": _core("1234.56"),
        "fidelity_crime_coverage_present": _core("SAMPLE"),
        "fidelity_crime_coverage_amount": _core("1234.56"),
        "flood_coverage_present": _core("SAMPLE"),
        "agent_contact_and_certificate_date": _core("SAMPLE"),
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
    d = _parse_master_insurance_policy_for_condominium_json(FULL_JSON).data  # type: ignore[union-attr]
    assert d.association_or_named_insured.value == "SAMPLE"
    assert d.association_or_named_insured.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {"association_or_named_insured": _core(None)}}
    parsed = _parse_master_insurance_policy_for_condominium_json(json.dumps(payload))
    assert parsed is not None
    assert parsed.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{ broken"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_master_insurance_policy_for_condominium_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_master_insurance_policy_for_condominium(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_master_insurance_policy_for_condominium(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = MasterInsurancePolicyForCondominiumExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.data == MasterInsurancePolicyForCondominiumExtraction()
