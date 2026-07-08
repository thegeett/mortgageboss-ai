"""Round-3 fixes for the rule seed generator (FIX 2 / 3 / 4 / 6A / 6B).

The seed is the fresh-DB source of truth; these tests guard the invariants it must satisfy so drift
can't be re-introduced at the source (existing DBs are aligned by the round-3 data migration
``c9a3e7f1b5d8``, verified against the live dev DB). The meta-lesson: fail LOUD on bad authoring, and
never emit a shape/value that silently degrades when the engine is wired.
"""

import json
from types import SimpleNamespace

import pytest
from app.scripts.generate_rule_seed import (
    _default_applicability,
    build_seed,
)
from app.services.rule_registry import DEFAULT_SEED_PATH
from app.verification.applicability.authoring import enforce_refi_scope_invariant

_WIRE_KEYS = {"scope", "triggers", "required_inputs"}


def _seed_rows() -> list[dict]:
    return json.loads(DEFAULT_SEED_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# FIX 2 — exhaustive purpose mapping (fail loud on an unhandled scope member)
# --------------------------------------------------------------------------- #


def test_r3fix2_unhandled_purpose_raises() -> None:
    # A new PurposeScope member (not one of the four handled) must break seeding LOUD, never degrade to
    # a purpose-less scope (which the engine reads as "no constraint → applies nationwide" — false green).
    bad_rule = SimpleNamespace(program=None, purpose="some_new_purpose_member")
    with pytest.raises(ValueError, match="unhandled PurposeScope"):
        _default_applicability(bad_rule)


# --------------------------------------------------------------------------- #
# FIX 6A — refi loan_purpose co-emission enforced structurally at construction
# --------------------------------------------------------------------------- #


def test_r3fix6a_refi_type_scope_coemits_loan_purpose() -> None:
    # A refinance_type scope can NEVER exist without loan_purpose:[refinance] — enforced at construction,
    # so a purchase file resolves DOESN'T-APPLY (loan_purpose mismatch), never a false couldn't-check.
    out = enforce_refi_scope_invariant({"refinance_type": ["cash_out"]})
    assert out == {"loan_purpose": ["refinance"], "refinance_type": ["cash_out"]}
    # Idempotent when loan_purpose is already correct.
    already = {"loan_purpose": ["refinance"], "refinance_type": ["rate_term"]}
    assert enforce_refi_scope_invariant(already) == already


def test_r3fix6a_contradictory_loan_purpose_raises() -> None:
    with pytest.raises(ValueError, match="requires loan_purpose"):
        enforce_refi_scope_invariant({"refinance_type": ["cash_out"], "loan_purpose": ["purchase"]})


# --------------------------------------------------------------------------- #
# FIX 6B — validated-no-threshold criterion enforced in code
# --------------------------------------------------------------------------- #


def test_r3fix6b_validated_no_threshold_rejects_a_threshold_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Marking a THRESHOLD-bearing rule validated-no-threshold (→ non-empty params) violates the LP-122R
    # criterion and must break seeding LOUD, never seed validated=true beside an unconfirmed threshold.
    import app.scripts.generate_rule_seed as gen

    monkeypatch.setattr(gen, "_VALIDATED_NO_THRESHOLD", {"xsrc.income.stated_vs_documented"})
    with pytest.raises(ValueError, match="only legal for threshold-free"):
        build_seed()


# --------------------------------------------------------------------------- #
# FIX 3 / FIX 4 — the seed (fresh-DB source) carries no drifted vocab or shape
# --------------------------------------------------------------------------- #


def test_r3fix3_seed_confidence_mode_vocab() -> None:
    # No row at the retired "certain" vocab; the runner-emitted vocabulary only ({deterministic,computed}).
    modes = {r["confidence_mode"] for r in _seed_rows()}
    assert "certain" not in modes
    assert modes <= {"deterministic", "computed", None}


def test_r3fix4_seed_has_no_flat_applicability() -> None:
    # Every applicability is either NULL or a valid wire shape (only scope/triggers/required_inputs) —
    # no legacy flat {"purpose": ...} / {"program": ...} shape that degrades to couldn't-check when wired.
    for row in _seed_rows():
        app = row["applicability"]
        if app is None:
            continue
        assert set(app.keys()) <= _WIRE_KEYS, (
            f"{row['rule_id']} holds a non-wire applicability: {app}"
        )


def test_r5fix7_confidence_mode_sourced_from_evaluator() -> None:
    # FIX 7 — the seeded confidence_mode of a BUILT rule is exactly its evaluator's declared mode (the
    # single source of truth), never a playbook-layer guess that could drift.
    from app.verification.evaluators import get_evaluator, registered_rule_ids

    rows = {r["rule_id"]: r for r in _seed_rows()}
    for rule_id in registered_rule_ids():
        evaluator = get_evaluator(rule_id)
        assert evaluator is not None
        assert rows[rule_id]["confidence_mode"] == evaluator.confidence_mode.value
