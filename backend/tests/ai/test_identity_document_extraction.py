"""Tests for the shared identity-document extractor (LP-472) — the AI wrapper is MOCKED.

Two things are proven here:

1. **Shape/mechanism** (guide §10): the typed core is coerced with source, an all-null
   core is FAILED, unparseable JSON returns None, and the ``.failed()`` factory holds.

2. **The consolidation invariant** — the whole point of LP-472. The four government-identity
   types (``passport``, ``permanent_resident_card``, ``work_visa_ead_card``,
   ``government_issued_id``) all route to ONE extractor, and the four schema specs share a
   BYTE-IDENTICAL typed core that matches the module. This is drift-*prevention*, not
   drift-detection: there is a single field set to change. ``drivers_license`` is deliberately
   excluded (its own tuned extractor).
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.ai.client import AIClientError
from app.ai.extraction import EXTRACTORS, model_call
from app.ai.extraction.identity_document import (
    _CORE_SPEC,
    IdentityDocumentExtraction,
    IdentityDocumentExtractionResult,
    _parse_identity_document_json,
    extract_identity_document,
)
from app.models.extraction import ExtractionStatus
from app.schema_specs import SPECS_DIR

PDF_BYTES = b"%PDF-1.7 dummy identity_document"

_IDENTITY_TYPES = (
    "passport",
    "permanent_resident_card",
    "work_visa_ead_card",
    "government_issued_id",
)
_SPEC_FILES = (
    "038-resident-alien-card",  # permanent_resident_card
    "071-government-issued-id",
    "108-work-visa-ead-card",
    "121-passport",
)
_SPECS_DIR = SPECS_DIR


def _core(value: object, page: int | None = 1, snippet: str | None = "snip") -> dict:
    return {"value": value, "page": page, "snippet": snippet}


FULL_PAYLOAD = {
    "typed_core": {
        "document_type_as_printed": _core("PERMANENT RESIDENT"),
        "surname": _core("SABBINENI"),
        "given_names": _core("SIVAJI"),
        "full_name": _core("SIVAJI SABBINENI"),
        "date_of_birth": _core("1983-08-28"),
        "document_number": _core("SAMPLE123"),
        "uscis_or_a_number": _core("208-384-911"),
        "issue_date": _core("2022-08-25"),
        "expiry_date": _core("2032-08-25"),
        "valid_from_date": _core("2023-11-10"),
        "resident_since_date": _core("2022-08-25"),
        "category_code": _core("E26"),
        "employment_terms_or_restriction": _core("None"),
        "issuing_country_or_state": _core("USA"),
        "issuing_authority": _core("USCIS"),
        "place_or_country_of_birth": _core("India"),
        "nationality_or_citizenship": _core("INDIAN"),
        "place_of_issue": _core("COIMBATORE"),
        "government_id_type": _core("State ID"),
        "residential_address": _core("1 Main St"),
    },
    "additional_sections": [
        {"section": "Other", "fields": [{"label": "MRZ", "value": "P<IND..."}]}
    ],
    "confidence": 0.9,
    "reasoning": "identity test fixture.",
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


# --------------------------------------------------------------------------- #
# Shape / mechanism
# --------------------------------------------------------------------------- #
def test_typed_core_coerced_with_source() -> None:
    result = _parse_identity_document_json(FULL_JSON)
    assert result is not None
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.full_name.value == "SIVAJI SABBINENI"
    assert result.data.date_of_birth.value.isoformat() == "1983-08-28"
    assert result.data.category_code.value == "E26"
    # source travels with the value
    assert result.data.full_name.source is not None


def test_all_null_core_is_failed() -> None:
    payload = {"typed_core": {k: _core(None) for k, _ in _CORE_SPEC}, "confidence": 0.1}
    result = _parse_identity_document_json(json.dumps(payload))
    assert result is not None
    assert result.status == ExtractionStatus.FAILED


@pytest.mark.parametrize("raw", ["not json", "", "{unbalanced", "[]"])
def test_parse_unparseable_returns_none(raw: str) -> None:
    assert _parse_identity_document_json(raw) is None


async def test_extract_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, text=FULL_JSON)
    result = await extract_identity_document(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.uscis_or_a_number.value == "208-384-911"


async def test_extract_ai_failure_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_complete(monkeypatch, exc=AIClientError("boom"))
    result = await extract_identity_document(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.FAILED


def test_failed_factory() -> None:
    result = IdentityDocumentExtractionResult.failed("nope")
    assert result.status == ExtractionStatus.FAILED
    assert result.confidence == 0.0
    assert result.data == IdentityDocumentExtraction()


async def test_a_passport_fills_only_its_printed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared schema, filled as a passport would be — category/EAD fields stay null."""
    payload = {
        "typed_core": {k: _core(None) for k, _ in _CORE_SPEC},
        "confidence": 0.95,
    }
    payload["typed_core"].update(
        {
            "document_type_as_printed": _core("PASSPORT"),
            "full_name": _core("THANGAVEL JAGADEESAN"),
            "document_number": _core("Z8043711"),
            "nationality_or_citizenship": _core("INDIAN"),
            "expiry_date": _core("2034-12-16"),
        }
    )
    _mock_complete(monkeypatch, text=json.dumps(payload))
    result = await extract_identity_document(PDF_BYTES, "application/pdf")
    assert result.status == ExtractionStatus.SUCCEEDED
    assert result.data.nationality_or_citizenship.value == "INDIAN"
    assert result.data.category_code.value is None  # not printed on a passport
    assert result.data.resident_since_date.value is None


# --------------------------------------------------------------------------- #
# The consolidation invariant (LP-472) — the reason the ticket exists
# --------------------------------------------------------------------------- #
def test_all_four_types_share_one_extractor() -> None:
    """The four identity types classify distinctly but extract in common: one function."""
    fns = {EXTRACTORS[t] for t in _IDENTITY_TYPES}
    assert fns == {extract_identity_document}
    # drivers_license is NOT in the family.
    assert EXTRACTORS["drivers_license"] is not extract_identity_document


def _spec_core(spec_file: str) -> tuple[str, ...]:
    data = json.loads((_SPECS_DIR / f"{spec_file}.json").read_text(encoding="utf-8"))
    return tuple(f["name"] for f in data["typed_core"])


def test_the_four_specs_share_a_byte_identical_core_matching_the_module() -> None:
    """DRIFT LOCK: all four identity specs carry the IDENTICAL typed core, and it equals the
    module's ``_CORE_SPEC``. Add/rename/reorder a field in one place and this fails — which is the
    guarantee. This replaces four drifting per-type schemas (038/071/108 used different names for
    the same facts) with a single shared field set."""
    module_core = tuple(name for name, _ in _CORE_SPEC)
    cores = {sf: _spec_core(sf) for sf in _SPEC_FILES}
    # every spec identical to the module (and therefore to each other)
    for sf, core in cores.items():
        assert core == module_core, f"{sf} core drifted from the shared identity schema"


def test_each_identity_spec_declares_its_own_document_type() -> None:
    """Tier-1-iff-spec (LP-441) needs each slug to own a spec; the four are distinct types."""
    got = {
        json.loads((_SPECS_DIR / f"{sf}.json").read_text(encoding="utf-8"))["document_type"]
        for sf in _SPEC_FILES
    }
    assert got == set(_IDENTITY_TYPES)
