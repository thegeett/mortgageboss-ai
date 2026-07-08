"""Tests for the LP-118 rule registry — verification_rules + seed + rule_change_audit + loader.

Covers the HYBRID storage foundation ONLY: the seed populates the table, each insert is
audited, the 5 live rules are present with their real rule_ids (employer -> IN-5), the
structural/tunable split + the validated gate hold, and the read-only loader returns enabled
rules + fetches by rule_id. **No test executes a rule** — there is nothing to execute yet
(evaluators are LP-120); the loader returns inert data snapshots.

Uses the transaction-rollback ``db_session`` fixture. The seed is applied via the same sync
``seed_verification_rules`` the migration uses, run on the session's connection.
"""

from app.models.verification_rule import RuleChangeAudit, VerificationRule
from app.services.rule_registry import (
    get_rule,
    load_enabled_rules,
    rule_change_history,
    seed_verification_rules,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# The 5 rules LP-115 found firing today — must be present with their real rule_ids.
_LIVE_FIRING = {
    "xsrc.identity.name_consistency",
    "xsrc.address.dl_equals_subject",
    "xsrc.income.employer_name_consistency",
    "xsrc.income.employer_count_matches_items",
    "xsrc.asset.gift_without_letter",
}


async def _seed(db: AsyncSession) -> int:
    """Apply the version-controlled seed on the test transaction (the migration's code path)."""
    return await db.run_sync(lambda s: seed_verification_rules(s.connection()))


async def test_seed_populates_table_and_audit(db_session: AsyncSession) -> None:
    inserted = await _seed(db_session)
    assert inserted == 140  # 19 enabled (18 live + AS-8 built) + 121 not-yet-built playbook rows

    rule_count = (
        await db_session.execute(select(func.count()).select_from(VerificationRule))
    ).scalar()
    audit_count = (
        await db_session.execute(
            select(func.count())
            .select_from(RuleChangeAudit)
            .where(RuleChangeAudit.change_source == "seed_migration")
        )
    ).scalar()
    assert rule_count == 140
    assert audit_count == 140  # every insert is audited

    # Every seed audit row is a full-row insert.
    fields = (
        (await db_session.execute(select(RuleChangeAudit.changed_field).distinct())).scalars().all()
    )
    assert fields == ["__insert__"]


async def test_live_rules_present_with_real_ids(db_session: AsyncSession) -> None:
    await _seed(db_session)
    ids = set((await db_session.execute(select(VerificationRule.rule_id))).scalars().all())
    assert ids >= _LIVE_FIRING  # the 5 firing rules, exact rule_ids preserved (not renamed)

    employer = await db_session.get(VerificationRule, "xsrc.income.employer_name_consistency")
    assert employer is not None
    assert employer.playbook_id == "IN-5"  # the LP-117.5 mapping
    assert employer.enabled is True


async def test_structural_tunable_and_validated_gate(db_session: AsyncSession) -> None:
    await _seed(db_session)

    # validated defaults FALSE — the two Priya-confirmed thresholds, plus the no-threshold live-parity
    # rules certified true (AS-5 LP-122R; employer-count LP-124R) per the LP-122R criterion.
    validated = set(
        (
            await db_session.execute(
                select(VerificationRule.rule_id).where(VerificationRule.validated.is_(True))
            )
        )
        .scalars()
        .all()
    )
    assert (
        validated
        == {
            "xsrc.income.stated_vs_documented",
            "xsrc.asset.large_deposit_unsourced",
            "xsrc.asset.gift_without_letter",
            "xsrc.income.employer_count_matches_items",  # LP-124R (reproduces live; exact count, no threshold)
        }
    )

    # enabled=True for the 18 live code rules + AS-8 (built playbook rule, LP-123R); others disabled.
    enabled_count = (
        await db_session.execute(
            select(func.count())
            .select_from(VerificationRule)
            .where(VerificationRule.enabled.is_(True))
        )
    ).scalar()
    assert enabled_count == 19

    # A not-yet-built playbook row: structural fields null (it will not run until LP-120).
    not_built = await db_session.get(VerificationRule, "pb.id-5")
    assert not_built is not None
    assert not_built.enabled is False
    assert not_built.evaluator is None
    assert not_built.canonical_type is None
    assert not_built.playbook_id == "ID-5"


async def test_loader_returns_enabled_and_fetch_by_id(db_session: AsyncSession) -> None:
    await _seed(db_session)

    enabled = await load_enabled_rules(db_session)
    assert len(enabled) == 19  # 18 live + AS-8 (built playbook rule, LP-123R)
    assert all(rule.enabled for rule in enabled)
    # The loader returns INERT data snapshots — evaluator is a string-or-None, never callable.
    assert all(rule.evaluator is None or isinstance(rule.evaluator, str) for rule in enabled)
    # Ordered by rule_id for determinism.
    assert [r.rule_id for r in enabled] == sorted(r.rule_id for r in enabled)

    one = await get_rule(db_session, "xsrc.income.stated_vs_documented")
    assert one is not None
    assert one.playbook_id == "IN-1"
    assert one.validated is True
    assert one.params == {"variance_pct": 5}  # the Priya-confirmed authoring value

    assert await get_rule(db_session, "does.not.exist") is None


async def test_change_history_records_seed_insert(db_session: AsyncSession) -> None:
    await _seed(db_session)
    history = await rule_change_history(db_session, "xsrc.income.employer_name_consistency")
    assert len(history) == 1
    entry = history[0]
    assert entry["change_source"] == "seed_migration"
    assert entry["changed_field"] == "__insert__"
    assert entry["changed_by"] is None
    assert "IN-5" in (entry["new_value"] or "")  # the row JSON captured on insert


async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    first = await _seed(db_session)
    second = await _seed(db_session)  # re-running inserts nothing new
    assert first == 140
    assert second == 0

    rule_count = (
        await db_session.execute(select(func.count()).select_from(VerificationRule))
    ).scalar()
    audit_count = (
        await db_session.execute(select(func.count()).select_from(RuleChangeAudit))
    ).scalar()
    assert rule_count == 140
    assert audit_count == 140  # no duplicate audit rows either
