"""Tests for the evaluator framework + the AS-5 gift-letter evaluator (LP-120).

Covers the contract (finding/satisfied + confidence + provenance), the read-only/no-AI determinism
rule, the registry dispatch, and — the key correctness check — that the new AS-5 evaluator's verdict
MATCHES the current live ``xsrc.asset.gift_without_letter`` rule on the same file. No applicability
filtering, no couldn't-check/doesn't-apply produced here.
"""

from decimal import Decimal

import pytest
from app.models.stated_financials import StatedAsset
from app.services.cross_source import assemble_cross_source_context
from app.services.cross_source_deterministic import build_cross_source_facts
from app.verification.cross_source.engine import evaluate_cross_source
from app.verification.evaluators import (
    ConfidenceMode,
    Verdict,
    evaluate_rule,
    get_evaluator,
    registered_rule_ids,
)
from app.verification.evaluators.contract import computed_confidence
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
from tests.integration.factories import (
    make_borrower,
    make_company,
    make_document,
    make_extraction,
    make_loan_file,
)

_RULE_ID = "xsrc.asset.gift_without_letter"


def _empty() -> Fact[Decimal]:
    return Fact[Decimal](value=None)


def _gift_asset() -> AssetFacts:
    return AssetFacts(
        asset_type_raw="Gift of Cash",
        asset_type_canonical=Fact[str](value=None),
        is_gift=True,
        value=Fact.present(Decimal("10000"), source=FactSource.STATED),
        holder_name="Mom",
    )


def _gift_letter_doc() -> DocumentRef:
    return DocumentRef(
        document_id="d1",
        document_type="gift_letter",
        present=True,
        current_extraction_id="x",
        fields={"donor_name": "Mom"},
    )


def _snapshot(assets: list[AssetFacts], documents: list[DocumentRef]) -> FactNamespace:
    return FactNamespace(
        loan_file_id="LF",
        file=FileFacts(
            program=Fact[str](value=None),
            loan_purpose=Fact[str](value=None),
            refinance_type=Fact[str](value=None),
            loan_amount=_empty(),
            note_amount=_empty(),
            note_rate_percent=_empty(),
        ),
        borrowers=[],
        property=None,
        liabilities=[],
        assets=assets,
        documents=documents,
        transactions=[],
        computed=ComputedFacts(
            ltv=_empty(),
            cltv=_empty(),
            hcltv=_empty(),
            front_end_dti=_empty(),
            back_end_dti=_empty(),
            mi_monthly=_empty(),
            reserves_months=_empty(),
        ),
        documented=DocumentedFacts(
            documented_employers=Fact(value=[], source=FactSource.EXTRACTION),
            documented_income_monthly=_empty(),
            credit_tradelines=_empty(),
            documented_loan_amount=_empty(),
            occupancy_evidence=_empty(),
        ),
    )


# --------------------------------------------------------------------------- #
# The AS-5 evaluator — finding / satisfied
# --------------------------------------------------------------------------- #


def test_gift_without_letter_is_finding() -> None:
    result = evaluate_rule(_RULE_ID, _snapshot([_gift_asset()], []))
    assert result is not None
    assert result.verdict is Verdict.FINDING
    assert "no gift letter" in result.message


def test_gift_with_letter_is_satisfied() -> None:
    result = evaluate_rule(_RULE_ID, _snapshot([_gift_asset()], [_gift_letter_doc()]))
    assert result is not None
    assert result.verdict is Verdict.SATISFIED


def test_result_carries_full_confidence_and_provenance() -> None:
    result = evaluate_rule(_RULE_ID, _snapshot([_gift_asset()], []))
    assert result is not None
    assert result.confidence == 1.0
    assert result.confidence_mode is ConfidenceMode.DETERMINISTIC
    paths = {p.path for p in result.provenance}
    assert paths == {"assets[].is_gift", "documents[].document_type"}


# --------------------------------------------------------------------------- #
# Determinism — pure reader, no recompute / no AI at eval time
# --------------------------------------------------------------------------- #


def test_evaluator_does_not_recompute_or_call_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    # If the evaluator recomputed LTV/DTI or called AI, these would fire. It reads the snapshot only.
    def _boom(*a: object, **k: object) -> object:
        raise AssertionError("evaluator must not recompute / call AI at eval time")

    monkeypatch.setattr("app.services.ltv.build_ltv_calculation", _boom)
    monkeypatch.setattr("app.services.dti.build_dti_calculation", _boom)
    monkeypatch.setattr("app.ai.client.complete", _boom)

    snap = _snapshot([_gift_asset()], [])
    first = evaluate_rule(_RULE_ID, snap)
    second = evaluate_rule(_RULE_ID, snap)
    assert first == second  # pure + deterministic: same snapshot → identical result


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def test_registry_dispatch_and_unregistered() -> None:
    assert _RULE_ID in registered_rule_ids()
    assert get_evaluator(_RULE_ID) is not None
    assert get_evaluator("not.a.rule") is None
    assert evaluate_rule("not.a.rule", _snapshot([], [])) is None  # graceful, no crash


def test_computed_confidence_never_a_false_100() -> None:
    # The computed path (for IN-5 / blocker-fed rules) caps below 1.0 — never a false 100%.
    assert computed_confidence(1.0) < 1.0
    assert computed_confidence(0.85) == 0.85
    assert computed_confidence(-5) == 0.0


# --------------------------------------------------------------------------- #
# Correctness check — new verdict == live rule verdict on the same file
# --------------------------------------------------------------------------- #


async def _live_gift_finding(db: AsyncSession, loan_file) -> bool:
    """Whether the LIVE ``xsrc.asset.gift_without_letter`` rule fires on this file."""
    context = await assemble_cross_source_context(db, loan_file)
    facts = await build_cross_source_facts(db, loan_file=loan_file, context=context)
    results = evaluate_cross_source(
        facts,
        program=loan_file.loan_program,
        loan_purpose=loan_file.loan_purpose,
        refinance_type=loan_file.refinance_type,
    )
    return any(r.rule.rule_id == _RULE_ID for r in results)


async def _new_gift_finding(db: AsyncSession, loan_file) -> bool:
    snapshot = await assemble_fact_namespace(db, loan_file)
    result = evaluate_rule(_RULE_ID, snapshot)
    return result is not None and result.verdict is Verdict.FINDING


async def test_matches_live_rule_no_letter(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="ev1")
    lf = await make_loan_file(db_session, company=company)
    await make_borrower(db_session, loan_file=lf, first_name="Bansari", last_name="Patel")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await db_session.flush()

    live = await _live_gift_finding(db_session, lf)
    new = await _new_gift_finding(db_session, lf)
    assert live is True and new is True  # both fire — no gift letter


async def test_matches_live_rule_with_letter(db_session: AsyncSession) -> None:
    company = await make_company(db_session, slug="ev2")
    lf = await make_loan_file(db_session, company=company)
    await make_borrower(db_session, loan_file=lf, first_name="Bansari", last_name="Patel")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    gift = await make_document(
        db_session, loan_file=lf, company=company, document_type="gift_letter"
    )
    await make_extraction(
        db_session, document=gift, data={"donor_name": {"value": "Mom", "source": {}}}
    )
    await db_session.flush()

    live = await _live_gift_finding(db_session, lf)
    new = await _new_gift_finding(db_session, lf)
    assert live is False and new is False  # both clear — gift letter present


# --------------------------------------------------------------------------- #
# Review fixes (LP-120 hardening)
# --------------------------------------------------------------------------- #


def test_fix8_gift_with_no_value_is_couldnt_check() -> None:
    # An is_gift asset with value None → gift_total 0. The live rule makes NO verdict (its gift facts
    # are (None, None) → no check). So the evaluator must NOT emit a nonsense "gift of 0" FINDING (FIX 2)
    # AND must NOT assert SATISFIED for a check that never ran (FIX 8) — it is COULDN'T-CHECK, honestly.
    zero_gift = AssetFacts(
        asset_type_raw="Gift of Cash",
        asset_type_canonical=Fact[str](value=None),
        is_gift=True,
        value=Fact.missing(source=FactSource.ABSENT_UNCOMPUTABLE),
        holder_name="Mom",
    )
    result = evaluate_rule(_RULE_ID, _snapshot([zero_gift], []))
    assert result is not None and result.verdict is Verdict.COULDNT_CHECK


async def test_fix2_matches_live_rule_gift_value_none(db_session: AsyncSession) -> None:
    # Correctness re-verification: a gift asset with NO value → both live and new produce NO finding.
    company = await make_company(db_session, slug="ev3")
    lf = await make_loan_file(db_session, company=company)
    await make_borrower(db_session, loan_file=lf, first_name="Bansari", last_name="Patel")
    db_session.add(
        StatedAsset(loan_file_id=lf.id, asset_type="Gift of Cash", value=None, holder_name="Mom")
    )
    await db_session.flush()

    assert await _live_gift_finding(db_session, lf) is False
    assert await _new_gift_finding(db_session, lf) is False


def test_fix10_registry_self_bootstraps_when_emptied(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with an empty, un-bootstrapped registry, a read repopulates it (no reliance on the
    # package __init__ side effect) → AS-5 still dispatches.
    import app.verification.evaluators.registry as reg

    monkeypatch.setattr(reg, "_bootstrapped", False)
    monkeypatch.setattr(reg, "_REGISTRY", {})
    assert reg.get_evaluator(_RULE_ID) is not None
    assert reg.evaluate_rule(_RULE_ID, _snapshot([_gift_asset()], [])) is not None
