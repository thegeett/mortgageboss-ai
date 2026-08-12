"""Typed operands in the deterministic evaluator (LP-328, GAP-A) + the hand-editable vocabulary
(GAP-E).

The spec DECLARES an operand `type`; a registry resolves it to a coercer, and ONE type-agnostic
comparator (`compare_values`) serves every type. `decimal` is the default (every existing rule
unchanged — equivalence); `date` unblocks ID-5 and every date rule. GAP-E: a NEW tag can be added by
editing a version-controlled YAML overlay (no xlsx round-trip). AS-1/ID-3/ID-6 equivalence is proven
by their own suites passing unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import RuleSpec, load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage


# --------------------------------------------------------------------------- #
# ⚠️ LP-508 review: these are RULE-LOGIC tests, so they run with the distrusted-field guard OFF.
#
# ID-3 and ID-5 gate on tags whose source fields are on the distrust list (a hallucinated driver's-licence
# date on docs 146/294), so with the guard live EVERY case here degrades to needs_review and the date
# comparison this file exists to prove is never reached. Asserting needs_review instead would delete the
# coverage, not move it. The DEGRADATION itself is asserted in test_distrusted_fields_lp508.py; this file
# keeps proving the logic underneath it.
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _without_distrust_guard(monkeypatch):
    monkeypatch.setattr("app.verification.rule_engine.gate.distrusted_tag_ids", dict, raising=True)


def _tag(value: object) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("loan",),
        produced_by=TagProducedBy.PARSED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _loan(tags: dict[str, Tag]) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        tags=TagsSection.present({"loan": tags} if tags else {}),
    )


# LP-389-A — ID-5 is PER BORROWER. The TRUE subjects (not the pre-LP-389-A fiction that placed the tags at
# "loan" where the rule wrongly read them): the borrower's OWN id.borrower_id_expiration under the borrower
# subject, the loan's contract.loan_closing_date under "loan", and a belongs_to document so the per_borrower
# enumerator yields the borrower. The document→borrower promotion itself is proven end-to-end in
# test_id5_per_borrower_lp389a.py; here we exercise the deterministic date operands at those subjects.
_BID = UUID("11111111-1111-4111-8111-111111111111")


def _id5(*, expiration: str | None, closing: str = "2026-05-01") -> list:
    by_subject: dict[str, dict[str, Tag]] = {"loan": {"contract.loan_closing_date": _tag(closing)}}
    if expiration is not None:
        by_subject[str(_BID)] = {"id.borrower_id_expiration": _tag(expiration)}
    doc = DocumentEntry(
        content_id="dl",
        document_type="drivers_license",
        belongs_to=(BorrowerRef(borrower_id=_BID, name="Sam Borrower"),),
        fields={},
    )
    snap = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        tags=TagsSection.present(by_subject),
    )
    return evaluate_deterministic_rule(load_rule_spec("ID-5"), snap)


# --------------------------------------------------------------------------- #
# ID-5 — the `date` typed comparison (id_expiration >= closing_date), PER BORROWER
# --------------------------------------------------------------------------- #
def test_id5_expired_before_closing_fires() -> None:
    (r,) = _id5(expiration="2026-04-30", closing="2026-05-01")
    assert r.verdict is Verdict.FIRED
    assert "2026-04-30" in r.reasoning and "2026-05-01" in r.reasoning  # both dates inline


def test_id5_expiration_equals_closing_is_satisfied_the_ge_default() -> None:
    # PRIYA-PENDING ASSUMPTION: the encoded default is `>=` — an ID valid ON the closing date is valid.
    # If Priya rules `>` (must be valid the day AFTER), this flips to fired; it is a documented default.
    (r,) = _id5(expiration="2026-05-01", closing="2026-05-01")
    assert r.verdict is Verdict.SATISFIED


def test_id5_expiration_after_closing_is_satisfied() -> None:
    (r,) = _id5(expiration="2026-12-31", closing="2026-05-01")
    assert r.verdict is Verdict.SATISFIED


def test_id5_absent_expiration_is_couldnt_check_not_expired() -> None:
    # THE -A DOMAIN EDGE: a non-expiring state ID (no expiration) is NOT expired — couldnt_check,
    # and the reason names the absent tag (never a fabricated fire).
    (r,) = _id5(expiration=None)
    assert r.verdict is Verdict.COULDNT_CHECK
    assert "ID expiration" in r.reasoning  # LP-376-C: the mortgage fact, not the tag id


def test_id5_unparseable_date_is_couldnt_check_never_silently_coerced() -> None:
    # An unparseable / ambiguous date → the operand resolves to None → couldnt_check. NEVER a silent
    # epoch/0 (which would fire or pass wrongly).
    (r,) = _id5(expiration="not-a-date", closing="2026-05-01")
    assert r.verdict is Verdict.COULDNT_CHECK
    assert "could not run" in r.reasoning  # LP-376-C: no "operand" in user text


# --------------------------------------------------------------------------- #
# `decimal` is the DEFAULT — a rule with no declared type runs unchanged; the ONE evaluator serves both
# --------------------------------------------------------------------------- #
def test_decimal_is_the_default_type_no_spec_edit_needed() -> None:
    # AS-1's operands declare no `type` → decimal (equivalence). ID-6 (no operands) also unaffected.
    assert all(
        op.type == "decimal" for op in load_rule_spec("AS-1").deterministic.operands.values()
    )


# A BRAND-NEW date rule expressed as DATA ONLY — proves a typed rule runs from a spec, no evaluator edit.
_SYNTH_DATE_SPEC = {
    "rule_id": "ID-5",  # reuse ID-5's kinds row for the CSV cross-check; a distinct synthetic body
    "name": "synthetic date rule",
    "category": "Identity",
    "kind": "structural",
    "numeric_check": False,
    "criteria": "a must be on or after b",
    "applicability": {"scope": "all loans", "trigger": "once per loan"},
    "required_inputs": [{"name": "a", "snapshot_path": 'tags["loan"]["x.a"]', "description": "a"}],
    "reference_values": {"priya_validated": False, "threshold_needs_signoff": False},
    "subject_enumeration": "loan",
    "subject_key_fields": ["loan"],
    "evidence_required": "the two dates",
    "guideline_reference": "n/a — synthetic",
    "spec_version": 1,
    "deterministic": {
        "load_bearing_tags": ["x.a", "x.b"],
        "gated_tags": ["x.a", "x.b"],
        "operands": {"a": {"tag": "x.a", "type": "date"}, "b": {"tag": "x.b", "type": "date"}},
        "outcomes": [
            {
                "verdict": "fired",
                "when_compare": {"op": "<", "left": "a", "right": "b"},
                "reasoning": "a<b",
            },
            {"verdict": "satisfied", "default": True, "reasoning": "a>=b"},
        ],
    },
}


def test_a_new_date_rule_runs_from_a_spec_only() -> None:
    spec = RuleSpec.model_validate(_SYNTH_DATE_SPEC)
    (fired,) = evaluate_deterministic_rule(
        spec, _loan({"x.a": _tag("2026-01-01"), "x.b": _tag("2026-02-01")})
    )
    assert fired.verdict is Verdict.FIRED
    (ok,) = evaluate_deterministic_rule(
        spec, _loan({"x.a": _tag("2026-03-01"), "x.b": _tag("2026-02-01")})
    )
    assert ok.verdict is Verdict.SATISFIED


def test_mismatched_operand_types_fail_loud_at_load() -> None:
    bad = {**_SYNTH_DATE_SPEC}
    bad["deterministic"] = {
        **_SYNTH_DATE_SPEC["deterministic"],
        "operands": {"a": {"tag": "x.a", "type": "date"}, "b": {"tag": "x.b", "type": "decimal"}},
    }
    with pytest.raises(ValueError, match="different types"):
        RuleSpec.model_validate(bad)


def test_no_operand_type_branch_outside_the_registry() -> None:
    # The wave's success criterion: no `if type == "date"` special-case — coercion is registry-resolved.
    src = (
        Path(__file__).parents[3] / "app" / "verification" / "rule_engine" / "deterministic.py"
    ).read_text()
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        assert 'type == "date"' not in code and "type=='date'" not in code, line
        assert 'type == "decimal"' not in code, line


# --------------------------------------------------------------------------- #
# GAP-E — a NEW tag added by editing the version-controlled overlay ONLY
# --------------------------------------------------------------------------- #
def test_gap_e_new_tag_from_the_overlay_projects(tmp_path, monkeypatch) -> None:
    import app.verification.rules.projection as projection
    import app.verification.tag_materialization.declarations as declarations

    overlay = tmp_path / "vocabulary_extra.yaml"
    overlay.write_text(
        "tags:\n"
        "  id.residency_eligible:\n"
        "    entity: borrower\n"
        "    value_type: enum\n"
        "    allowed_values: ['yes', 'no', 'unknown']\n"
        "    description: A wave-added verdict tag.\n"
        "    produced_by: AI\n"
    )
    # The overlay reader lives in the vocabulary loader (declarations), not projection (LP-328 review).
    monkeypatch.setattr(declarations, "_VOCAB_EXTRA_YAML", overlay)

    tags = projection.load_desired_tags()
    assert "id.residency_eligible" in tags  # projects from the hand-edited file, no xlsx round-trip
    assert tags["id.residency_eligible"]["allowed_values"] == ["yes", "no", "unknown"]
    assert tags["id.residency_eligible"]["entity"] == "borrower"


def test_gap_e_overlay_tag_duplicating_the_vocabulary_fails_loud(tmp_path, monkeypatch) -> None:
    import app.verification.rules.projection as projection
    import app.verification.tag_materialization.declarations as declarations

    overlay = tmp_path / "vocabulary_extra.yaml"
    # id.dob already exists in fact_tags.csv — the overlay must not silently shadow it.
    overlay.write_text("tags:\n  id.dob:\n    entity: borrower\n    value_type: date\n")
    monkeypatch.setattr(declarations, "_VOCAB_EXTRA_YAML", overlay)

    with pytest.raises(projection.ProjectionError, match=r"duplicates a fact_tags\.csv tag"):
        projection.load_desired_tags()


def test_gap_e_overlay_duplicate_also_fails_loud_in_the_declarations_reader(
    tmp_path, monkeypatch
) -> None:
    # The SECOND overlay reader (_allowed_values_by_tag, used at eval time for AI coercion) must guard
    # duplicates the SAME way projection does — the two readers can never disagree (LP-328 review #2).
    import app.verification.tag_materialization.declarations as declarations

    overlay = tmp_path / "vocabulary_extra.yaml"
    overlay.write_text("tags:\n  id.dob:\n    entity: borrower\n    value_type: date\n")
    monkeypatch.setattr(declarations, "_VOCAB_EXTRA_YAML", overlay)
    declarations._allowed_values_by_tag.cache_clear()
    try:
        with pytest.raises(declarations.DeclarationError, match=r"duplicates a fact_tags\.csv tag"):
            declarations._allowed_values_by_tag()
    finally:
        declarations._allowed_values_by_tag.cache_clear()


def test_product_operand_with_a_date_factor_fails_loud_at_load() -> None:
    # A product multiplies numbers; a date factor would raise `Decimal * date` at eval. The Operand
    # validator must reject it at LOAD (LP-328 review #1) — never a runtime crash of an un-backstopped
    # rules step.
    bad = {**_SYNTH_DATE_SPEC}
    bad["deterministic"] = {
        **_SYNTH_DATE_SPEC["deterministic"],
        "operands": {
            "a": {"tag": "x.a", "type": "date"},
            "b": {"product": [{"tag": "x.b", "type": "date"}, {"reference": "k"}]},
        },
    }
    with pytest.raises(ValueError, match="factors must all be `decimal`"):
        RuleSpec.model_validate(bad)
