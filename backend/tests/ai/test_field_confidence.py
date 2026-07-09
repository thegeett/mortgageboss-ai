"""Per-field extraction confidence (LP-201) — honesty + backward-compat tests.

The rules being guarded:
* a field the model rated → its number stored on the field; the provenance tag
  (``model_self_reported``) is *derived* at read time, never stored beside it;
* a field the model did NOT rate → ``confidence=None`` → derives ``not_provided`` —
  never a fabricated ``0.0``/``0.9``/``1.0``;
* a legacy payload with no ``field_confidence`` map still parses, values unchanged;
* ``coerce_optional_confidence`` never invents a number — garbage, non-finite, and
  out-of-range values are ``None`` (unassessable), NOT clamped to a fake ``1.0``.
"""

import math

from app.ai.extraction.parsing import parse_typed_core
from app.ai.parsing import coerce_confidence, coerce_optional_confidence
from app.models.extraction import ConfidenceSource

# A tiny typed-core spec: (field_name, value-coercer). Identity coercers keep the
# test focused on the confidence plumbing, not on value coercion.
_SPEC = (
    ("gross_pay", lambda v: v),
    ("employer_name", lambda v: v),
    ("rate", lambda v: v),
)


def _source(confidence: float | None) -> ConfidenceSource:
    """The read-time derivation a downstream consumer would apply."""
    return ConfidenceSource.for_confidence(confidence)


def test_rated_field_carries_confidence_and_derives_model_self_reported() -> None:
    payload = {
        "typed_core": {
            "gross_pay": {"value": "8076.93", "page": 1, "snippet": "Gross 8,076.93"},
            "employer_name": {"value": "ACME", "page": 1, "snippet": "ACME"},
        },
        "field_confidence": {"gross_pay": 0.95, "employer_name": 0.4},
    }
    core, _non_null, _lost = parse_typed_core(payload, _SPEC)

    # The tag is not stored — only the number is (so the two can never disagree).
    assert "confidence_source" not in core["gross_pay"]
    assert core["gross_pay"]["confidence"] == 0.95
    assert _source(core["gross_pay"]["confidence"]) == ConfidenceSource.MODEL_SELF_REPORTED
    assert core["employer_name"]["confidence"] == 0.4
    assert _source(core["employer_name"]["confidence"]) == ConfidenceSource.MODEL_SELF_REPORTED


def test_unrated_field_is_null_not_provided_never_fabricated() -> None:
    """A field the model omitted from field_confidence must be null → not_provided."""
    payload = {
        "typed_core": {
            "gross_pay": {"value": "8076.93", "page": 1, "snippet": "x"},
            "employer_name": {"value": "ACME"},
            "rate": {"value": None, "source": None},
        },
        "field_confidence": {"gross_pay": 0.9},  # employer_name + rate omitted
    }
    core, _non_null, _lost = parse_typed_core(payload, _SPEC)

    for key in ("employer_name", "rate"):
        assert core[key]["confidence"] is None, core[key]
        assert _source(core[key]["confidence"]) == ConfidenceSource.NOT_PROVIDED


def test_genuine_zero_confidence_is_kept_and_distinguishable_from_absence() -> None:
    """A model that explicitly rates a field 0.0 keeps 0.0 (genuine), not None."""
    payload = {
        "typed_core": {"gross_pay": {"value": "1"}, "employer_name": {"value": "A"}},
        "field_confidence": {"gross_pay": 0.0},  # explicit zero; employer_name absent
    }
    core, _non_null, _lost = parse_typed_core(payload, _SPEC)

    assert core["gross_pay"]["confidence"] == 0.0
    assert _source(core["gross_pay"]["confidence"]) == ConfidenceSource.MODEL_SELF_REPORTED
    assert core["employer_name"]["confidence"] is None
    assert _source(core["employer_name"]["confidence"]) == ConfidenceSource.NOT_PROVIDED


def test_no_field_confidence_map_all_null_values_unchanged() -> None:
    """A legacy payload (no field_confidence) parses; values unchanged; all null."""
    legacy = {
        "typed_core": {
            "gross_pay": {"value": "8076.93", "page": 1, "snippet": "x"},
            "employer_name": {"value": "ACME"},
            "rate": {"value": None},
        }
    }
    core, _non_null, _lost = parse_typed_core(legacy, _SPEC)

    # Values are exactly what they were before LP-201 (no regression).
    assert core["gross_pay"]["value"] == "8076.93"
    assert core["employer_name"]["value"] == "ACME"
    assert core["rate"]["value"] is None
    # Every field honestly has no confidence → derives not_provided.
    for key in ("gross_pay", "employer_name", "rate"):
        assert core[key]["confidence"] is None
        assert _source(core[key]["confidence"]) == ConfidenceSource.NOT_PROVIDED


def test_no_fabricated_default_appears_anywhere() -> None:
    """Assert no field silently gets a 1.0 / 0.9 / 0.0 default when unrated."""
    payload = {
        "typed_core": {
            "gross_pay": {"value": "1"},
            "employer_name": {"value": "A"},
            "rate": {"value": "2"},
        },
        "field_confidence": {},  # model rated nothing
    }
    core, _non_null, _lost = parse_typed_core(payload, _SPEC)
    assert {core[k]["confidence"] for k in ("gross_pay", "employer_name", "rate")} == {None}


def test_coerce_optional_confidence_never_invents_a_number() -> None:
    assert coerce_optional_confidence(None) is None
    assert coerce_optional_confidence("junk") is None
    assert coerce_optional_confidence(True) is None  # bool rejected, not treated as 1
    assert coerce_optional_confidence(0.87) == 0.87
    assert coerce_optional_confidence("0.72") == 0.72
    assert coerce_optional_confidence(0.0) == 0.0  # a genuine zero is honest, not None
    # Out-of-range / non-finite are unassessable → None, NEVER clamped to a fake 1.0.
    assert coerce_optional_confidence(1.5) is None
    assert coerce_optional_confidence(-3) is None
    assert coerce_optional_confidence("85%") is None  # regex grabs 85 → out of range → None
    assert coerce_optional_confidence(float("nan")) is None
    assert coerce_optional_confidence(float("inf")) is None
    assert coerce_optional_confidence(float("-inf")) is None


def test_document_confidence_coercer_keeps_legacy_clamp_but_rejects_non_finite() -> None:
    """The doc-level gate keeps its legacy clamp; only NaN/Infinity change (→ 0.0)."""
    assert coerce_confidence(None) == 0.0  # unchanged legacy behavior (the review gate)
    assert coerce_confidence(0.83) == 0.83
    assert coerce_confidence(1.5) == 1.0  # out of range → clamped (legacy, unchanged)
    assert coerce_confidence(2.0) == 1.0
    # NaN/Infinity previously clamped to a fake 1.0; now collapse to 0.0, never NaN.
    assert coerce_confidence(float("nan")) == 0.0
    assert coerce_confidence(float("inf")) == 0.0
    assert not any(math.isnan(coerce_confidence(v)) for v in (float("nan"), float("inf"), "junk"))


def test_optional_vs_document_confidence_differ_on_absence() -> None:
    """The doc-level gate defaults missing→0.0; the per-field slot stays honest (None)."""
    assert coerce_confidence(None) == 0.0
    assert coerce_optional_confidence(None) is None
