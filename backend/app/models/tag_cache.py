"""Persisted AI tag caches (LP-644 §3) — the answers a re-run should not pay for twice.

`TagCaches` is built fresh on every invocation (`verification_run.py`'s ``caches = caches or
TagCaches()``), and the only caller — the Celery task — passes none. So a re-run re-pays for every AI
call the previous run already made. `tag_production._fingerprint`'s docstring has claimed otherwise
since it was written:

    Keyed on the four raw Fields (not the content_id), so identical-content transactions share one AI
    judgment and **an unchanged transaction is a cache hit across re-runs.**

The keying is right; the storage never existed. This table is it.

**SAFE BY CONSTRUCTION, which is why this is a §0-clean change.** The keys are content fingerprints:
the same input hashes to the same key and therefore returns the same answer a fresh call would have
produced. Nothing here decides anything — it only avoids re-asking a question already answered.

WHAT IS NOT STORED. Only outcomes the producers already mark cacheable in memory: a failed,
truncated or malformed judgment is excluded at the source (`_Sourced.cacheable`, and the
complete-judgment checks in Stage A and the AI producer), so a degraded answer is retried next run
rather than frozen into the file forever. Persisting is strictly narrower than caching in memory,
never wider.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TagCacheKind:
    """The producing stage a cached entry belongs to.

    A plain string constant set rather than a DB enum: adding a stage must not need a migration, and
    an unknown kind read back from an older row is ignored by the loader rather than crashing it —
    a cache is an optimisation and must never be able to fail a run.
    """

    STAGE_A = "stage_a"
    STAGE_B = "stage_b"
    MATERIALIZATION = "materialization"

    ALL = frozenset({STAGE_A, STAGE_B, MATERIALIZATION})


class TagCacheEntry(Base, UUIDMixin, TimestampMixin):
    """One cached AI answer for one loan file, keyed by the content it was computed from."""

    __tablename__ = "tag_cache_entries"
    __table_args__ = (
        # The lookup AND the identity. A repeated (file, kind, key) is the same question asked twice,
        # so it must collapse to one row rather than accumulate — the upsert on save depends on this.
        Index(
            "uq_tag_cache_file_kind_key",
            "loan_file_id",
            "cache_kind",
            "cache_key",
            unique=True,
        ),
        # Eviction reads this: oldest-first within a (file, kind). See `tag_cache_store`.
        Index("ix_tag_cache_file_kind_created", "loan_file_id", "cache_kind", "created_at"),
    )

    loan_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("loan_files.id", ondelete="CASCADE"), index=True, nullable=False
    )
    cache_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The content fingerprint the producer computed. For materialization it is prefixed with the AI
    #: group key, because two groups asking DIFFERENT questions about the same subject hash that
    #: subject identically — without the prefix one group's answer would be served to another.
    cache_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: The producer's own serialisation of its cache value. JSONB rather than a typed column set:
    #: three stages store three different shapes, each owned by the module that produces it, and a
    #: shape change must not need a migration for what is only ever a cache.
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Bumped every time a run STORES this entry — which is every run, for every entry, because the
    #: loader pulls the whole file's rows into the cache and the saver writes the whole cache back.
    #:
    #: ⚠️ SO IT IS NOT A LIVENESS SIGNAL, and the first version of this comment claimed it was ("a
    #: busy file's live entries stay young while its dead ones age"). Measured: a fingerprint whose
    #: content has changed — never looked up by any producer again — still reaches `hit_count=3`
    #: after three runs, exactly like an entry hit every time. What this counts is runs SURVIVED.
    #:
    #: A future exact-eviction policy therefore cannot be built on this column as it stands; it needs
    #: the producers to report the keys they actually READ, and those reads happen in the await-free
    #: hot loops `tag_cache_store` must not reach into. Left in place because the column is harmless
    #: and dropping it would cost a migration, but it buys nothing until that plumbing exists.
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


__all__ = ["TagCacheEntry", "TagCacheKind"]
