"""LP-563 — a rule DECLARES the structured change Apply performs.

Apply is the only action that changes the LOAN rather than the finding, so what it writes has to be
declared as data on the rule rather than inferred at the point of clicking. The declaration is
resolved per subject from that subject's tags, and reaches the finding as `details["apply"]`.

The safety property is that an unresolvable value produces NO apply block, not a partial one.
"""

from __future__ import annotations

from app.verification.rule_engine.deterministic import _resolve_apply
from app.verification.rules.specs import ApplySpec, ApplyValue, load_rule_spec
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=None,
        reasoning="fixture",
        source_facts=("s",),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.B,
    )


_SPEC = ApplySpec(
    action="add_liability",
    fields={
        "holder_name": ApplyValue(tag="liab.creditor_name"),
        "type": ApplyValue(literal="Installment"),
    },
)


def test_a_declared_change_resolves_from_the_subjects_own_tags() -> None:
    resolved = _resolve_apply(_SPEC, {"liab.creditor_name": _tag("AMEX")})

    assert resolved == {"action": "add_liability", "holder_name": "AMEX", "type": "Installment"}


def test_a_missing_value_produces_NO_apply_rather_than_a_partial_one() -> None:
    """The safety of the whole mechanism. A `correct_purchase_price` with no price would write a null
    over a real figure; a half-filled `add_liability` would create a debt with no payment. Absent means
    the button does not appear — which is also why `can_apply` is computed from this and not from the
    rule having declared something."""
    assert _resolve_apply(_SPEC, {}) is None


def test_an_unknown_tag_value_is_treated_as_missing() -> None:
    """ "unknown" is the vocabulary's abstain. Writing the literal string "unknown" into a money column
    is the kind of silent corruption the §8 contract exists to prevent."""
    assert _resolve_apply(_SPEC, {"liab.creditor_name": _tag("unknown")}) is None


# --------------------------------------------------------------------------------------------- #
# THE TWO RULES THAT CAN CARRY ONE TODAY
# --------------------------------------------------------------------------------------------- #
def test_pc2_writes_the_CONTRACT_price_not_the_applications() -> None:
    """The direction is the whole correctness of the action. PC-2 compares the price the purchase
    contract states against the one the application carries; a mismatch means the APPLICATION is
    wrong. Writing it the other way would edit the document's figure to match a data-entry error."""
    apply = load_rule_spec("PC-2").deterministic.apply

    assert apply is not None and apply.action == "correct_purchase_price"
    assert apply.fields["value"].tag == "contract.loan_sales_price"


def test_cr1_adds_the_undisclosed_debt_with_a_payment_and_a_name() -> None:
    """The canonical interlock example: a debt the file carries and the 1003 does not, so the DTI
    recomputes HIGHER — the conservative direction every apply moves."""
    apply = load_rule_spec("CR-1").deterministic.apply

    assert apply is not None and apply.action == "add_liability"
    # `holder_name` names WHICH debt; `monthly_payment` is what the DTI reads. Missing either resolves
    # to no apply rather than a debt with no payment.
    assert apply.fields["holder_name"].tag == "liab.creditor_name"
    assert apply.fields["monthly_payment"].tag == "liab.monthly_payment"


def test_every_declared_apply_names_an_action_the_engine_can_perform() -> None:
    """A typo'd action reaches `_incorporate_into_structured_data`, matches nothing, and raises at the
    point of clicking (LP-558). Catching it at load is cheaper than catching it in front of a
    processor."""
    import pathlib

    import yaml

    known = {
        "add_liability",
        "correct_income",
        "correct_liability_payment",
        "correct_purchase_price",
        "correct_valuation",
        # LP-573 — DT-8's remediation. Not a money edit: it records that an obligation does not
        # survive closing, and the DTI drops it from the back-end ratio as a consequence.
        "exclude_liability_paid_off",
    }
    for path in sorted(pathlib.Path("app/verification/rules/specs").glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        # LP-564 — `deterministic` ONLY. A judgment rule cannot declare an apply (the field is gone),
        # and scanning both blocks was how a judgment `apply:` would have passed CI while producing
        # nothing — the guard would have vouched for a declaration the engine never reads.
        declared = (document.get("deterministic") or {}).get("apply")
        if declared:
            assert declared["action"] in known, f"{path.stem}: {declared['action']}"
        assert "apply" not in (document.get("judgment") or {}), (
            f"{path.stem}: a judgment rule declared an apply, which no evaluator resolves"
        )
