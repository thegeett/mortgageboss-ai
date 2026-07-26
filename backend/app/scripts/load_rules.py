"""Project the rule + fact-tag files into the DB (LP-311). Safe to run on deploy.

Reads the version-controlled source files (rule_kinds.csv, specs/*.yaml, fact_tags.csv,
rule_tags.csv, tag_dependencies.csv) and reconciles the ``rules`` / ``tags`` /
``rule_tags`` / ``tag_dependencies`` tables to them (insert new / update changed /
remove vanished). Idempotent — unchanged files produce no writes — so it is safe to run
on every deploy. The DB is a PROJECTION of the files and is never hand-edited.

Not dev-only and not production-guarded: this is reference data, identical for every
company, and keeping it in sync in production is the point.

Usage::

    uv run python -m app.scripts.load_rules
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.database import async_session_maker
from app.verification.rules.projection import ProjectionResult, project_files_to_db

logger = structlog.get_logger(__name__)


async def _run() -> ProjectionResult:
    async with async_session_maker() as session:
        result = await project_files_to_db(session)
        await session.commit()
        return result


def main() -> None:
    result = asyncio.run(_run())
    logger.info(
        "rule_tag_projection_complete",
        changed=result.changed(),
        rules=vars(result.rules),
        tags=vars(result.tags),
        rule_tags=vars(result.rule_tags),
        tag_dependencies=vars(result.tag_dependencies),
    )
    verb = "applied changes" if result.changed() else "no changes (already in sync)"
    print(
        f"Projection {verb}: "
        f"rules(+{result.rules.inserted}/~{result.rules.updated}/-{result.rules.deleted}), "
        f"tags(+{result.tags.inserted}/~{result.tags.updated}/-{result.tags.deleted}), "
        f"rule_tags(+{result.rule_tags.inserted}/-{result.rule_tags.deleted}), "
        f"tag_dependencies(+{result.tag_dependencies.inserted}/-{result.tag_dependencies.deleted})"
    )


if __name__ == "__main__":
    main()
