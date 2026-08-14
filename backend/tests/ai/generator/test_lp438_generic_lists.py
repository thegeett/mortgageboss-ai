"""LP-438 — the generator's generic-list emission (ListSpec + registration + count cross-check) and docs.

Pins: the validator no longer refuses on a nested list; a spec with derived/redact/stable_row_id emits a
correct, executable LP-437 ListSpec; the count cross-check emits where a *_count field sits beside a matching
list; and the format doc + guide §4 are updated (the guide no longer says lists are refused).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.ai.extraction.generator.emitters import (
    emit_count_crosschecks,
    emit_list_specs,
)
from app.ai.extraction.generator.spec import load_spec
from app.ai.extraction.generator.validator import validate
from app.verification.snapshot.documents_section import DerivedSpec, ListSpec

_BACKEND = Path(__file__).resolve().parents[3]
_SPECS = _BACKEND.parent / "docs" / "schema-specs"


def _spec(tmp_path: Path, payload: dict[str, Any]) -> Any:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return load_spec(p)


_LIST_DEMO = {
    "document_type": "demo",
    "existing_extractor": None,
    "typed_core": [{"name": "issuer", "type": "str", "reason_class": "identity"}],
    "nested_lists": [
        {
            "name": "activity",
            "shape": "flat_row",
            "fields": [
                {"name": "date", "type": "date"},
                {"name": "amount", "type": "Decimal"},
                {"name": "description", "type": "str"},
                {"name": "transaction_type", "type": "str"},
            ],
            "derived": [
                {
                    "field": "direction",
                    "from": "transaction_type",
                    "map": {"deposit": "credit", "withdrawal": "debit"},
                }
            ],
            "redact": ["description"],
            "stable_row_id": True,
        }
    ],
    "open_questions": [],
}


def _exec_list_spec(code: str) -> ListSpec:
    """Execute the emitted ListSpec block (dropping the registration snippet) → the single ListSpec."""
    block = code.split("# Register")[0]
    body = "\n".join(line for line in block.splitlines() if not line.startswith("#"))
    ns: dict[str, Any] = {"ListSpec": ListSpec, "DerivedSpec": DerivedSpec}
    exec(compile(body, "<gen>", "exec"), ns)
    specs = [v for v in ns.values() if isinstance(v, ListSpec)]
    assert len(specs) == 1
    return specs[0]


def test_validator_does_not_refuse_on_a_nested_list(tmp_path: Path) -> None:
    assert validate(_spec(tmp_path, _LIST_DEMO)) == []


def test_emits_a_correct_executable_list_spec(tmp_path: Path) -> None:
    ls = _exec_list_spec(emit_list_specs(_spec(tmp_path, _LIST_DEMO)))
    assert isinstance(ls, ListSpec)
    assert ls.name == "activity"
    assert ls.fields == ("date", "amount", "description", "transaction_type")


def test_emits_the_derived_helper_fail_closed_mapping(tmp_path: Path) -> None:
    ls = _exec_list_spec(emit_list_specs(_spec(tmp_path, _LIST_DEMO)))
    assert len(ls.derived) == 1
    d = ls.derived[0]
    assert d.field == "direction" and d.from_field == "transaction_type"
    assert d.mapping == {"deposit": "credit", "withdrawal": "debit"}


def test_derived_map_keys_are_normalized_to_match_the_runtime_lookup(tmp_path: Path) -> None:
    # LP-438 review: _derive_field normalizes its lookup key (str(raw).strip().lower().replace(" ", "_")),
    # so a spec written with natural casing/spaces must NOT emit verbatim keys the lookup can never hit
    # (else the derived field is silently ALWAYS absent). The generator normalizes the keys, and the
    # runtime resolves a natural-cased source value against the emitted mapping.
    import copy

    from app.verification.snapshot.documents_section import _derive_field

    demo = copy.deepcopy(_LIST_DEMO)
    demo["nested_lists"][0]["derived"][0]["map"] = {"Deposit": "credit", "Wire Transfer": "debit"}
    ls = _exec_list_spec(emit_list_specs(_spec(tmp_path, demo)))
    d = ls.derived[0]
    assert d.mapping == {"deposit": "credit", "wire_transfer": "debit"}  # normalized, not verbatim
    # end to end: a natural-cased extracted value resolves through the emitted mapping (not silently absent)
    assert _derive_field({"transaction_type": "Wire Transfer"}, d).value == "debit"
    assert _derive_field({"transaction_type": "Deposit"}, d).value == "credit"
    assert _derive_field({"transaction_type": "unmapped"}, d).absent  # fail-closed still holds


def test_emits_the_redact_helper(tmp_path: Path) -> None:
    ls = _exec_list_spec(emit_list_specs(_spec(tmp_path, _LIST_DEMO)))
    assert ls.redact == frozenset({"description"})


def test_emits_the_stable_row_id_helper(tmp_path: Path) -> None:
    ls = _exec_list_spec(emit_list_specs(_spec(tmp_path, _LIST_DEMO)))
    assert ls.stable_row_id is True


def test_registration_snippet_is_a_snippet_not_a_patch(tmp_path: Path) -> None:
    code = emit_list_specs(_spec(tmp_path, _LIST_DEMO))
    assert '"demo": (_ACTIVITY_LIST,)' in code
    assert "never a patch" in code  # D2 — a snippet, not a shared-file edit


def test_count_crosscheck_emits_for_count_field_beside_matching_list(tmp_path: Path) -> None:
    payload = {
        "document_type": "demo",
        "typed_core": [{"name": "row_count", "type": "int", "reason_class": "rule"}],
        "nested_lists": [{"name": "rows", "fields": [{"name": "a", "type": "str"}]}],
        "open_questions": [],
    }
    cc = emit_count_crosschecks(_spec(tmp_path, payload))
    assert "declared != actual" in cc
    assert "ExtractionStatus.PARTIAL" in cc


def test_count_crosscheck_empty_when_no_count_field(tmp_path: Path) -> None:
    assert emit_count_crosschecks(_spec(tmp_path, _LIST_DEMO)) == ""


def test_bank_statement_002_emits_the_lp437_demo_list_spec() -> None:
    # LP-461 added a second list (additional_accounts) to spec 002 → emit_list_specs now emits two;
    # select the transactions demo among them and assert its LP-437 properties are intact.
    block = emit_list_specs(load_spec(_SPECS / "002-bank-statement.json")).split("# Register")[0]
    body = "\n".join(line for line in block.splitlines() if not line.startswith("#"))
    ns: dict[str, Any] = {"ListSpec": ListSpec, "DerivedSpec": DerivedSpec}
    exec(compile(body, "<gen>", "exec"), ns)
    specs = {v.name: v for v in ns.values() if isinstance(v, ListSpec)}
    ls = specs["transactions"]
    assert ls.stable_row_id and "description" in ls.redact
    assert ls.derived[0].mapping == {"deposit": "credit", "withdrawal": "debit"}
    assert "additional_accounts" in specs  # LP-461 — the combined-statement list emits too


# --------------------------------------------------------------------------- #
# The docs are updated (JOB 1)
# --------------------------------------------------------------------------- #
def test_guide_section_4_no_longer_says_lists_are_refused() -> None:
    guide = (_SPECS / "_GENERATION_GUIDE.md").read_text(encoding="utf-8")
    assert "GENERIC since LP-437" in guide
    assert "no longer refused" in guide.lower()


def test_format_doc_declares_the_three_helpers() -> None:
    fmt = (_SPECS / "_FORMAT.md").read_text(encoding="utf-8")
    for token in ("derived", "redact", "stable_row_id"):
        assert token in fmt
    assert "ABSENT" in fmt  # the derived fail-closed contract is stated


@pytest.mark.parametrize("num", ["005", "006", "010"])
def test_real_count_specs_emit_the_crosscheck(num: str) -> None:
    spec = load_spec(next(_SPECS.glob(f"{num}-*.json")))
    assert "ExtractionStatus.PARTIAL" in emit_count_crosschecks(spec)
