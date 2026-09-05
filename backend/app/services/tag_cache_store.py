"""Load and save the per-file AI tag caches across runs (LP-644 §3).

`TagCaches` is rebuilt on every invocation and the only caller passes none, so a re-run re-pays for
every AI call the previous run already made. The API already short-circuits a re-run whose inputs are
byte-identical; **the case this covers is the one that endpoint does not** — a processor corrects one
document's type or uploads one more, and the file re-pays for all 44 documents' worth of AI work to
answer 43 questions it has already answered.

⚠️ ALL I/O HAPPENS OUTSIDE `run_verification`, AND THAT IS A CORRECTNESS CONSTRAINT, NOT A STYLE
CHOICE. The LP-644 §2 review established that `ai_cache` is now written by four concurrent groups and
is safe only because each group gets a disjoint sub-dict AND every write happens in an apply loop
containing no ``await``. The same await-free property is what lets the breaker count failures without
a lock. Putting a database round-trip inside one of those loops would silently break both: the loop
would yield, another group's coroutine would interleave, and "five consecutive failures" would stop
meaning what it says. So the caches are LOADED before the run and SAVED after it, by the Celery task,
and `run_verification` stays pure.

**Safe by construction.** The keys are content fingerprints — same input, same key, same answer a
fresh call would have produced. Nothing here decides anything; it only avoids re-asking. And only
outcomes the producers already marked cacheable in memory are ever written, so a failed, truncated or
malformed judgment still retries next run rather than being frozen into the file.

**A cache must never fail a run.** Every path here is best-effort: a row that cannot be decoded is
skipped, and a save that fails is logged and swallowed. The worst outcome this module may cause is a
re-ask.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.tag_cache import TagCacheEntry, TagCacheKind
from app.services.tag_correlation import dump_stage_b_entry, load_stage_b_entry
from app.services.tag_production import dump_stage_a_entry, load_stage_a_entry
from app.verification.tag_materialization.ai import dump_ai_group_entry, load_ai_group_entry

logger = get_logger(__name__)

#: The most entries kept per (loan file, kind). EVICTION, and the ticket asked for one: without a
#: bound "a file edited fifty times accumulates fifty generations of dead fingerprints".
#:
#: Oldest-first by `created_at`, which is a deliberately blunt policy. The exact one — evict what this
#: run did not READ — needs the producers to report which keys they touched, and the read happens in
#: the same await-free hot loops this module must not reach into. A cap bounds the table without
#: needing any of that: a dead fingerprint survives, but only until CAP newer ones displace it.
#:
#: 2,000 is roughly four full re-runs of a 44-document file with the transaction volume LF-ZE9N
#: carries, so the live set of a working file is never evicted by its own history.
_MAX_ENTRIES_PER_KIND = 2000

#: Materialization keys are namespaced by AI group, because two groups asking DIFFERENT questions
#: about the same subject fingerprint that subject identically. Without the prefix, one group's
#: answer would be served to another — a wrong answer, silently, from a cache that looked like it was
#: working.
_GROUP_SEPARATOR = "\x1f"


def _materialization_key(group_key: str, fingerprint: str) -> str:
    return f"{group_key}{_GROUP_SEPARATOR}{fingerprint}"


def _split_materialization_key(cache_key: str) -> tuple[str, str] | None:
    group_key, separator, fingerprint = cache_key.partition(_GROUP_SEPARATOR)
    if not separator or not group_key or not fingerprint:
        return None
    return group_key, fingerprint


async def load_tag_caches(db: AsyncSession, loan_file_id: UUID) -> Any:
    """Build a `TagCaches` for this file from its persisted entries.

    Imported lazily because `verification_run` imports the producers this module imports; a top-level
    import here would close the cycle. The alternative — moving `TagCaches` into its own module — is
    a wider change than a cache warrants.
    """
    from app.services.verification_run import TagCaches

    caches = TagCaches()
    loaded = skipped = 0
    # THE WHOLE READ IS GUARDED, not just the query. An earlier version wrapped only `db.execute`
    # and iterated outside the try — so a failure while CONSUMING the result escaped and failed the
    # verification, which is precisely what this module promises cannot happen. A cache is an
    # optimisation; the worst it may ever cost is a re-ask.
    try:
        rows = (
            await db.execute(
                select(TagCacheEntry).where(TagCacheEntry.loan_file_id == loan_file_id)
            )
        ).scalars()
        for row in rows:
            if row.cache_kind == TagCacheKind.STAGE_A:
                entry_a = load_stage_a_entry(row.value)
                if entry_a is None:
                    skipped += 1
                    continue
                caches.stage_a[row.cache_key] = entry_a
            elif row.cache_kind == TagCacheKind.STAGE_B:
                entry_b = load_stage_b_entry(row.value)
                if entry_b is None:
                    skipped += 1
                    continue
                caches.stage_b[row.cache_key] = entry_b
            elif row.cache_kind == TagCacheKind.MATERIALIZATION:
                split = _split_materialization_key(row.cache_key)
                entry_m = load_ai_group_entry(row.value) if split is not None else None
                if split is None or entry_m is None:
                    skipped += 1
                    continue
                group_key, fingerprint = split
                caches.materialization.setdefault(group_key, {})[fingerprint] = entry_m
            else:
                skipped += 1  # an unknown kind is an older/newer shape — ignored, never fatal
                continue
            loaded += 1
    except Exception as exc:
        # A PARTIAL load is kept rather than discarded: every entry already decoded is a valid
        # answer to a question whose input has not changed, and throwing them away would cost calls
        # for no gain. What is lost is only the tail of the read.
        logger.warning("tag_cache_load_failed", error=type(exc).__name__, loaded=loaded)
        return caches

    logger.info(
        "tag_cache_loaded",
        loan_file_id=str(loan_file_id),
        loaded=loaded,
        skipped=skipped,
        stage_a=len(caches.stage_a),
        stage_b=len(caches.stage_b),
        materialization=sum(len(g) for g in caches.materialization.values()),
    )
    return caches


def _rows_from(caches: Any, loan_file_id: UUID) -> list[dict[str, object]]:
    """Every cacheable entry the run now holds, as insertable row dicts."""
    rows: list[dict[str, object]] = []
    for fingerprint, entry_a in caches.stage_a.items():
        rows.append(
            {
                "loan_file_id": loan_file_id,
                "cache_kind": TagCacheKind.STAGE_A,
                "cache_key": fingerprint,
                "value": dump_stage_a_entry(entry_a),
            }
        )
    for fingerprint, entry_b in caches.stage_b.items():
        # The in-memory cache can hold an UNCACHEABLE verdict (it is still reused within the run);
        # persisting one would freeze a degraded answer into the file, so the line is drawn here.
        if not entry_b.cacheable:
            continue
        rows.append(
            {
                "loan_file_id": loan_file_id,
                "cache_kind": TagCacheKind.STAGE_B,
                "cache_key": fingerprint,
                "value": dump_stage_b_entry(entry_b),
            }
        )
    for group_key, group_cache in caches.materialization.items():
        for fingerprint, entry_m in group_cache.items():
            rows.append(
                {
                    "loan_file_id": loan_file_id,
                    "cache_kind": TagCacheKind.MATERIALIZATION,
                    "cache_key": _materialization_key(group_key, fingerprint),
                    "value": dump_ai_group_entry(entry_m),
                }
            )
    return rows


async def save_tag_caches(db: AsyncSession, loan_file_id: UUID, caches: Any) -> int:
    """Persist what this run's caches hold, then evict down to the per-kind cap. Flush-only.

    Returns the number of rows written (0 on any failure). Best-effort throughout: a verification
    that produced correct findings must not be failed by the bookkeeping that makes the NEXT one
    cheaper.
    """
    rows = _rows_from(caches, loan_file_id)
    if not rows:
        return 0
    try:
        # UPSERT rather than delete-then-insert: an entry already stored is the SAME answer (the key
        # is a content fingerprint), so re-writing it would churn `created_at` and make the eviction
        # order meaningless — a file's oldest live entries would look newest after every run.
        # `hit_count` is bumped so a future exact-eviction policy has the signal it needs.
        statement = pg_insert(TagCacheEntry).values(rows)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    TagCacheEntry.loan_file_id,
                    TagCacheEntry.cache_kind,
                    TagCacheEntry.cache_key,
                ],
                set_={"hit_count": TagCacheEntry.hit_count + 1},
            )
        )
        await _evict(db, loan_file_id)
    except Exception as exc:  # pragma: no cover - a cache write must never fail a run
        logger.warning("tag_cache_save_failed", error=type(exc).__name__, rows=len(rows))
        return 0

    logger.info("tag_cache_saved", loan_file_id=str(loan_file_id), rows=len(rows))
    return len(rows)


async def _evict(db: AsyncSession, loan_file_id: UUID) -> None:
    """Trim each kind to `_MAX_ENTRIES_PER_KIND`, oldest `created_at` first."""
    for kind in TagCacheKind.ALL:
        keep = (
            select(TagCacheEntry.id)
            .where(
                TagCacheEntry.loan_file_id == loan_file_id,
                TagCacheEntry.cache_kind == kind,
            )
            .order_by(TagCacheEntry.created_at.desc())
            .limit(_MAX_ENTRIES_PER_KIND)
            .scalar_subquery()
        )
        await db.execute(
            delete(TagCacheEntry).where(
                TagCacheEntry.loan_file_id == loan_file_id,
                TagCacheEntry.cache_kind == kind,
                TagCacheEntry.id.not_in(keep),
            )
        )


__all__ = ["load_tag_caches", "save_tag_caches"]
