"""LP-439 — the final blocking-question answers + the PII-kind remap took validate 70 → 108.

These pin the two guarantees LP-439 delivered on the spec corpus: every spec parses and validates (no blocking
question, no PII kind outside the live ``PiiKind`` enum — the condition-3 guarantee), the four field additions
are present with a reason_class + a why, and 064's Custom key-value list declares the safety-gate ``redact``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.ai.extraction.generator.spec import load_spec
from app.ai.extraction.generator.validator import validate
from app.verification.snapshot.pii import PiiKind

_SPECS = Path(__file__).resolve().parents[3].parent / "docs" / "schema-specs"
_ALL = sorted(_SPECS.glob("[0-9]*.json"))
_VALID_KINDS = {k.name for k in PiiKind}


def test_there_are_108_specs() -> None:
    assert len(_ALL) == 108


@pytest.mark.parametrize("path", _ALL, ids=lambda p: p.stem)
def test_spec_is_valid_json(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))  # raises on malformed JSON


def test_all_108_specs_pass_the_validator() -> None:
    # The measure: 14 (LP-435) → 70 (LP-438) → 108 (LP-439). Every spec is now generatable.
    refusing = {p.stem: [str(r) for r in validate(load_spec(p))] for p in _ALL}
    refusing = {k: v for k, v in refusing.items() if v}
    assert refusing == {}, f"specs still refusing: {refusing}"


def test_no_spec_carries_a_pii_kind_outside_the_enum() -> None:
    # The condition-3 guarantee: every declared pii.kind exists in the live PiiKind enum.
    offenders = []
    for p in _ALL:
        for fld in json.loads(p.read_text(encoding="utf-8")).get("typed_core", []):
            pii = fld.get("pii")
            if isinstance(pii, dict) and pii.get("kind") not in _VALID_KINDS:
                offenders.append((p.stem, fld["name"], pii.get("kind")))
    assert offenders == [], f"invalid pii kinds: {offenders}"


def _field(spec_stem: str, name: str) -> dict[str, object]:
    path = next(p for p in _ALL if p.stem == spec_stem)
    spec = json.loads(path.read_text(encoding="utf-8"))
    return next(f for f in spec["typed_core"] if f["name"] == name)


@pytest.mark.parametrize(
    "spec_stem,name",
    [
        ("079-letter-of-explanation-property", "subject_property_indicator"),
        ("106-verification-of-mortgage", "late_120_plus_count"),
        ("106-verification-of-mortgage", "worst_rating"),
        ("015-written-voe", "employment_status"),
    ],
)
def test_field_addition_has_reason_class_and_why(spec_stem: str, name: str) -> None:
    fld = _field(spec_stem, name)
    assert fld.get("reason_class"), f"{name} missing reason_class"
    assert fld.get("why"), f"{name} missing why"


def test_106_new_late_bucket_and_worst_rating_are_rule_floor() -> None:
    for name in ("late_120_plus_count", "worst_rating"):
        fld = _field("106-verification-of-mortgage", name)
        assert fld["reason_class"] == "rule" and fld["rule_floor"] is True


def test_064_custom_key_value_list_declares_the_redact_safety_gate() -> None:
    spec = json.loads((_SPECS / "064-custom.json").read_text(encoding="utf-8"))
    kv = next(nl for nl in spec["nested_lists"] if nl["name"] == "unmapped_key_value_pairs")
    assert kv.get("redact") == ["value"]  # the explicit safety gate — Custom's values are scrubbed


def test_no_blocking_questions_remain() -> None:
    remaining = [
        (p.stem, q.get("id"))
        for p in _ALL
        for q in json.loads(p.read_text(encoding="utf-8")).get("open_questions", [])
        if q.get("blocks_implementation") is True
    ]
    assert remaining == [], f"still blocking: {remaining}"
