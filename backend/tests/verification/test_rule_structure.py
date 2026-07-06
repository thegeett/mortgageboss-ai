"""The uniform rule structure + the two linchpins (LP-74).

Asserts the two non-negotiables: every rule carries a **stable** ``rule_id``, and
its threshold is **data** the fixed logic reads (changing the data changes the
verdict — the threshold is not hardcoded in the comparison).
"""

from decimal import Decimal

from app.verification.rules.samples import CONV_DTI_BACK_END_MAX, SAMPLE_RULES
from app.verification.rules.schema import (
    Condition,
    Operator,
    satisfies,
)


def test_every_sample_rule_has_a_stable_rule_id() -> None:
    """Linchpin 1: each rule has a non-empty, unique, stable id."""
    ids = [rule.rule_id for rule in SAMPLE_RULES]
    assert all(ids)  # no empty ids
    assert len(ids) == len(set(ids))  # unique
    # The ids are stable, dotted-namespace strings overlays reference by.
    assert "conv.dti.back_end_max" in ids


def test_threshold_is_data_not_hardcoded() -> None:
    """Linchpin 2: the threshold lives in the Condition; the logic just reads it.

    The same :func:`satisfies` call yields a different verdict purely because the
    Condition *data* changed — proving the threshold is not baked into the logic.
    """
    observed = Decimal("48")
    loose = Condition(op=Operator.LE, value=Decimal("50"))
    strict = Condition(op=Operator.LE, value=Decimal("45"))

    assert satisfies(loose, observed) is True  # 48 <= 50
    assert satisfies(strict, observed) is False  # 48 <= 45


def test_satisfies_covers_each_operator() -> None:
    """The fixed comparison primitive implements every operator."""
    assert satisfies(Condition(op=Operator.LT, value=Decimal("10")), Decimal("9"))
    assert satisfies(Condition(op=Operator.LE, value=Decimal("10")), Decimal("10"))
    assert satisfies(Condition(op=Operator.GE, value=Decimal("10")), Decimal("10"))
    assert satisfies(Condition(op=Operator.GT, value=Decimal("10")), Decimal("11"))
    assert satisfies(Condition(op=Operator.EQ, value=Decimal("10")), Decimal("10"))
    assert satisfies(Condition(op=Operator.NE, value=Decimal("10")), Decimal("11"))


def test_with_condition_preserves_identity_and_logic() -> None:
    """Overriding a threshold changes only the Condition — not id/reads/layer."""
    patched = CONV_DTI_BACK_END_MAX.with_condition(
        Condition(op=Operator.LE, value=Decimal("45"), unit="percent"),
        overlay="sample-overlay-bank",
    )

    assert patched.rule_id == CONV_DTI_BACK_END_MAX.rule_id
    assert patched.reads == CONV_DTI_BACK_END_MAX.reads
    assert patched.layer == CONV_DTI_BACK_END_MAX.layer
    assert patched.condition.value == Decimal("45")
    assert patched.overlay_applied == "sample-overlay-bank"
    # The original definition is untouched (frozen, copy-on-write).
    assert CONV_DTI_BACK_END_MAX.condition.value == Decimal("50")
    assert CONV_DTI_BACK_END_MAX.overlay_applied is None


def test_rules_read_typed_field_paths_never_prose() -> None:
    """Each rule names the typed field path(s) it reads (structured handoff)."""
    for rule in SAMPLE_RULES:
        assert rule.reads  # non-empty
        assert all(isinstance(path, str) and "." in path for path in rule.reads)
