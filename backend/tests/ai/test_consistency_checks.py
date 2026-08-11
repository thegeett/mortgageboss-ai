"""Deterministic self-consistency checks (LP-474) — the three ``must-differ`` pairs.

Each proven at ZERO false positives on the stored v2 corpus (088 / 049 / 096). These tests pin the
shape (scalar==scalar, per-row, list-any==scalar), the zero-skip, and that a clean extraction flags
nothing. The layer FLAGS; it never rewrites a value.
"""

from app.ai.extraction.consistency import (
    CHECKS,
    normalize_bench_record,
    run_on_bench_record,
)


def _w2(**typed) -> dict:
    return {"typed_core": typed, "lists": {}}


# --------------------------------------------------------------------------- #
# 088 — state_income_tax == federal_income_tax_withheld
# --------------------------------------------------------------------------- #
def test_088_state_equals_federal_is_flagged() -> None:
    ex = _w2(state_income_tax="35312.86", federal_income_tax_withheld="35312.86", state_code="TX")
    viols = run_on_bench_record("w2", ex)
    assert len(viols) == 1
    assert (
        "state_income_tax" in viols[0].detail and "federal_income_tax_withheld" in viols[0].detail
    )


def test_088_normal_w2_is_clean() -> None:
    ex = _w2(state_income_tax="1499.0", federal_income_tax_withheld="5627.6")
    assert run_on_bench_record("w2", ex) == []


def test_state_tax_absent_does_not_flag() -> None:
    ex = _w2(state_income_tax=None, federal_income_tax_withheld="46360.04")
    assert run_on_bench_record("w2", ex) == []


def test_both_zero_does_not_flag() -> None:
    # A no-tax W-2: state and federal both 0 are trivially equal, not an error.
    ex = _w2(state_income_tax="0", federal_income_tax_withheld="0.00")
    assert run_on_bench_record("w2", ex) == []


# --------------------------------------------------------------------------- #
# 096 — a box_12 amount == medicare_tax_withheld (list-any vs scalar)
# --------------------------------------------------------------------------- #
def test_096_box12_equals_medicare_is_flagged() -> None:
    ex = {
        "typed_core": {"medicare_tax_withheld": "2116.92"},
        "lists": {
            "box_12_items": [
                {"code": "C", "amount": "2116.92"},
                {"code": "D", "amount": "4300.00"},
            ]
        },
    }
    viols = run_on_bench_record("w2", ex)
    assert len(viols) == 1
    assert "box_12_items" in viols[0].detail


def test_096_distinct_box12_is_clean() -> None:
    ex = {
        "typed_core": {"medicare_tax_withheld": "2116.92"},
        "lists": {"box_12_items": [{"code": "C", "amount": "329.52"}]},
    }
    assert run_on_bench_record("w2", ex) == []


# --------------------------------------------------------------------------- #
# 049 — a transaction amount == its own running_balance (per-row)
# --------------------------------------------------------------------------- #
def test_049_amount_equals_running_balance_is_flagged() -> None:
    ex = {
        "typed_core": {},
        "lists": {
            "transactions": [
                {"amount": "278.43", "running_balance": "2435.17"},
                {"amount": "732.27", "running_balance": "732.27"},  # the Zelle bug
                {"amount": "50.00", "running_balance": "682.27"},
            ]
        },
    }
    viols = run_on_bench_record("bank_statement", ex)
    assert len(viols) == 1
    assert "row 1" in viols[0].detail


def test_049_clean_statement_flags_nothing() -> None:
    ex = {
        "typed_core": {},
        "lists": {"transactions": [{"amount": "278.43", "running_balance": "2435.17"}]},
    }
    assert run_on_bench_record("bank_statement", ex) == []


# --------------------------------------------------------------------------- #
# Wiring / scope
# --------------------------------------------------------------------------- #
def test_unknown_type_has_no_checks() -> None:
    assert run_on_bench_record("gift_letter", {"typed_core": {"gift_amount": "224307.94"}}) == []
    assert run_on_bench_record(None, {"typed_core": {}}) == []


def test_only_the_three_declared_types_have_checks() -> None:
    # The scope is deliberately small (LP-474 A6): w2 (two pairs) + bank_statement (one).
    assert set(CHECKS) == {"w2", "bank_statement"}
    assert len(CHECKS["w2"]) == 2 and len(CHECKS["bank_statement"]) == 1


def test_normalize_bench_record_shape() -> None:
    norm = normalize_bench_record({"typed_core": {"a": "1"}, "lists": {"L": [{"x": "2"}]}})
    assert norm == {"typed": {"a": "1"}, "lists": {"L": [{"x": "2"}]}}
