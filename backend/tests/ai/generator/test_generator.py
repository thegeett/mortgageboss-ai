"""LP-434 — the extractor generator: validator, emitters, and the round-trip proof.

The load-bearing assertions:

* the validator catches EACH of the guide's five §0 stop conditions;
* a valid spec generates a module that executes (imports), passes ruff and mypy, and
  whose ``_CORE_SPEC`` matches the spec's fields and coercers;
* **the round-trip** — a spec describing ``property_tax_bill`` as it ships today
  generates a module behaviourally identical to the shipping one (same ``_CORE_SPEC``
  pairs, same model field names/types); the only differences are docstrings/comments;
* the count cross-check emits when a ``*_count`` field + a matching list are present;
* NO review metadata (``why`` / ``reason_class`` / ``rejected`` …) reaches the output.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from app.ai.extraction import property_tax_bill as shipping
from app.ai.extraction.generator.emitters import (
    class_prefix,
    count_crosscheck_pairs,
    emit_count_crosscheck,
    emit_diff_report,
    emit_module,
    emit_prompt,
    emit_test,
)
from app.ai.extraction.generator.spec import TYPE_TO_COERCER, load_spec
from app.ai.extraction.generator.validator import validate

_BACKEND = Path(__file__).resolve().parents[3]
_FIXTURES = Path(__file__).parent / "fixtures"
_ROUNDTRIP = _FIXTURES / "roundtrip_property_tax_bill.json"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _field(name: str, ftype: str | None, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "type": ftype,
        "reason_class": "rule",
        "pii": None,
        "exists_today": False,
        "prompt_hint": None,
        "degraded_from": None,
    }
    base.update(over)
    return base


def _spec_dict(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "document_type": "probe_doc",
        "existing_extractor": None,
        "typed_core": [_field("issuer", "str"), _field("amount", "Decimal")],
        "nested_lists": [],
        "open_questions": [],
    }
    base.update(over)
    return base


def _load(tmp_path: Path, payload: dict[str, Any]) -> Any:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return load_spec(p)


def _conditions(refusals: list[Any]) -> set[int]:
    return {r.condition for r in refusals}


# --------------------------------------------------------------------------- #
# The five stop conditions — one case each (the load-bearing behaviour)
# --------------------------------------------------------------------------- #


def test_clean_spec_passes(tmp_path: Path) -> None:
    assert validate(_load(tmp_path, _spec_dict())) == []


def test_condition_1_blocking_open_question(tmp_path: Path) -> None:
    spec = _load(
        tmp_path,
        _spec_dict(open_questions=[{"id": 1, "q": "shape?", "blocks_implementation": True}]),
    )
    assert 1 in _conditions(validate(spec))


def test_condition_1_answered_question_does_not_block(tmp_path: Path) -> None:
    # blocks_implementation: false is NOT a stop condition.
    spec = _load(
        tmp_path,
        _spec_dict(open_questions=[{"id": 1, "q": "cosmetic?", "blocks_implementation": False}]),
    )
    assert validate(spec) == []


def test_condition_2_type_without_coercer(tmp_path: Path) -> None:
    spec = _load(tmp_path, _spec_dict(typed_core=[_field("flag", "bool")]))
    assert 2 in _conditions(validate(spec))


def test_condition_3_unknown_pii_kind(tmp_path: Path) -> None:
    spec = _load(
        tmp_path,
        _spec_dict(
            typed_core=[_field("addr", "str", pii={"kind": "ADDRESS", "pre_masked": False})]
        ),
    )
    assert 3 in _conditions(validate(spec))


def test_condition_3_known_pii_kind_passes(tmp_path: Path) -> None:
    # SSN / ACCOUNT exist in PiiKind — not a stop condition.
    spec = _load(
        tmp_path,
        _spec_dict(typed_core=[_field("ssn", "str", pii={"kind": "SSN", "pre_masked": False})]),
    )
    assert validate(spec) == []


def test_condition_4_nested_list(tmp_path: Path) -> None:
    spec = _load(tmp_path, _spec_dict(nested_lists=[{"name": "rows", "fields": []}]))
    assert 4 in _conditions(validate(spec))


def test_condition_5_missing_reason_class(tmp_path: Path) -> None:
    spec = _load(tmp_path, _spec_dict(typed_core=[_field("x", "str", reason_class=None)]))
    assert 5 in _conditions(validate(spec))


def test_top_ten_refuse_except_the_two_geet_unblocked() -> None:
    # A high refusal rate on the nested-heavy top ten is the CORRECT outcome (guide §12). After LP-435
    # applied Geet's four decisions, TWO of the top ten now pass: 008-w2 (its ADDRESS pii was unmasked →
    # pii null) and 009-condo (its blocking master-policy question was answered). The other eight still
    # refuse (nested lists, DOB, other blocking questions). This pins that post-decision reality.
    specs_dir = _BACKEND.parent / "docs" / "schema-specs"
    now_passing = {"w2", "condo_questionnaire"}
    for n in range(1, 11):
        matches = list(specs_dir.glob(f"{n:03d}-*.json"))
        assert matches, f"missing spec {n:03d}"
        spec = load_spec(matches[0])
        refuses = bool(validate(spec))
        if spec.document_type in now_passing:
            assert not refuses, f"{spec.document_type} should pass after Geet's LP-435 decisions"
        else:
            assert refuses, f"{spec.document_type} unexpectedly passed"


# --------------------------------------------------------------------------- #
# A valid spec → an importable, ruff- and mypy-clean module with the right _CORE_SPEC
# --------------------------------------------------------------------------- #


def _exec_module(source: str) -> dict[str, Any]:
    ns: dict[str, Any] = {}
    exec(compile(source, "<generated>", "exec"), ns)
    return ns


def test_generated_module_executes_and_core_spec_matches_spec() -> None:
    spec = load_spec(_ROUNDTRIP)
    ns = _exec_module(emit_module(spec))
    got = [(name, coercer.__name__) for name, coercer in ns["_CORE_SPEC"]]
    expected = [(f.name, TYPE_TO_COERCER[f.type]) for f in spec.typed_core if f.type is not None]
    assert got == expected
    model = ns[f"{class_prefix(spec.document_type)}Extraction"]
    field_names = [n for n in model.model_fields if n != "additional_sections"]
    assert field_names == [f.name for f in spec.typed_core]


@pytest.mark.parametrize("target", ["module", "test"])
def test_generated_passes_ruff(target: str) -> None:
    ruff = shutil.which("ruff")
    assert ruff is not None
    spec = load_spec(_ROUNDTRIP)
    dt = spec.document_type
    if target == "module":
        source, name = emit_module(spec), f"app/ai/extraction/{dt}.py"
    else:
        source, name = emit_test(spec), f"tests/ai/test_{dt}_extraction.py"
    for extra in (["check"], ["format", "--check"]):
        proc = subprocess.run(
            [ruff, *extra, "--stdin-filename", name, "-"],
            input=source,
            capture_output=True,
            text=True,
            cwd=_BACKEND,
            check=False,
        )
        assert proc.returncode == 0, f"ruff {extra} failed:\n{proc.stdout}\n{proc.stderr}"


def test_generated_module_passes_mypy(tmp_path: Path) -> None:
    mypy = shutil.which("mypy")
    assert mypy is not None
    # A fresh, non-colliding type name so no existing module is touched.
    payload = _spec_dict(
        document_type="generated_sample_doc",
        typed_core=[
            _field("issuer", "str"),
            _field("amount", "Decimal"),
            _field("issued_on", "date"),
            _field("count_of_pages", "int"),
        ],
    )
    spec = _load(tmp_path, payload)
    probe = _BACKEND / "app" / "ai" / "extraction" / "generated_sample_doc.py"
    probe.write_text(emit_module(spec), encoding="utf-8")
    try:
        proc = subprocess.run(
            [mypy, "--follow-imports=silent", str(probe.relative_to(_BACKEND))],
            capture_output=True,
            text=True,
            cwd=_BACKEND,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout
    finally:
        probe.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# The round-trip — generated property_tax_bill ≡ the shipping one (behaviour)
# --------------------------------------------------------------------------- #


def test_roundtrip_core_spec_identical_to_shipping() -> None:
    spec = load_spec(_ROUNDTRIP)
    ns = _exec_module(emit_module(spec))
    generated = [(name, coercer.__name__) for name, coercer in ns["_CORE_SPEC"]]
    real = [(name, coercer.__name__) for name, coercer in shipping._CORE_SPEC]
    assert generated == real  # same fields, same coercers — behaviourally identical


def test_roundtrip_model_fields_identical_to_shipping() -> None:
    spec = load_spec(_ROUNDTRIP)
    ns = _exec_module(emit_module(spec))
    gen_model = ns["PropertyTaxBillExtraction"]
    real_model = shipping.PropertyTaxBillExtraction
    assert list(gen_model.model_fields) == list(real_model.model_fields)

    def _inner(ann: Any) -> str:
        # Both render as ``TypedField[<T>]`` — as a resolved class in the real module and a
        # ForwardRef when exec'd in a bare namespace; compare the inner type parameter.
        match = re.search(r"TypedField\[(\w+)\]", str(ann))
        return match.group(1) if match else str(ann)

    for name, info in real_model.model_fields.items():
        if name == "additional_sections":
            continue  # the catch-all is identical boilerplate, not a typed-core field
        assert _inner(gen_model.model_fields[name].annotation) == _inner(info.annotation)


# --------------------------------------------------------------------------- #
# The count cross-check (guide §8) — built ready even though nested specs refuse
# --------------------------------------------------------------------------- #


def test_count_crosscheck_pairs_and_emit(tmp_path: Path) -> None:
    spec = _load(
        tmp_path,
        _spec_dict(
            typed_core=[_field("tradeline_count", "int", reason_class="processor")],
            nested_lists=[{"name": "tradelines", "fields": []}],
        ),
    )
    pairs = count_crosscheck_pairs(spec)
    assert pairs == [("tradeline_count", "tradelines")]
    snippet = emit_count_crosscheck(*pairs[0])
    assert "declared != actual" in snippet
    assert "ExtractionStatus.PARTIAL" in snippet


def test_count_crosscheck_absent_when_no_matching_list(tmp_path: Path) -> None:
    spec = _load(
        tmp_path,
        _spec_dict(
            typed_core=[_field("tradeline_count", "int", reason_class="processor")],
            nested_lists=[{"name": "inquiries", "fields": []}],
        ),
    )
    assert count_crosscheck_pairs(spec) == []


# --------------------------------------------------------------------------- #
# No review metadata reaches the output (guide §1)
# --------------------------------------------------------------------------- #


def test_no_review_metadata_in_generated_code() -> None:
    spec = load_spec(_ROUNDTRIP)
    blob = "\n".join((emit_module(spec), emit_prompt(spec), emit_test(spec)))
    for token in (
        "reason_class",
        "rejected",
        "open_questions",
        "encoding_variations",
        "rule_floor",
        "plumbing_sites",
        "blocks_implementation",
        "exists_today",
        "degraded_from",
        '"why"',
    ):
        assert token not in blob, f"leaked review metadata: {token}"


# --------------------------------------------------------------------------- #
# Diff mode (guide §6 / D6) — a report, never a module; blockers flagged
# --------------------------------------------------------------------------- #


def test_diff_mode_reports_additions_and_flags_blocked_pii() -> None:
    spec = load_spec(_BACKEND.parent / "docs" / "schema-specs" / "008-w2.json")
    assert spec.is_diff_mode
    report = emit_diff_report(spec)
    assert "employer_address" in report and "ADD" in report
    # the ADDRESS-pii field is flagged BLOCKED, never silently emitted.
    assert "employee_address" in report
    assert "BLOCKED" in report
