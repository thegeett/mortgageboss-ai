"""LP-311: the fact-tag machine-source files + their generator (no DB)."""

from __future__ import annotations

import pytest
from app.scripts import generate_fact_tags
from app.verification.rules.projection import (
    ProjectionError,
    check_consistency,
    load_desired_rule_tags,
    load_desired_rules,
    load_desired_tag_dependencies,
    load_desired_tags,
)


def test_generated_csvs_are_committed_and_current() -> None:
    """The committed CSVs must match what the vocabulary xlsx generates.

    If this fails, someone edited the xlsx without re-running the generator (or
    hand-edited a CSV). Re-run ``python -m app.scripts.generate_fact_tags``.
    """
    assert generate_fact_tags.main(["--check"]) == 0


def test_value_type_parsing() -> None:
    assert generate_fact_tags._parse_value_type("enum: in | out | unknown") == (
        "enum",
        ["in", "out", "unknown"],
    )
    assert generate_fact_tags._parse_value_type("number") == ("number", [])
    assert generate_fact_tags._parse_value_type("number | unknown") == ("number", [])
    assert generate_fact_tags._parse_value_type("object: {value, breakdown[]}") == (
        "object",
        [],
    )
    assert generate_fact_tags._parse_value_type("number (from spec)") == ("number", [])


def test_range_pseudo_rules_expand() -> None:
    assert generate_fact_tags._expand_rule_id("CO-1..5") == [
        "CO-1",
        "CO-2",
        "CO-3",
        "CO-4",
        "CO-5",
    ]
    assert generate_fact_tags._expand_rule_id("AS-1") == ["AS-1"]


def test_desired_state_shape() -> None:
    rules = load_desired_rules()
    tags = load_desired_tags()
    rule_tags = load_desired_rule_tags()
    tag_deps = load_desired_tag_dependencies()

    # rule_kinds.csv is 133 rules; the vocabulary is 143 xlsx tags + 1 hand-added overlay tag
    # (id.poa_acceptable LP-329, id.residency_eligible LP-331) = 145.
    assert len(rules) == 133
    assert (
        len(tags) == 160
    )  # +4 assets (LP-323-AS-B) +2 ID-5 (LP-389-A) +2 stmt variance/co-holder (LP-400)
    assert len(rule_tags) == 203
    # No depends_on authored yet (LP-311 Phase 0): the DAG is empty.
    assert tag_deps == set()

    # An enum tag carries allowed_values; a scalar tag does not.
    assert tags["txn.is_money_in"]["allowed_values"] == ["in", "out", "unknown"]
    assert tags["txn.amount"]["allowed_values"] is None
    # tag_role/tag_version are not authored yet.
    assert tags["txn.is_money_in"]["tag_role"] is None
    assert tags["txn.is_money_in"]["tag_version"] == 1


def test_as1_gate_is_files_truth_not_seed() -> None:
    """AS-1 stays priya_validated=False — the files win over LP-118's seed TRUE."""
    rules = load_desired_rules()
    assert rules["AS-1"]["priya_validated"] is False
    assert rules["AS-1"]["threshold_needs_signoff"] is True
    # AS-1 + OC-2 + the ID family + the IN family carry specs; IN-6 (deferred, LP-323-IN-B) does not.
    assert rules["AS-1"]["spec"] is not None
    assert rules["IN-1"]["spec"] is not None  # authored by LP-323-IN-B
    assert rules["IN-6"]["spec"] is None  # deferred (set-coverage shape — see LP-323-IN-B D3)
    assert rules["IN-6"]["priya_validated"] is False


def test_committed_files_are_consistent() -> None:
    """The shipped files must pass the load-time consistency checks."""
    check_consistency(
        rules=load_desired_rules(),
        tags=load_desired_tags(),
        rule_tags=load_desired_rule_tags(),
        tag_dependencies=load_desired_tag_dependencies(),
    )


def test_consistency_rejects_unknown_required_tag() -> None:
    with pytest.raises(ProjectionError, match="not in the fact-tag vocabulary"):
        check_consistency(
            rules={"AS-1": {}},
            tags={},
            rule_tags={("AS-1", "txn.ghost")},
            tag_dependencies=set(),
        )


def test_consistency_rejects_rule_tag_for_unknown_rule() -> None:
    with pytest.raises(ProjectionError, match="unknown rule"):
        check_consistency(
            rules={},
            tags={"txn.amount": {}},
            rule_tags={("ZZ-9", "txn.amount")},
            tag_dependencies=set(),
        )


def test_consistency_rejects_dangling_dependency_edge() -> None:
    with pytest.raises(ProjectionError, match="depends on unknown tag"):
        check_consistency(
            rules={},
            tags={"a": {}},
            rule_tags=set(),
            tag_dependencies={("a", "missing")},
        )


def test_consistency_rejects_dependency_cycle() -> None:
    with pytest.raises(ProjectionError, match="cycle"):
        check_consistency(
            rules={},
            tags={"a": {}, "b": {}, "c": {}},
            rule_tags=set(),
            tag_dependencies={("a", "b"), ("b", "c"), ("c", "a")},
        )


def test_consistency_accepts_valid_dag() -> None:
    # A -> B -> C, A -> C is a valid DAG (no cycle).
    check_consistency(
        rules={},
        tags={"a": {}, "b": {}, "c": {}},
        rule_tags=set(),
        tag_dependencies={("a", "b"), ("b", "c"), ("a", "c")},
    )
