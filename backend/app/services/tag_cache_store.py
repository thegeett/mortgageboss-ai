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

⚠️ "SAME INPUT, SAME ANSWER" IS ONLY TRUE IF THE QUESTION IS ALSO THE SAME, and a fingerprint does
not know about the question. `content_fingerprint` hashes the SUBJECT — the four raw transaction
Fields, the deposit-plus-candidates context, the AI group's subject context — and nothing about the
prompt, the tag set or the model that will be asked about it. In memory that gap could not be
observed: the cache died with the run, so an edited prompt took effect on the very next one.
PERSISTED, it becomes permanent staleness — the failure the rest of this module is written to avoid:

  * edit `STAGE_A_TRANSACTION_SYSTEM_PROMPT` (or Stage B's, or a group's `system_prompt`), and every
    already-cached subject is served the OLD model's answer for as long as its content is unchanged;
  * ADD a tag to an AI group, and it is worse than stale. `produce_ai_group_tags` skips a subject
    whose fingerprint is cached, so the new tag is never asked for, and `_build_tag` renders the
    missing short as ``unknown`` with "tag value missing or malformed in structuring response" —
    an honest-looking abstention that no re-run can ever clear;
  * point `anthropic_model_reasoning` at a different model and none of its answers are used.

So every key carries a PRODUCER VERSION: a digest of the model id plus the prompt (plus the group's
tag ids, which is the case above). A row whose version is not the current one simply does not match
and is re-asked; it is never decoded, never "repaired", and ages out through the ordinary eviction
cap because nothing rewrites it. The cost of a prompt edit is one run at full price — which is what
it cost before this table existed.

**A cache must never fail a run.** Every path here is best-effort: a row that cannot be decoded is
skipped, and a save that fails is logged and swallowed. The worst outcome this module may cause is a
re-ask.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tag_correlation import STAGE_B_SOURCING_SYSTEM_PROMPT
from app.ai.tag_production import STAGE_A_TRANSACTION_SYSTEM_PROMPT
from app.core.config import settings
from app.core.logging import get_logger
from app.models.tag_cache import TagCacheEntry, TagCacheKind
from app.services.tag_correlation import dump_stage_b_entry, load_stage_b_entry
from app.services.tag_production import dump_stage_a_entry, load_stage_a_entry
from app.verification.tag_materialization.ai import dump_ai_group_entry, load_ai_group_entry
from app.verification.tag_materialization.declarations import load_ai_groups

if TYPE_CHECKING:  # imported for TYPES only — the runtime import stays inside the functions.
    from app.services.verification_run import TagCaches

logger = get_logger(__name__)

#: The most entries kept per (loan file, kind). EVICTION, and the ticket asked for one: without a
#: bound "a file edited fifty times accumulates fifty generations of dead fingerprints".
#:
#: Oldest-first by `created_at`, which is a deliberately blunt policy — and blunter than it reads.
#: `created_at` is never churned (the upsert deliberately leaves it alone), so it records when a
#: fingerprint FIRST appeared, which is uncorrelated with whether it is still live. Eviction
#: therefore displaces long-stable entries just as readily as dead ones; what it buys is the bound
#: the ticket asked for ("a file edited fifty times accumulates fifty generations of dead
#: fingerprints"), not a preference for keeping the useful ones.
#:
#: The exact policy — evict what this run did not READ — needs the producers to report which keys
#: they touched, and those reads happen in the await-free hot loops this module must not reach into.
#: `hit_count` does NOT stand in for it: every row is loaded and re-saved every run, so a dead
#: fingerprint's count rises exactly as fast as a live one's (measured, not assumed).
#:
#: 2,000 is roughly four full re-runs of a 44-document file with the transaction volume LF-ZE9N
#: carries, so the live set of a working file is never evicted by its own history.
_MAX_ENTRIES_PER_KIND = 2000

#: Rows per INSERT statement. Not a tuning knob — a protocol ceiling. Postgres binds parameters in a
#: message whose parameter count is a signed 16-bit int, so asyncpg refuses any statement carrying
#: more than 32,767 of them, and each row here binds EIGHT (the four columns built by `_rows_from`
#: plus `hit_count`, `id`, `created_at` and `updated_at`, which SQLAlchemy fills per row from the
#: model's Python-side defaults). One statement therefore tops out at 4,095 rows, and the cap above
#: allows 6,000 — reachable on exactly the document-heavy files this cache exists for, where the save
#: would fail, be swallowed, and leave the cache permanently empty for the biggest files in the
#: system. 1,000 leaves generous headroom without making the save chatty.
_INSERT_CHUNK_ROWS = 1000

#: Materialization keys are namespaced by AI group, because two groups asking DIFFERENT questions
#: about the same subject fingerprint that subject identically. Without the prefix, one group's
#: answer would be served to another — a wrong answer, silently, from a cache that looked like it was
#: working.
_GROUP_SEPARATOR = "\x1f"


def _producer_version(*parts: str) -> str:
    """A short digest of everything that decides an answer OTHER than the subject's content.

    The model comes first because it applies to all three stages: every one of them calls
    `settings.anthropic_model_reasoning`, so a model swap invalidates the whole table at once.
    Twelve hex characters is 48 bits — a collision would have to be between two prompts that a
    human also cannot tell apart, and the cost of one is a stale answer for one stage until the
    next edit.
    """
    payload = "\x1e".join((settings.anthropic_model_reasoning, *parts))
    return sha256(payload.encode()).hexdigest()[:12]


def _stage_a_version() -> str:
    return _producer_version(STAGE_A_TRANSACTION_SYSTEM_PROMPT)


def _stage_b_version() -> str:
    return _producer_version(STAGE_B_SOURCING_SYSTEM_PROMPT)


def _materialization_versions() -> Mapping[str, str]:
    """One version per declared AI group. Built once per save/load, never per row.

    The group's TAG IDS are in the digest as well as its prompt, because adding a tag to a group is
    the case that fails worst: the subject is skipped as a cache hit and the new tag renders as a
    permanent, honest-looking ``unknown``. A group that has been deleted from the declarations has
    no version here, so its rows stop matching — which is the right answer for a question nobody
    asks any more.
    """
    return {
        key: _producer_version(group.system_prompt, *group.tag_ids)
        for key, group in load_ai_groups().items()
    }


def _versioned_key(version: str, fingerprint: str) -> str:
    return f"{version}{_GROUP_SEPARATOR}{fingerprint}"


def _split_versioned_key(cache_key: str, expected_version: str) -> str | None:
    version, separator, fingerprint = cache_key.partition(_GROUP_SEPARATOR)
    if not separator or version != expected_version or not fingerprint:
        return None
    return fingerprint


def _materialization_key(group_key: str, version: str, fingerprint: str) -> str:
    return f"{group_key}{_GROUP_SEPARATOR}{version}{_GROUP_SEPARATOR}{fingerprint}"


def _split_materialization_key(
    cache_key: str, versions: Mapping[str, str]
) -> tuple[str, str] | None:
    parts = cache_key.split(_GROUP_SEPARATOR)
    if len(parts) != 3:
        return None
    group_key, version, fingerprint = parts
    if not group_key or not fingerprint or versions.get(group_key) != version:
        return None
    return group_key, fingerprint


async def load_tag_caches(db: AsyncSession, loan_file_id: UUID) -> TagCaches:
    """Build a `TagCaches` for this file from its persisted entries.

    The runtime import is deferred to keep this module importable without pulling in the whole
    orchestrator, but the TYPE is imported under `TYPE_CHECKING` and used for real. It was
    previously annotated `Any` on the grounds that a top-level import "would close the cycle";
    there is no cycle — `verification_run` does not import this module, directly or otherwise —
    and `Any` silently switched mypy off at this module's only public boundary, which is exactly
    where a codec returning the wrong shape would have shown up.
    """
    from app.services.verification_run import TagCaches

    caches = TagCaches()
    loaded = skipped = stale = 0
    # The producer versions this deploy would ask WITH. A row keyed on any other one is a question
    # this code no longer asks, so it is not decoded at all — see the module docstring.
    stage_a_version = _stage_a_version()
    stage_b_version = _stage_b_version()
    group_versions = _materialization_versions()
    # THE WHOLE READ IS GUARDED, not just the query. An earlier version wrapped only `db.execute`
    # and iterated outside the try — so a failure while CONSUMING the result escaped and failed the
    # verification, which is precisely what this module promises cannot happen. A cache is an
    # optimisation; the worst it may ever cost is a re-ask.
    try:
        # SAVEPOINT, and it is the difference between "degrades to a re-ask" and "fails the run".
        # Swallowing a DB error is only best-effort for NON-DB errors: a failed statement ABORTS the
        # transaction, so every later statement on this session raises
        # `InFailedSQLTransactionError` — and the caller runs the ENTIRE verification on this
        # session afterwards. The realistic trigger is deploying this code ahead of its migration:
        # the table is missing, the load "degrades" to empty exactly as designed, and then every
        # verification on the box fails. `begin_nested()` contains it, which is the same fix
        # `verification_run` already carries for `snapshot_findings` and the needs sync.
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(TagCacheEntry).where(TagCacheEntry.loan_file_id == loan_file_id)
                )
            ).scalars()
            for row in rows:
                if row.cache_kind == TagCacheKind.STAGE_A:
                    fingerprint_a = _split_versioned_key(row.cache_key, stage_a_version)
                    if fingerprint_a is None:
                        stale += 1
                        continue
                    entry_a = load_stage_a_entry(row.value)
                    if entry_a is None:
                        skipped += 1
                        continue
                    caches.stage_a[fingerprint_a] = entry_a
                elif row.cache_kind == TagCacheKind.STAGE_B:
                    fingerprint_b = _split_versioned_key(row.cache_key, stage_b_version)
                    if fingerprint_b is None:
                        stale += 1
                        continue
                    entry_b = load_stage_b_entry(row.value)
                    if entry_b is None:
                        skipped += 1
                        continue
                    caches.stage_b[fingerprint_b] = entry_b
                elif row.cache_kind == TagCacheKind.MATERIALIZATION:
                    split = _split_materialization_key(row.cache_key, group_versions)
                    if split is None:
                        stale += 1
                        continue
                    entry_m = load_ai_group_entry(row.value)
                    if entry_m is None:
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
        # A non-zero `stale` right after a deploy is the prompt/model change being re-asked, not a
        # fault. A non-zero one on a quiet deploy is worth looking at.
        stale=stale,
        stage_a=len(caches.stage_a),
        stage_b=len(caches.stage_b),
        materialization=sum(len(g) for g in caches.materialization.values()),
    )
    return caches


def _rows_from(caches: TagCaches, loan_file_id: UUID) -> list[dict[str, object]]:
    """Every cacheable entry the run now holds, as insertable row dicts."""
    rows: list[dict[str, object]] = []
    stage_a_version = _stage_a_version()
    stage_b_version = _stage_b_version()
    group_versions = _materialization_versions()
    for fingerprint, entry_a in caches.stage_a.items():
        rows.append(
            {
                "loan_file_id": loan_file_id,
                "cache_kind": TagCacheKind.STAGE_A,
                "cache_key": _versioned_key(stage_a_version, fingerprint),
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
                "cache_key": _versioned_key(stage_b_version, fingerprint),
                "value": dump_stage_b_entry(entry_b),
            }
        )
    for group_key, group_cache in caches.materialization.items():
        # A group with no declaration has no version, so nothing it produced can be keyed — and a
        # row nobody can key is a row nobody could ever match. Dropped rather than guessed at.
        version = group_versions.get(group_key)
        if version is None:
            continue
        for fingerprint, entry_m in group_cache.items():
            rows.append(
                {
                    "loan_file_id": loan_file_id,
                    "cache_kind": TagCacheKind.MATERIALIZATION,
                    "cache_key": _materialization_key(group_key, version, fingerprint),
                    "value": dump_ai_group_entry(entry_m),
                }
            )
    return rows


async def save_tag_caches(db: AsyncSession, loan_file_id: UUID, caches: TagCaches) -> int:
    """Persist what this run's caches hold, then evict down to the per-kind cap. Flush-only.

    Returns the number of rows written (0 on any failure). Best-effort throughout: a verification
    that produced correct findings must not be failed by the bookkeeping that makes the NEXT one
    cheaper.
    """
    rows = _rows_from(caches, loan_file_id)
    if not rows:
        return 0
    try:
        # SAVEPOINT — without it "best-effort" is only true for NON-DB errors, and the errors this
        # write can raise are all DB ones. A failed statement ABORTS the transaction, so swallowing
        # it here left the caller to hit `InFailedSQLTransactionError` on its very next statement:
        # `tasks/verification_rules._run` goes on to lock the run row, flush, count findings and
        # COMMIT. The verification would then fail — discarding a complete set of correct findings —
        # in order to record a cache whose entire purpose is to make the NEXT run cheaper. A
        # deleted loan file (the FK is ON DELETE CASCADE) reaches this by an ordinary route.
        async with db.begin_nested():
            # UPSERT rather than delete-then-insert: an entry already stored is the SAME answer (the
            # key is a content fingerprint), so re-writing it would churn `created_at` and make the
            # eviction order meaningless — a file's oldest live entries would look newest after
            # every run.
            #
            # CHUNKED, because one statement cannot carry the whole cache — see
            # `_INSERT_CHUNK_ROWS`. Still one savepoint for all of them: a half-written cache is
            # harmless (every row is independently keyed), but it is not worth reasoning about.
            for start in range(0, len(rows), _INSERT_CHUNK_ROWS):
                statement = pg_insert(TagCacheEntry).values(
                    rows[start : start + _INSERT_CHUNK_ROWS]
                )
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
    except Exception as exc:
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
