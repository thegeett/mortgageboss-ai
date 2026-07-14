"""Runtime read accessors for the rule + fact-tag projection (LP-311).

Thin, read-only DB helpers over the ``rules`` / ``tags`` / ``rule_tags`` /
``tag_dependencies`` projection tables (populated by
:mod:`app.verification.rules.projection`). These are the runtime read seam the
engine will use later; they never write.

Note on ``load_rule_spec`` (specs.py): its signature is preserved as the swap seam
and it stays FILE-BACKED for now (LP-311, ADR-250) — the full spec is also mirrored
into ``rules.spec``, and :func:`get_rule` exposes it, so a DB-backed spec source is a
later drop-in without changing callers.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule
from app.models.tag import RuleTag, Tag, TagDependency


async def get_rule(session: AsyncSession, rule_id: str) -> Rule | None:
    """Return the rule with this ``rule_id``, or None if it is not projected."""
    return (await session.scalars(select(Rule).where(Rule.rule_id == rule_id))).one_or_none()


async def get_tag(session: AsyncSession, tag_id: str) -> Tag | None:
    """Return the fact-tag definition with this ``tag_id``, or None."""
    return (await session.scalars(select(Tag).where(Tag.tag_id == tag_id))).one_or_none()


async def tags_for_rule(session: AsyncSession, rule_id: str) -> list[Tag]:
    """Return the fact-tags this rule requires (from ``rule_tags``), tag_id order."""
    stmt = (
        select(Tag)
        .join(RuleTag, RuleTag.tag_id == Tag.tag_id)
        .where(RuleTag.rule_id == rule_id)
        .order_by(Tag.tag_id)
    )
    return list((await session.scalars(stmt)).all())


async def rules_using_tag(session: AsyncSession, tag_id: str) -> list[Rule]:
    """Return the rules that require this tag (from ``rule_tags``), rule_id order."""
    stmt = (
        select(Rule)
        .join(RuleTag, RuleTag.rule_id == Rule.rule_id)
        .where(RuleTag.tag_id == tag_id)
        .order_by(Rule.rule_id)
    )
    return list((await session.scalars(stmt)).all())


async def tag_dependencies(session: AsyncSession, tag_id: str) -> list[Tag]:
    """Return the tags this tag depends on (its DAG inputs), tag_id order.

    Empty for every tag today — the vocabulary declares no ``depends_on`` yet
    (LP-311 Phase 0); the query is ready for when it does.
    """
    stmt = (
        select(Tag)
        .join(TagDependency, TagDependency.depends_on_tag_id == Tag.tag_id)
        .where(TagDependency.tag_id == tag_id)
        .order_by(Tag.tag_id)
    )
    return list((await session.scalars(stmt)).all())
