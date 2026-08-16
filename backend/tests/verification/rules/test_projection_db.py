"""LP-311: the files -> DB projection loader + runtime accessors (DB-backed)."""

from __future__ import annotations

import pytest
from app.models.rule import Rule
from app.models.tag import RuleTag, Tag, TagDependency
from app.verification.rules import projection
from app.verification.rules.accessors import (
    get_rule,
    get_tag,
    rules_using_tag,
    tag_dependencies,
    tags_for_rule,
)
from app.verification.rules.projection import (
    load_desired_rule_tags,
    load_desired_rules,
    load_desired_tags,
    project_files_to_db,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.scalar(select(func.count()).select_from(model))) or 0


async def test_projection_counts_match_files(db_session: AsyncSession) -> None:
    result = await project_files_to_db(db_session)

    assert await _count(db_session, Rule) == len(load_desired_rules())
    assert await _count(db_session, Tag) == len(load_desired_tags())
    assert await _count(db_session, RuleTag) == len(load_desired_rule_tags())
    assert await _count(db_session, TagDependency) == 0

    # First run inserts everything, removes nothing.
    assert (
        result.rules.inserted == 136
    )  # LP-430 +IN-15; LP-433 +IN-16  # LP-509-D1 +IH-9 (hazard policy expired)
    assert (
        result.tags.inserted
        == 248  # LP-516 +1 (txn.readily_identifiable_source — AS-12's guideline-exemption fact)  # LP-509-D1 +2 (ins.expiration_date + ins.policy_expired — IH-9's parsed binder date and its derived loan verdict)  # LP-498 +1 (contract.credits_warrant_review)  # LP-496a +1 (program.conforming_eligibility — PE-3's program.fha_min_investment_met was already in fact_tags.csv)  # LP-495b +2 (OC-3's and DT-7's judgment output tags)  # LP-495a +4 (reo.statement_disclosure + reo.statement_payment_coverage — ONE matcher, ADR-375;
        # loe.is_explanation_letter — LO-2's 8-type applicability predicate; loe.completeness)
        # LP-494 (CO-3) +3 (condo.fidelity_present_raw, condo.fidelity_amount, ins.condo_fidelity_coverage); review +2 (condo.units_delinquent_over_60_days — the 60-day COUNT B4-2.2-02's cap is
        # actually stated on, plus the derived condo.delinquent_units_pct built from it; the parsed
        # generic delinquency_percentage it replaced carried whatever period the form chose); LP-494 +8 (the condo project lane: 5 CO-5 questionnaire reads, condo.reserve_adequacy, condo.project_eligibility, loan.application_received_date — condo.reserve_pct already exists in fact_tags.csv); LP-493 +1 (contract.personal_property_assessment); LP-492 +9 (the appraisal lane's tags); prior +1 (property.value_vs_price_gap); LP-491 +11 (TI-1/TI-2/TI-6's inputs, chain facts and judgment outputs); prior +4 (title.vested_owner_name/_2, contract.seller_name, title.vested_owner_matches); LP-490 review +2 (credit.largest_single_collection_balance — CR-10's DU matrix turns on an
        # INDIVIDUAL collection, which the aggregate cannot answer; credit.has_collections — its
        # applicability gate, since the predicate DSL is eq/ne and cannot compare a number);
        # LP-490 +10 (the credit AI cohort: liab.is_mortgage, liab.structured_history_confident, liab.mortgage_late_60_plus_last_12mo, liab.is_medical_collection, liab.collection_balance, credit.collection_aggregate_balance, credit.derogatory_months_elapsed, property.occupancy, and the two rule-judgment outputs credit.mortgage_history_assessment / credit.collection_treatment); LP-488 review +2 (property.valuation_amount, property.estimated_value — the LTV
        # worksheet's own appraised-basis fields, so MI-1 stops diverging from it on MISMO-only
        # files); LP-488 +5 (…, condo.questionnaire_present); prior +4 (loan.ltv_percent, loan.note_amount, loan.refinance_type, mi.fha_ufmip_percent); prior LP-488 +3 (loan.ltv_percent, loan.note_amount, loan.refinance_type); LP-487 +6 (IH-2/IH-7's parsed inputs: ins.mortgagee_name, loan.lender_name_cd, loan.lender_name_le, condo.master_policy_number, condo.master_policy_basis_raw, condo.master_liability_limit — their two CONCLUSION tags already exist in fact_tags.csv); LP-485 +3 (the date-compare family); LP-453 +2 (credit.tradeline_count/_monthly_payment_total); LP-447 +1 (ins.dwelling_settlement_basis); LP-444 +1; LP-430 +2; LP-433 +1
    )  # +4 assets (LP-323-AS-B) +2 ID-5 (LP-389-A) +2 stmt +1 LP-417 (ins.loan_effective_date)
    # variance/co-holder (LP-400) +3 LP-410 derived-producer wave (days_until_closing / continuity / coverage)
    # +1 LP-407-2 (contract.loan_sales_price — the PC-2 loan promotion)
    # +1 LP-418 (income.is_self_employed — the deterministic per-borrower self-employment promotion)
    # +1 LP-422 (income.has_rental_income — the deterministic per-borrower rental presence off Schedule E)
    # LP-490 review +7: the four credit rules' catalog rows corrected to what each rule actually reads.
    # LP-491 review +3: the TI-* catalog rows were corrected to what each rule actually reads
    # (TI-1 pointed at title.parties_match, TI-2 at title.legal_desc_matches, TI-6 at
    # title.rapid_transfer — three live rules wired to dead vocabulary). Same defect the LP-490
    # review fixed for the credit rules, one ticket later.
    # LP-509-A1 +1: AS-2 -> txn.is_money_in (see test_fact_tags_files.test_desired_state_shape).
    assert result.rule_tags.inserted == 214
    assert result.rules.deleted == result.tags.deleted == 0


async def test_projection_is_idempotent(db_session: AsyncSession) -> None:
    await project_files_to_db(db_session)
    again = await project_files_to_db(db_session)

    assert not again.changed()
    assert again.rules.inserted == again.rules.updated == again.rules.deleted == 0
    assert again.tags.inserted == again.tags.updated == again.tags.deleted == 0
    assert again.rule_tags.inserted == again.rule_tags.deleted == 0


async def test_as1_projects_priya_validated_false_with_spec(db_session: AsyncSession) -> None:
    await project_files_to_db(db_session)

    as1 = await get_rule(db_session, "AS-1")
    assert as1 is not None
    # The contradiction resolved to the files, NOT the abandoned seed's TRUE.
    assert as1.priya_validated is False
    assert as1.threshold_needs_signoff is True
    assert as1.spec is not None
    assert as1.spec["rule_id"] == "AS-1"

    # A rule with no spec file has SQL NULL spec (none_as_null), not a JSON 'null'. Rules carrying a
    # spec now: AS-1 + OC-2 + ID-1..ID-9 (11) + IN-1..IN-5, IN-7..IN-14 (13, IN-6 deferred) = 24.
    with_spec = await db_session.scalar(
        select(func.count()).select_from(Rule).where(Rule.spec.isnot(None))
    )
    # 34 = +10 AS-2..AS-12 (LP-323-AS-B); +OC-1 (LP-406-4); +AS-8 (LP-406-2b); +IN-6 (LP-406-3b); +PC-7 (LP-406-1b).
    # +PC-2 = 39; +IH-3 = 40; +PC-3 = 41; +IN-15 (LP-430) = 42; +IN-16 (LP-433) = 43; +CR-4 (LP-444, inert) = 44;
    # +IH-1 (LP-447 — its spec now exists) = 45; +CL-1/CR-13/PR-6 (LP-485 — specs now exist, all held) = 48.
    assert (
        with_spec
        == 82  # LP-509-D1 +IH-9 (spec written, ACTIVE)  # LP-498 +FR-3 (spec written, ACTIVE)  # LP-496a +PE-1/PE-3 (specs written, both ACTIVE)  # LP-495b +OC-3/DT-7 (specs written, both held)  # +RE-1/DT-6/LO-2 (LP-495a — all three ACTIVE, deterministic, no ratification)  # +CO-3 (LP-494, un-dropped)  # +CO-4/CO-5 (LP-494, INERT — built against real fields, held until a completed questionnaire exists)  # +PC-5/PC-8 (LP-493)  # +PR-2/PR-3/PR-4/PR-5/PR-7 (LP-492)  # +TI-1/TI-2/TI-6 (LP-491)  # +CR-5/CR-6/CR-8/CR-10 (LP-490, INERT — specs without live rules)
    )  # +CR-1 (LP-490, INERT — a spec exists without the rule being live); +MI-1/MI-4/CO-1/AU-3 (LP-488); +IH-2/IH-7 (LP-487); +CR-12 (LP-486)


async def test_db_loses_to_files(db_session: AsyncSession) -> None:
    """A hand-mutated DB row is restored to the file's truth on the next run."""
    await project_files_to_db(db_session)

    as1 = await get_rule(db_session, "AS-1")
    assert as1 is not None
    as1.name = "HAND EDITED — SHOULD BE OVERWRITTEN"
    as1.priya_validated = True  # pretend someone flipped the gate in the DB
    await db_session.flush()

    result = await project_files_to_db(db_session)
    assert result.rules.updated == 1

    restored = await get_rule(db_session, "AS-1")
    assert restored is not None
    assert restored.name == load_desired_rules()["AS-1"]["name"]
    assert restored.priya_validated is False


async def test_projection_removes_rows_absent_from_files(db_session: AsyncSession) -> None:
    """A DB row not in the files (an orphan) is removed on the next run."""
    await project_files_to_db(db_session)

    db_session.add(
        Tag(
            tag_id="ghost.tag",
            entity="loan",
            value_type="number",
            description="not in files",
            produced_by="AI",
            extras={},
        )
    )
    await db_session.flush()
    assert await get_tag(db_session, "ghost.tag") is not None

    result = await project_files_to_db(db_session)
    assert result.tags.deleted == 1
    assert await get_tag(db_session, "ghost.tag") is None


async def test_projection_reflects_file_changes(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Change the 'files', re-run: DB reflects insert / update / remove."""
    await project_files_to_db(db_session)
    base_tags = load_desired_tags()

    # INSERT: a new standalone tag appears in the files.
    extra = dict(base_tags)
    extra["new.synthetic_tag"] = {
        "entity": "loan",
        "value_type": "number",
        "allowed_values": None,
        "description": "synthetic",
        "produced_by": "derived",
        "tag_role": None,
        "tag_version": 1,
        "extras": {},
    }
    monkeypatch.setattr(projection, "load_desired_tags", lambda: extra)
    result = await project_files_to_db(db_session)
    assert result.tags.inserted == 1
    assert await get_tag(db_session, "new.synthetic_tag") is not None

    # UPDATE: the tag's description changes.
    changed = dict(extra)
    changed["new.synthetic_tag"] = {**extra["new.synthetic_tag"], "description": "changed"}
    monkeypatch.setattr(projection, "load_desired_tags", lambda: changed)
    result = await project_files_to_db(db_session)
    assert result.tags.updated == 1
    row = await get_tag(db_session, "new.synthetic_tag")
    assert row is not None and row.description == "changed"

    # REMOVE: the tag disappears from the files.
    monkeypatch.setattr(projection, "load_desired_tags", lambda: base_tags)
    result = await project_files_to_db(db_session)
    assert result.tags.deleted == 1
    assert await get_tag(db_session, "new.synthetic_tag") is None


async def test_accessors(db_session: AsyncSession) -> None:
    await project_files_to_db(db_session)

    # get_rule / get_tag
    assert (await get_rule(db_session, "AS-1")) is not None
    assert (await get_rule(db_session, "NOPE-0")) is None
    assert (await get_tag(db_session, "txn.amount")) is not None
    assert (await get_tag(db_session, "txn.ghost")) is None

    # tags_for_rule matches the file mapping for AS-1.
    as1_tags = {t.tag_id for t in await tags_for_rule(db_session, "AS-1")}
    expected = {t for (r, t) in load_desired_rule_tags() if r == "AS-1"}
    assert as1_tags == expected
    assert "txn.is_money_in" in as1_tags

    # rules_using_tag is the inverse.
    users = {r.rule_id for r in await rules_using_tag(db_session, "txn.is_money_in")}
    assert "AS-1" in users and "AS-8" in users

    # tag_dependencies is empty for every tag today.
    assert await tag_dependencies(db_session, "txn.is_money_in") == []


async def test_migration_drops_phase351_orphans(db_session: AsyncSession) -> None:
    """The migration's orphan-drop SQL removes verification_rules / rule_change_audits,
    is FK-safe (CASCADE), and is a no-op on a fresh DB (IF EXISTS)."""
    # Simulate the dirty dev DB: the orphan tables exist with the FK between them.
    await db_session.execute(text("CREATE TABLE verification_rules (rule_id text PRIMARY KEY)"))
    await db_session.execute(
        text(
            "CREATE TABLE rule_change_audits ("
            "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
            "rule_id text REFERENCES verification_rules(rule_id))"
        )
    )
    await db_session.flush()

    # The exact statements the migration runs.
    await db_session.execute(text("DROP TABLE IF EXISTS rule_change_audits CASCADE"))
    await db_session.execute(text("DROP TABLE IF EXISTS verification_rules CASCADE"))

    present = (
        await db_session.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename IN ('verification_rules','rule_change_audits')"
            )
        )
    ).all()
    assert present == []

    # Re-running on a DB that no longer has them is a clean no-op.
    await db_session.execute(text("DROP TABLE IF EXISTS rule_change_audits CASCADE"))
    await db_session.execute(text("DROP TABLE IF EXISTS verification_rules CASCADE"))
