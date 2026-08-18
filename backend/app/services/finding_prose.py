"""LP-527 — the composition PASS: enrich persisted findings, cache by facts, never break a verdict.

Runs AFTER the findings are written. It reads them, asks a model to rewrite the text of each, and
writes back only `message` and `how_to_fix`. Nothing else is touched: not the verdict, not the outcome,
not the tags, not the reconcile identity. A total failure of this pass leaves a fully correct run whose
findings read exactly as the templates wrote them.

⚠️ PER FINDING, NOT PER RULE, AND NOT ONE BATCHED CALL. Batching is cheaper on a cold cache and worse
everywhere else: a single changed finding would invalidate a whole batch (defeating the cache, which is
the point), one malformed response would cost every finding its prose instead of one, and item 17 of 25
gets less of the model's attention than item 1 — the position degradation this codebase already avoids
in the judgment evaluator. Concurrency is bounded the same way that evaluator bounds it.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.finding_prose import Composition, FactSummary, compose
from app.core.logging import get_logger
from app.models.finding import Finding
from app.models.finding_prose import FindingProse
from app.verification.rule_engine.reasons import fact_label

logger = get_logger(__name__)

# The same bound the judgment evaluator uses: enough to keep the pass short, low enough that a large
# file cannot burst into a hundred simultaneous calls and trip a rate limit.
_MAX_CONCURRENT = 8


def summarize(finding: Finding, *, rule_name: str) -> FactSummary:
    """The ONLY input a composition may draw on — assembled from the finding, never from the snapshot.

    Deliberately narrow. A composer that could reach the whole snapshot would be free to mention facts
    the rule never considered, and a processor reading a finding is entitled to assume the sentence
    describes what the check actually looked at.
    """
    facts = {
        fact_label(str(tag.get("tag_id", ""))): str(tag.get("value", ""))
        for tag in (finding.load_bearing_tags or [])
        if tag.get("tag_id") and tag.get("value") not in (None, "")
    }
    details = finding.details or {}
    return FactSummary(
        rule_name=rule_name,
        subject=str(finding.subject_key or "this loan file"),
        problem=finding.message,
        fix=details.get("how_to_fix") if isinstance(details.get("how_to_fix"), str) else None,
        facts=facts,
    )


async def _cached(db: AsyncSession, keys: list[str]) -> dict[str, Composition]:
    if not keys:
        return {}
    rows = (
        (await db.execute(select(FindingProse).where(FindingProse.fact_hash.in_(keys))))
        .scalars()
        .all()
    )
    return {row.fact_hash: Composition(row.action, row.why) for row in rows}


async def _store(db: AsyncSession, key: str, composition: Composition) -> None:
    """Upsert — two loan files can compose the same facts concurrently, and neither should fail."""
    await db.execute(
        insert(FindingProse)
        .values(fact_hash=key, action=composition.action, why=composition.why)
        .on_conflict_do_nothing(index_elements=["fact_hash"])
    )


async def compose_findings(
    db: AsyncSession, findings: list[Finding], *, rule_names: dict[str, str]
) -> int:
    """Rewrite what can be rewritten; leave the rest exactly as the templates wrote it.

    Returns how many findings were changed. Never raises: a composition pass that fails must not fail a
    verification run whose verdicts are already correct and already persisted.
    """
    summaries = {
        finding.id: summarize(finding, rule_name=rule_names.get(finding.rule_id, finding.rule_id))
        for finding in findings
        if finding.message
    }
    keys = {fid: summary.cache_key() for fid, summary in summaries.items()}
    cache = await _cached(db, list(dict.fromkeys(keys.values())))

    misses = [fid for fid, key in keys.items() if key not in cache]
    if misses:
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        async def _one(finding_id: UUID) -> tuple[UUID, Composition | None]:
            async with semaphore:
                return finding_id, await compose(summaries[finding_id])

        for finding_id, composition in await asyncio.gather(*(_one(fid) for fid in misses)):
            if composition is not None:
                cache[keys[finding_id]] = composition
                await _store(db, keys[finding_id], composition)

    changed = 0
    for finding in findings:
        composition = cache.get(keys.get(finding.id, ""))
        if composition is None:
            continue  # rejected, failed, or not summarizable — the template stands
        finding.message = composition.message
        changed += 1

    logger.info(
        "finding_prose_pass_done",
        findings=len(findings),
        composed=changed,
        cache_hits=len(summaries) - len(misses),
    )
    return changed


__all__ = ["compose_findings", "summarize"]
