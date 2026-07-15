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
    assert result.rules.inserted == 133
    assert result.tags.inserted == 143
    assert result.rule_tags.inserted == 203
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

    # A rule with no spec file has SQL NULL spec (none_as_null), not a JSON 'null'. Four rules carry
    # a spec now: AS-1 + OC-2 (LP-324) + ID-2 + ID-4 (LP-325 re-expressed them as consistency specs).
    with_spec = await db_session.scalar(
        select(func.count()).select_from(Rule).where(Rule.spec.isnot(None))
    )
    assert with_spec == 4


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
