"""End-to-end tests for the verification runner (LP-121) — snapshot → filter → evaluator → result.

Proves the pipeline end-to-end on AS-5 (gift-letter): the four buckets, the correctness match against
the live rule, evaluator gating (ready-to-run only), snapshot-built-once, runner-ensured registration,
and graceful handling of a rule with no evaluator. The live verification path is untouched.
"""

from decimal import Decimal

import pytest
from app.models.stated_financials import StatedAsset
from app.models.verification_rule import VerificationRule
from app.services.cross_source import assemble_cross_source_context
from app.services.cross_source_deterministic import build_cross_source_facts
from app.verification.cross_source.engine import evaluate_cross_source
from app.verification.evaluators import ConfidenceMode
from app.verification.runner import OutcomeSource, run_rule_engine
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.factories import (
    make_borrower,
    make_company,
    make_document,
    make_extraction,
    make_loan_file,
)

_AS5_RULE_ID = "xsrc.asset.gift_without_letter"
_AS5_APPLICABILITY = {
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


async def _insert_as5_rule(db: AsyncSession) -> None:
    db.add(
        VerificationRule(
            rule_id=_AS5_RULE_ID,
            name="Gift-fund documentation chain",
            applicability=_AS5_APPLICABILITY,
            params={},
            enabled=True,
        )
    )
    await db.flush()


async def _file(db: AsyncSession, slug: str):
    company = await make_company(db, slug=slug)
    lf = await make_loan_file(db, company=company)
    await make_borrower(db, loan_file=lf, first_name="Bansari", last_name="Patel")
    return company, lf


def _buckets(result) -> dict[str, list[str]]:
    return {
        "finding": [o.rule_id for o in result.findings],
        "satisfied": [o.rule_id for o in result.satisfied],
        "couldnt_check": [o.rule_id for o in result.couldnt_check],
        "doesnt_apply": [o.rule_id for o in result.doesnt_apply],
    }


# --------------------------------------------------------------------------- #
# The four buckets on AS-5
# --------------------------------------------------------------------------- #


async def test_as5_gift_no_letter_lands_in_findings(db_session: AsyncSession) -> None:
    _, lf = await _file(db_session, "run1")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    assert _AS5_RULE_ID in _buckets(result)["finding"]
    outcome = next(o for o in result.findings if o.rule_id == _AS5_RULE_ID)
    assert outcome.confidence == 1.0 and outcome.provenance  # verdict detail carried through


async def test_as5_gift_with_letter_lands_in_satisfied(db_session: AsyncSession) -> None:
    company, lf = await _file(db_session, "run2")
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
    await _insert_as5_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    assert _AS5_RULE_ID in _buckets(result)["satisfied"]


async def test_as5_no_asset_data_lands_in_couldnt_check(db_session: AsyncSession) -> None:
    _, lf = await _file(db_session, "run3")  # no assets at all
    await _insert_as5_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    assert _AS5_RULE_ID in _buckets(result)["couldnt_check"]
    outcome = next(o for o in result.couldnt_check if o.rule_id == _AS5_RULE_ID)
    assert outcome.reasons  # the reason is recorded


async def test_as5_no_gift_lands_in_doesnt_apply(db_session: AsyncSession) -> None:
    _, lf = await _file(db_session, "run4")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Checking", value=Decimal("25000"), holder_name="B"
        )
    )
    await _insert_as5_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    assert _AS5_RULE_ID in _buckets(result)["doesnt_apply"]


# --------------------------------------------------------------------------- #
# End-to-end correctness vs the live rule
# --------------------------------------------------------------------------- #


async def test_finding_matches_live_rule(db_session: AsyncSession) -> None:
    _, lf = await _file(db_session, "run5")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)

    # New engine (full pipeline).
    result = await run_rule_engine(db_session, lf)
    new_fires = _AS5_RULE_ID in _buckets(result)["finding"]

    # Live rule.
    context = await assemble_cross_source_context(db_session, lf)
    facts = await build_cross_source_facts(db_session, loan_file=lf, context=context)
    live_results = evaluate_cross_source(
        facts,
        program=lf.loan_program,
        loan_purpose=lf.loan_purpose,
        refinance_type=lf.refinance_type,
    )
    live_fires = any(r.rule.rule_id == _AS5_RULE_ID for r in live_results)

    assert new_fires is True and live_fires is True  # end-to-end verdict matches the live rule


# --------------------------------------------------------------------------- #
# Runner invariants
# --------------------------------------------------------------------------- #


async def test_evaluators_dispatch_only_for_ready_to_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, lf = await _file(db_session, "run6")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Checking", value=Decimal("25000"), holder_name="B"
        )
    )
    await _insert_as5_rule(db_session)  # no gift → AS-5 is doesn't-apply → must NOT be dispatched

    looked_up: list[str] = []
    import app.verification.runner as runner_mod

    real = runner_mod.get_evaluator
    monkeypatch.setattr(runner_mod, "get_evaluator", lambda rid: looked_up.append(rid) or real(rid))

    await run_rule_engine(db_session, lf)
    # Round-3 FIX 7 — the runner does a SINGLE registry lookup per ready-to-run rule; a doesn't-apply
    # rule is never looked up (never dispatched).
    assert _AS5_RULE_ID not in looked_up


async def test_snapshot_built_once(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, lf = await _file(db_session, "run7")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)

    import app.verification.runner as runner_mod

    calls = {"n": 0}
    real = runner_mod.assemble_fact_namespace

    async def _counting(db, loan_file, **kw):
        calls["n"] += 1
        return await real(db, loan_file, **kw)

    monkeypatch.setattr(runner_mod, "assemble_fact_namespace", _counting)
    await run_rule_engine(db_session, lf)
    assert calls["n"] == 1  # ONE snapshot per run, not per rule


async def test_runner_ensures_registration(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Empty + un-bootstrapped registry: the runner must repopulate it (fix #10 through the runner).
    import app.verification.evaluators.registry as reg

    monkeypatch.setattr(reg, "_bootstrapped", False)
    monkeypatch.setattr(reg, "_REGISTRY", {})

    _, lf = await _file(db_session, "run8")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    assert _AS5_RULE_ID in _buckets(result)["finding"]  # dispatched despite the emptied registry


async def test_rule_without_evaluator_does_not_crash(db_session: AsyncSession) -> None:
    _, lf = await _file(db_session, "run9")
    # An enabled rule with a valid empty applicability (→ ready-to-run) but NO registered evaluator
    # (a not-yet-built playbook rule).
    unbuilt_id = "pb.dt-1"
    db_session.add(
        VerificationRule(
            rule_id=unbuilt_id,
            name="DTI ratio vs limit (not built)",
            applicability={"scope": {}, "triggers": {}, "required_inputs": []},
            params={},
            enabled=True,
        )
    )
    await db_session.flush()

    result = await run_rule_engine(db_session, lf)  # must not raise
    outcome = next(o for o in result.couldnt_check if o.rule_id == unbuilt_id)
    assert "no evaluator" in outcome.reasons[0]


# --------------------------------------------------------------------------- #
# Post-review fixes (LP-121 hardening)
# --------------------------------------------------------------------------- #


async def test_fix1_malformed_applicability_row_does_not_crash_run(
    db_session: AsyncSession,
) -> None:
    # A malformed/legacy applicability row (the flat {program, purpose} shape extra="forbid" rejects)
    # must NOT abort the batch: the good rule still fires; the bad row is honestly couldn't-check.
    _, lf = await _file(db_session, "run10")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)
    db_session.add(
        VerificationRule(
            rule_id="pb.legacy.flat_shape",
            name="Legacy flat shape",
            applicability={"program": "fha", "purpose": "purchase"},  # rejected by extra="forbid"
            params={},
            enabled=True,
        )
    )
    await db_session.flush()

    result = await run_rule_engine(db_session, lf)  # must NOT raise or zero out
    assert _AS5_RULE_ID in _buckets(result)["finding"]  # the good rule still fires
    bad = next(o for o in result.couldnt_check if o.rule_id == "pb.legacy.flat_shape")
    assert "malformed applicability" in bad.reasons[0]  # bad row surfaced, never a silent pass


async def test_fix4_run_is_read_only(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The runner READS the snapshot — it persists nothing and writes no borrower↔document links.
    _, lf = await _file(db_session, "run11")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)
    await db_session.flush()  # drain pending state so `new`/`deleted` reflect only the run

    commits = {"n": 0}
    real_commit = db_session.commit

    async def _spy_commit() -> None:
        commits["n"] += 1
        await real_commit()

    monkeypatch.setattr(db_session, "commit", _spy_commit)

    await run_rule_engine(db_session, lf)
    assert commits["n"] == 0  # the runner commits nothing
    assert not db_session.new and not db_session.deleted  # and creates/removes no rows


async def test_fix5_unvalidated_rule_outcome_is_provisional(db_session: AsyncSession) -> None:
    # AS-5's threshold is not Priya-validated (validated defaults False) → the verdict is PROVISIONAL.
    _, lf = await _file(db_session, "run12")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)  # validated defaults False

    result = await run_rule_engine(db_session, lf)
    outcome = next(o for o in result.findings if o.rule_id == _AS5_RULE_ID)
    assert outcome.provisional is True


async def test_fix5_validated_rule_outcome_is_not_provisional(db_session: AsyncSession) -> None:
    _, lf = await _file(db_session, "run13")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    db_session.add(
        VerificationRule(
            rule_id=_AS5_RULE_ID,
            name="Gift-fund documentation chain",
            applicability=_AS5_APPLICABILITY,
            params={},
            enabled=True,
            validated=True,  # Priya-validated → authoritative, not provisional
        )
    )
    await db_session.flush()

    result = await run_rule_engine(db_session, lf)
    outcome = next(o for o in result.findings if o.rule_id == _AS5_RULE_ID)
    assert outcome.provisional is False


async def test_fix6_confidence_mode_is_enum_matching_seed_vocab(db_session: AsyncSession) -> None:
    # The outcome's confidence_mode is the ConfidenceMode enum — the SAME vocabulary the seed writes
    # to verification_rules.confidence_mode ({deterministic, computed}), joinable with no translation.
    _, lf = await _file(db_session, "run14")
    db_session.add(
        StatedAsset(
            loan_file_id=lf.id, asset_type="Gift of Cash", value=Decimal("10000"), holder_name="Mom"
        )
    )
    await _insert_as5_rule(db_session)

    result = await run_rule_engine(db_session, lf)
    outcome = next(o for o in result.findings if o.rule_id == _AS5_RULE_ID)
    assert outcome.confidence_mode is ConfidenceMode.DETERMINISTIC
    assert outcome.confidence_mode.value == "deterministic"  # seed vocab, no translation layer


# --------------------------------------------------------------------------- #
# Round-3 fixes
# --------------------------------------------------------------------------- #


async def test_r3fix5_couldnt_check_kinds_are_distinguishable_by_source(
    db_session: AsyncSession,
) -> None:
    # The trust surface (LP-162) needs to tell the two couldn't-check kinds apart. Both land in the same
    # bucket but carry a different `source`: "applicability" (missing inputs → fix/upload the file) vs
    # "evaluator" (had the data, couldn't reach a verdict).
    # (1) applicability couldn't-check: AS-5 on a file with NO asset data (can't tell if a gift exists).
    _, lf_a = await _file(db_session, "run15a")
    await _insert_as5_rule(db_session)
    res_a = await run_rule_engine(db_session, lf_a)
    cc_a = next(o for o in res_a.couldnt_check if o.rule_id == _AS5_RULE_ID)
    assert cc_a.source is OutcomeSource.APPLICABILITY

    # (2) evaluator couldn't-check: a gift asset exists (ready-to-run) but its amount wasn't extracted →
    # the evaluator ran and returned couldn't-check.
    _, lf_b = await _file(db_session, "run15b")
    db_session.add(
        StatedAsset(loan_file_id=lf_b.id, asset_type="Gift of Cash", value=None, holder_name="Mom")
    )
    await db_session.flush()
    res_b = await run_rule_engine(db_session, lf_b)
    cc_b = next(o for o in res_b.couldnt_check if o.rule_id == _AS5_RULE_ID)
    assert cc_b.source is OutcomeSource.EVALUATOR
    assert cc_a.source is not cc_b.source  # same bucket, distinguishable next-action


async def test_r3fix10_only_verdict_outcomes_are_provisional(db_session: AsyncSession) -> None:
    # provisional = "verdict pending validation" → legal ONLY on finding/satisfied. A doesn't-apply or a
    # couldn't-check made NO verdict, so it must never be badged provisional (even from an unvalidated rule).
    await _insert_as5_rule(
        db_session
    )  # ONE global AS-5 row (validated defaults False), reused below

    # doesn't-apply (no gift) — unvalidated, but no verdict → not provisional.
    _, lf_da = await _file(db_session, "run16a")
    db_session.add(
        StatedAsset(
            loan_file_id=lf_da.id, asset_type="Checking", value=Decimal("25000"), holder_name="B"
        )
    )
    await db_session.flush()
    res_da = await run_rule_engine(db_session, lf_da)
    assert next(o for o in res_da.doesnt_apply if o.rule_id == _AS5_RULE_ID).provisional is False

    # couldn't-check (no asset data) — also not provisional.
    _, lf_cc = await _file(db_session, "run16b")
    res_cc = await run_rule_engine(db_session, lf_cc)
    assert next(o for o in res_cc.couldnt_check if o.rule_id == _AS5_RULE_ID).provisional is False

    # a FINDING from the same unvalidated rule IS provisional (the verdict-bearing case).
    _, lf_f = await _file(db_session, "run16c")
    db_session.add(
        StatedAsset(
            loan_file_id=lf_f.id,
            asset_type="Gift of Cash",
            value=Decimal("10000"),
            holder_name="Mom",
        )
    )
    await db_session.flush()
    res_f = await run_rule_engine(db_session, lf_f)
    assert next(o for o in res_f.findings if o.rule_id == _AS5_RULE_ID).provisional is True


def test_r3fix7_run_rule_engine_uses_no_assert() -> None:
    # The None-guard is STRUCTURAL (get_evaluator None-check), not an `assert` (which `python -O` strips,
    # leaving an AttributeError on the hot path). Guard the invariant directly: the runner's main function
    # carries no assert statement.
    import ast
    import inspect

    import app.verification.runner as runner_mod

    tree = ast.parse(inspect.getsource(runner_mod.run_rule_engine))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
