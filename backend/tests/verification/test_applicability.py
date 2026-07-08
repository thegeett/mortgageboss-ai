"""Tests for the applicability filter engine (LP-119) — three-valued classification.

The CORE is the honesty contract / false-green guard: UNKNOWN (decision data absent) must resolve
to COULDNT_CHECK, never doesn't-apply or ready-to-run. Proven on AS-5 (gift-letter) + scope +
required-input + explicit false-green cases. No evaluator runs; no finding is produced.
"""

from decimal import Decimal

from app.models.stated_financials import StatedAsset
from app.models.verification_rule import VerificationRule
from app.verification.applicability import (
    ApplicabilityState,
    classify_from_json,
    classify_rules,
)
from app.verification.fact_namespace import assemble_fact_namespace
from app.verification.fact_namespace.snapshot import (
    AssetFacts,
    ComputedFacts,
    DocumentedFacts,
    DocumentRef,
    Fact,
    FactNamespace,
    FactSource,
    FileFacts,
)
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import make_borrower, make_company, make_loan_file

# AS-5's authored applicability (matches the seed + the LP-119 migration).
_AS5 = {
    "scope": {},
    "triggers": {
        "all": [
            {
                "kind": "entity_exists",
                "collection": "assets",
                "field": "is_gift",
                "op": "eq",
                "value": True,
            }
        ]
    },
    "required_inputs": [{"kind": "data_field", "path": "assets[].is_gift"}],
}


def _empty() -> Fact[Decimal]:
    return Fact[Decimal](value=None)


def _asset(is_gift: bool, raw: str = "Gift of Cash") -> AssetFacts:
    return AssetFacts(
        asset_type_raw=raw,
        asset_type_canonical=Fact[str](value=None),
        is_gift=is_gift,
        value=Fact.present(Decimal("10000"), source=FactSource.STATED),
        holder_name="Mom",
    )


def _snapshot(
    *,
    assets: list[AssetFacts] | None = None,
    program: Fact[str] | None = None,
    documents: list[DocumentRef] | None = None,
) -> FactNamespace:
    return FactNamespace(
        loan_file_id="LF-TEST",
        file=FileFacts(
            program=program or Fact.present("fha", source=FactSource.ENUM),
            loan_purpose=Fact[str](value=None),
            refinance_type=Fact[str](value=None),
            loan_amount=_empty(),
            note_amount=_empty(),
            note_rate_percent=_empty(),
        ),
        borrowers=[],
        property=None,
        liabilities=[],
        assets=assets or [],
        documents=documents or [],
        transactions=[],
        computed=ComputedFacts(
            ltv=Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE),
            cltv=_empty(),
            hcltv=_empty(),
            front_end_dti=_empty(),
            back_end_dti=_empty(),
            mi_monthly=_empty(),
            reserves_months=_empty(),
        ),
        documented=DocumentedFacts(
            documented_employers=Fact(value=[], source=FactSource.EXTRACTION),
            documented_income_monthly=Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE),
            credit_tradelines=Fact.missing(source=FactSource.ABSENT_NO_SCHEMA),
            documented_loan_amount=_empty(),
            occupancy_evidence=_empty(),
        ),
    )


# --------------------------------------------------------------------------- #
# AS-5 — the thin-slice proof
# --------------------------------------------------------------------------- #


def test_as5_gift_present_is_ready_to_run() -> None:
    # A gift exists → applies + data present → READY (the gift-letter check happens in LP-120).
    result = classify_from_json(_AS5, _snapshot(assets=[_asset(True)]))
    assert result.state is ApplicabilityState.READY_TO_RUN


def test_as5_no_gift_asset_doesnt_apply() -> None:
    # Assets present, none is a gift → trigger definitively FALSE → doesn't-apply (silent).
    result = classify_from_json(_AS5, _snapshot(assets=[_asset(False, "Checking")]))
    assert result.state is ApplicabilityState.DOESNT_APPLY


def test_as5_asset_data_absent_is_couldnt_check() -> None:
    # No asset data at all → can't confirm there's no gift → COULDNT_CHECK (the false-green guard).
    result = classify_from_json(_AS5, _snapshot(assets=[]))
    assert result.state is ApplicabilityState.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #


def test_empty_scope_applies_to_all() -> None:
    assert classify_from_json({"scope": {}}, _snapshot()).state is ApplicabilityState.READY_TO_RUN


def test_scope_mismatch_doesnt_apply() -> None:
    result = classify_from_json(
        {"scope": {"program": ["conventional"]}}, _snapshot()
    )  # file is fha
    assert result.state is ApplicabilityState.DOESNT_APPLY


def test_scope_match_ready() -> None:
    result = classify_from_json({"scope": {"program": ["fha"]}}, _snapshot())
    assert result.state is ApplicabilityState.READY_TO_RUN


def test_scope_value_absent_is_couldnt_check() -> None:
    # File program unknown → can't tell if the FHA rule applies → COULDNT_CHECK (not doesn't-apply).
    snap = _snapshot(program=Fact[str](value=None))
    result = classify_from_json({"scope": {"program": ["fha"]}}, snap)
    assert result.state is ApplicabilityState.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# Required inputs
# --------------------------------------------------------------------------- #


def test_required_document_absent_is_couldnt_check_named() -> None:
    rule = {"required_inputs": [{"kind": "document", "document_type": "credit_report"}]}
    result = classify_from_json(rule, _snapshot())
    assert result.state is ApplicabilityState.COULDNT_CHECK
    assert "document:credit_report" in result.missing_inputs


def test_required_derived_field_absent_is_couldnt_check() -> None:
    # computed.ltv is absent (uncomputable) in the snapshot → couldn't-check, named.
    rule = {"required_inputs": [{"kind": "derived_field", "path": "computed.ltv"}]}
    result = classify_from_json(rule, _snapshot())
    assert result.state is ApplicabilityState.COULDNT_CHECK
    assert "derived_field:computed.ltv" in result.missing_inputs


# --------------------------------------------------------------------------- #
# The false-green guard — UNKNOWN never collapses
# --------------------------------------------------------------------------- #


def test_unknown_trigger_never_collapses_to_apply_or_ready() -> None:
    # A trigger on an ABSENT fact (credit_tradelines — no schema) is UNKNOWN. It must resolve to
    # COULDNT_CHECK, NOT doesn't-apply and NOT ready-to-run. This is the whole point.
    rule = {
        "triggers": {
            "all": [
                {
                    "kind": "field_condition",
                    "path": "documented.credit_tradelines",
                    "op": "ne",
                    "value": None,
                }
            ]
        }
    }
    result = classify_from_json(rule, _snapshot(assets=[_asset(True)]))
    assert result.state is ApplicabilityState.COULDNT_CHECK
    assert result.state is not ApplicabilityState.DOESNT_APPLY
    assert result.state is not ApplicabilityState.READY_TO_RUN


def test_universal_rule_is_ready_to_run() -> None:
    # No scope, no triggers, no required inputs → universally relevant + runnable.
    assert classify_from_json(None, _snapshot()).state is ApplicabilityState.READY_TO_RUN
    assert classify_from_json({}, _snapshot()).state is ApplicabilityState.READY_TO_RUN


def test_false_precedence_over_unknown() -> None:
    # A definitively-FALSE scope wins over an UNKNOWN trigger → doesn't-apply (not couldn't-check).
    rule = {
        "scope": {"program": ["conventional"]},  # file is fha → FALSE
        "triggers": {
            "all": [
                {
                    "kind": "field_condition",
                    "path": "documented.credit_tradelines",
                    "op": "ne",
                    "value": None,
                }
            ]
        },
    }
    assert classify_from_json(rule, _snapshot()).state is ApplicabilityState.DOESNT_APPLY


# --------------------------------------------------------------------------- #
# Reads from the verification_rules table + a real assembled snapshot
# --------------------------------------------------------------------------- #


async def test_classify_rules_reads_applicability_from_table(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="appl")
    lf = await make_loan_file(db_session, company=company)
    lf.loan_program = None  # keep scope empty-relevant
    await make_borrower(db_session, loan_file=lf, first_name="Bansari", last_name="Patel")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await db_session.flush()

    # The AS-5 rule as a real verification_rules row (applicability read as DATA).
    rule = VerificationRule(
        rule_id="xsrc.asset.gift_without_letter",
        name="Gift-fund documentation chain",
        applicability=_AS5,
        enabled=True,
    )
    db_session.add(rule)
    await db_session.flush()

    snapshot = await assemble_fact_namespace(db_session, lf)
    grouped = classify_rules([rule], snapshot)

    assert [rc.rule_id for rc in grouped.ready_to_run] == ["xsrc.asset.gift_without_letter"]
    assert grouped.doesnt_apply == [] and grouped.couldnt_check == []


# --------------------------------------------------------------------------- #
# Review fixes (LP-119 hardening)
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402
from app.verification.fact_namespace.snapshot import (  # noqa: E402
    BorrowerFacts,
    IncomeItemFacts,
)
from pydantic import ValidationError  # noqa: E402


def _income_item(amount: Fact[Decimal]) -> IncomeItemFacts:
    return IncomeItemFacts(
        monthly_amount=amount,
        income_type_raw="Base Pay",
        income_type_canonical=Fact[str](value=None),
        employment_income=True,
    )


def _borrower(income_items: list[IncomeItemFacts]) -> BorrowerFacts:
    return BorrowerFacts(
        borrower_id="b1",
        position=1,
        is_primary=True,
        first_name="B",
        last_name="P",
        full_name="B P",
        ssn_masked=Fact[str](value=None),
        date_of_birth=Fact(value=None),
        current_address=Fact.missing(source=FactSource.ABSENT_NOT_PERSISTED),
        income_items=income_items,
        employers=[],
        documents=[],
    )


def test_fix1_required_input_inspects_named_field() -> None:
    # assets[].value with the value ABSENT → couldn't-check (named), not a false READY_TO_RUN.
    absent_val = AssetFacts(
        asset_type_raw="Gift of Cash",
        asset_type_canonical=Fact[str](value=None),
        is_gift=True,
        value=Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE),
        holder_name="Mom",
    )
    rule = {
        "triggers": {
            "all": [
                {
                    "kind": "entity_exists",
                    "collection": "assets",
                    "field": "is_gift",
                    "op": "eq",
                    "value": True,
                }
            ]
        },
        "required_inputs": [{"kind": "data_field", "path": "assets[].value"}],
    }
    r = classify_from_json(rule, _snapshot(assets=[absent_val]))
    assert r.state is ApplicabilityState.COULDNT_CHECK
    assert "data_field:assets[].value" in r.missing_inputs
    # present value → ready.
    assert (
        classify_from_json(rule, _snapshot(assets=[_asset(True)])).state
        is ApplicabilityState.READY_TO_RUN
    )


def test_fix1_nested_required_input_field() -> None:
    rule = {
        "required_inputs": [
            {"kind": "data_field", "path": "borrowers[].income_items[].monthly_amount"}
        ]
    }
    absent = _snapshot().model_copy(
        update={
            "borrowers": [
                _borrower([_income_item(Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE))])
            ]
        }
    )
    assert classify_from_json(rule, absent).state is ApplicabilityState.COULDNT_CHECK
    present = _snapshot().model_copy(
        update={
            "borrowers": [
                _borrower([_income_item(Fact.present(Decimal("8000"), source=FactSource.STATED))])
            ]
        }
    )
    assert classify_from_json(rule, present).state is ApplicabilityState.READY_TO_RUN


def test_fix3_flat_applicability_shape_raises() -> None:
    # The old flat {program, purpose} shape must now FAIL LOUDLY (extra="forbid"), not silently degrade.
    with pytest.raises(ValidationError):
        classify_from_json({"program": "fha", "purpose": "purchase"}, _snapshot())


def test_fix4_unknown_scope_dimension_fails_closed() -> None:
    # An unrecognized dimension must NOT become "no constraint → applies everywhere".
    r = classify_from_json({"scope": {"state": ["TX"]}}, _snapshot())
    assert r.state is ApplicabilityState.COULDNT_CHECK


def test_fix10_refi_scoped_rule_on_purchase_doesnt_apply_via_generic_path() -> None:
    # A refi-type-scoped rule is seeded with BOTH dims (FIX 10); on a purchase the loan_purpose
    # mismatch → FALSE → doesn't-apply via the generic FALSE-precedence path (no engine special case).
    snap = _snapshot().model_copy(
        update={
            "file": _snapshot().file.model_copy(
                update={"loan_purpose": Fact.present("purchase", source=FactSource.ENUM)}
            )
        }
    )
    r = classify_from_json(
        {"scope": {"loan_purpose": ["refinance"], "refinance_type": ["cash_out"]}}, snap
    )
    assert r.state is ApplicabilityState.DOESNT_APPLY


def test_fix6_present_none_computed_is_known() -> None:
    # computed.mi_monthly None with source=COMPUTED = "MI not required" = a real answer (known) → ready.
    snap = _snapshot().model_copy(
        update={
            "computed": _snapshot().computed.model_copy(
                update={"mi_monthly": Fact[Decimal](value=None, source=FactSource.COMPUTED)}
            )
        }
    )
    rule = {"required_inputs": [{"kind": "derived_field", "path": "computed.mi_monthly"}]}
    assert classify_from_json(rule, snap).state is ApplicabilityState.READY_TO_RUN
    # An unset scalar (source None) stays UNKNOWN → couldn't-check (the false-green guard preserved).
    assert classify_from_json(rule, _snapshot()).state is ApplicabilityState.COULDNT_CHECK


def test_fix2_present_none_unmapped_is_not_known() -> None:
    # SAME None value as FIX 6 — but here it came from UNMAPPED (a canonicalization miss), NOT a
    # computed "not required" answer. UNMAPPED / non-determination sources are NOT a known value →
    # couldn't-check, never a false pass (the honesty contract's other half from FIX 6).
    snap = _snapshot().model_copy(
        update={
            "computed": _snapshot().computed.model_copy(
                update={"mi_monthly": Fact[Decimal](value=None, source=FactSource.UNMAPPED)}
            )
        }
    )
    rule = {"required_inputs": [{"kind": "derived_field", "path": "computed.mi_monthly"}]}
    assert classify_from_json(rule, snap).state is ApplicabilityState.COULDNT_CHECK


def test_fix7_ragged_multi_borrower_any_present_is_ready() -> None:
    # 2 borrowers; the required nested field is present on ONE of them. FIX 7's `any` semantics: a
    # relevant element satisfies the input — a co-borrower missing the field must NOT sink the rule
    # into couldn't-check (that was the `all(...)` overshoot).
    rule = {
        "required_inputs": [
            {"kind": "data_field", "path": "borrowers[].income_items[].monthly_amount"}
        ]
    }
    present_b = _borrower([_income_item(Fact.present(Decimal("8000"), source=FactSource.STATED))])
    absent_b = _borrower(
        [_income_item(Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE))]
    ).model_copy(update={"borrower_id": "b2", "position": 2, "is_primary": False})
    snap = _snapshot().model_copy(update={"borrowers": [present_b, absent_b]})
    assert classify_from_json(rule, snap).state is ApplicabilityState.READY_TO_RUN
