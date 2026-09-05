"""LP-644 §3 — the persisted cache, against a real database.

The codecs are pinned separately; this pins the STORE, and the property that makes §3 worth building
at all: **a second run over the same content asks the model nothing.** LP-644 sizes §3 at ~44% of a
946s run on a re-run, and the case it covers is the common one the API's byte-identical
short-circuit does NOT — a processor corrects one document's type or adds one more, and the file
re-pays for 44 documents' worth of AI work to answer 43 questions already answered.

The `save -> load -> reuse` cycle is what has to hold. Everything else here is a guard on the two
ways a cache can be worse than no cache: serving an answer that should not have been stored, or
failing a run it was only ever meant to speed up.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from app.ai.tag_production import TagJudgment
from app.models.company import Company
from app.models.loan_file import LoanFile
from app.models.tag_cache import TagCacheEntry, TagCacheKind
from app.services import tag_cache_store
from app.services.tag_cache_store import (
    _INSERT_CHUNK_ROWS,
    load_tag_caches,
    save_tag_caches,
)
from app.services.tag_correlation import SourceStrength, _Sourced
from app.services.tag_production import _Judged
from app.services.verification_run import TagCaches
from app.verification.tag_materialization.ai import AiTagJudgment, _Resolved
from app.verification.tag_materialization.declarations import load_ai_groups
from sqlalchemy import func, select

pytestmark = pytest.mark.anyio


def _judged(value: str = "in") -> _Judged:
    return _Judged(
        is_money_in=TagJudgment(value, 0.9, "stub"),
        apparent_category=TagJudgment("payroll", 0.9, "stub"),
        reason="r",
    )


def _sourced(*, cacheable: bool = True) -> _Sourced:
    return _Sourced(
        value="yes",
        source_content_id="txn1",
        confidence=0.9,
        reasoning="matching debit",
        cacheable=cacheable,
        strength=SourceStrength.VERIFIED,
    )


def _resolved() -> _Resolved:
    return _Resolved(tags={"address_normalized": AiTagJudgment("12 High St", 0.9, "s")}, reason="r")


async def _loan_file(db_session) -> LoanFile:
    """A real, persisted loan file — the cache rows carry a CASCADE foreign key to it."""
    company = Company(name="LP-644", slug=f"lp644-{uuid4().hex[:8]}")
    db_session.add(company)
    await db_session.flush()
    lf = LoanFile(
        company_id=company.id,
        display_id=f"LF-{uuid4().hex[:4].upper()}",
        inbox_token=uuid4().hex,  # NOT NULL — the per-file upload capability
    )
    db_session.add(lf)
    await db_session.flush()
    return lf


async def test_a_saved_cache_comes_back_on_the_next_run(db_session) -> None:
    # THE POINT OF §3. What one run learned, the next one starts with.
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.stage_a["fp-a"] = _judged()
    caches.stage_b["fp-b"] = _sourced()
    caches.materialization.setdefault("id_address", {})["fp-m"] = _resolved()

    written = await save_tag_caches(db_session, lf.id, caches)
    assert written == 3

    restored = await load_tag_caches(db_session, lf.id)

    assert restored.stage_a["fp-a"] == caches.stage_a["fp-a"]
    assert restored.stage_b["fp-b"] == caches.stage_b["fp-b"]
    assert restored.materialization["id_address"]["fp-m"] == _resolved()


async def test_an_uncacheable_stage_b_verdict_is_never_persisted(db_session) -> None:
    # It is still reused WITHIN the run (the in-memory dict holds it), but persisting it would freeze
    # a failed/truncated/malformed judgment into the file forever instead of retrying next run.
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.stage_b["fp-bad"] = _sourced(cacheable=False)

    assert await save_tag_caches(db_session, lf.id, caches) == 0

    restored = await load_tag_caches(db_session, lf.id)
    assert restored.stage_b == {}


async def test_two_groups_sharing_a_fingerprint_do_not_share_an_answer(db_session) -> None:
    # THE BUG THE KEY PREFIX EXISTS TO PREVENT. Two AI groups asking DIFFERENT questions about the
    # same subject fingerprint that subject identically. Without namespacing by group, one group's
    # answer is served to another — silently, from a cache that looks like it is working.
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.materialization.setdefault("id_address", {})["same-fp"] = _Resolved(
        tags={"address_normalized": AiTagJudgment("12 High St", 0.9, "s")}, reason="r"
    )
    caches.materialization.setdefault("id_name", {})["same-fp"] = _Resolved(
        tags={"name_normalized": AiTagJudgment("Jane Roe", 0.9, "s")}, reason="r"
    )

    assert await save_tag_caches(db_session, lf.id, caches) == 2

    restored = await load_tag_caches(db_session, lf.id)
    assert restored.materialization["id_address"]["same-fp"].tags["address_normalized"].value == (
        "12 High St"
    )
    assert (
        restored.materialization["id_name"]["same-fp"].tags["name_normalized"].value == "Jane Roe"
    )


async def test_saving_the_same_entry_twice_updates_rather_than_duplicates(db_session) -> None:
    # The key is a content fingerprint, so the same question asked on two runs is ONE row. Inserting
    # again would breach the unique index; the upsert is what makes a re-run idempotent.
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.stage_a["fp-a"] = _judged()

    await save_tag_caches(db_session, lf.id, caches)
    await save_tag_caches(db_session, lf.id, caches)

    count = await db_session.scalar(
        select(func.count()).select_from(TagCacheEntry).where(TagCacheEntry.loan_file_id == lf.id)
    )
    assert count == 1
    hits = await db_session.scalar(
        select(TagCacheEntry.hit_count).where(TagCacheEntry.loan_file_id == lf.id)
    )
    assert hits == 1  # bumped on the second save, so a future exact-eviction policy has the signal


async def test_one_file_never_sees_another_files_cache(db_session) -> None:
    # Multi-tenancy is scoped by loan file here rather than company, because that is the unit a
    # fingerprint means anything within. A leak would serve one borrower's judgment on another's file.
    first = await _loan_file(db_session)
    second = await _loan_file(db_session)
    caches = TagCaches()
    caches.stage_a["fp-a"] = _judged()
    await save_tag_caches(db_session, first.id, caches)

    restored = await load_tag_caches(db_session, second.id)
    assert restored.stage_a == {}


async def test_a_corrupt_row_is_skipped_and_the_rest_still_load(db_session) -> None:
    # A cache must never fail a run. A row written by an older shape costs a re-ask for THAT subject
    # and nothing more — the others still come back.
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.stage_a["good"] = _judged()
    await save_tag_caches(db_session, lf.id, caches)
    db_session.add(
        TagCacheEntry(
            loan_file_id=lf.id,
            cache_kind=TagCacheKind.STAGE_A,
            cache_key="corrupt",
            value={"is_money_in": "not-a-judgment"},
        )
    )
    await db_session.flush()

    restored = await load_tag_caches(db_session, lf.id)

    assert "good" in restored.stage_a
    assert "corrupt" not in restored.stage_a


async def test_an_unknown_cache_kind_is_ignored_not_fatal(db_session) -> None:
    # Forward compatibility: a row written by a NEWER deploy that added a stage must not crash an
    # older one still running during a rollout.
    lf = await _loan_file(db_session)
    db_session.add(
        TagCacheEntry(
            loan_file_id=lf.id, cache_kind="stage_z", cache_key="k", value={"anything": 1}
        )
    )
    await db_session.flush()

    restored = await load_tag_caches(db_session, lf.id)

    assert restored.stage_a == {} and restored.stage_b == {} and restored.materialization == {}


async def test_an_empty_cache_writes_nothing(db_session) -> None:
    lf = await _loan_file(db_session)
    assert await save_tag_caches(db_session, lf.id, TagCaches()) == 0


async def test_a_failed_save_leaves_the_session_usable(db_session) -> None:
    """LP-644 §3 review — the module's central promise, made true rather than stated.

    "A cache must never fail a run" was only true for NON-DB errors, and every error this write can
    raise is a DB one. A failed statement ABORTS the transaction, so swallowing it left the caller
    to hit `InFailedSQLTransactionError` on its very next statement — and
    `tasks/verification_rules._run` goes on to lock the run row, flush, count findings and COMMIT.
    The verification would fail, discarding a complete set of correct findings, to record a cache
    whose only purpose is to make the NEXT run cheaper.

    The trigger here is an ordinary one: the loan file is gone (the FK is ON DELETE CASCADE), which
    is reachable whenever a file is deleted while its run is in flight.
    """
    caches = TagCaches()
    caches.stage_a["fp1"] = _judged()

    assert await save_tag_caches(db_session, uuid4(), caches) == 0, (
        "a save that cannot land must report failure rather than raise"
    )

    # THE POINT: the caller's session is still usable, so the verification still commits.
    await db_session.execute(select(func.count()).select_from(TagCacheEntry))
    await db_session.flush()


async def test_a_failed_load_leaves_the_session_usable(db_session, monkeypatch) -> None:
    """The same guarantee on the read side, where the blast radius is larger.

    The load runs BEFORE `run_verification`, so a poisoned session here fails the whole pass rather
    than its tail. The realistic trigger is deploying this code ahead of its migration: the table is
    absent, the load degrades to an empty cache exactly as designed, and then every verification on
    the box fails for a reason that has nothing to do with verification.

    Pointing the mapped table at a name that does not exist reproduces that without DDL — real
    schema changes take an AccessExclusiveLock that deadlocks against the suite's own teardown.
    """
    monkeypatch.setattr(TagCacheEntry.__table__, "name", "tag_cache_entries_absent")

    caches = await load_tag_caches(db_session, uuid4())
    assert not caches.stage_a and not caches.stage_b, "a missing table degrades to an empty cache"

    monkeypatch.undo()
    # THE POINT: the caller runs the ENTIRE verification on this session afterwards.
    await db_session.execute(select(func.count()).select_from(TagCacheEntry))
    await db_session.flush()


# --------------------------------------------------------------------------- #
# LP-644 §3 review — the key has to carry the QUESTION, not just the subject
# --------------------------------------------------------------------------- #


async def test_an_edited_prompt_invalidates_what_it_was_asked_with(db_session, monkeypatch) -> None:
    """A fingerprint hashes the SUBJECT and knows nothing about the prompt asked about it.

    In memory that was unobservable — the cache died with the run, so an edited prompt took effect
    on the next one. Persisted, it would be permanent: every already-cached subject served the old
    model's answer for as long as its content is unchanged. The producer version in the key is what
    makes an edit cost one run at full price instead of forever.
    """
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.stage_a["fp-a"] = _judged()
    await save_tag_caches(db_session, lf.id, caches)
    assert (await load_tag_caches(db_session, lf.id)).stage_a["fp-a"].is_money_in is not None

    monkeypatch.setattr(
        tag_cache_store, "STAGE_A_TRANSACTION_SYSTEM_PROMPT", "a materially different prompt"
    )

    restored = await load_tag_caches(db_session, lf.id)

    assert restored.stage_a == {}, "the old answer is not served to the new question"


async def test_a_group_that_gains_a_tag_is_re_asked_not_frozen(db_session, monkeypatch) -> None:
    """The worst version of the same defect, and the reason `tag_ids` is in the group's digest.

    `produce_ai_group_tags` skips a subject whose fingerprint is cached, so a tag ADDED to a group
    would never be asked for — and `_build_tag` renders the missing short as `unknown` with "tag
    value missing or malformed", an honest-looking abstention that no re-run could ever clear.
    """
    lf = await _loan_file(db_session)
    caches = TagCaches()
    caches.materialization.setdefault("id_address", {})["fp-m"] = _resolved()
    await save_tag_caches(db_session, lf.id, caches)
    assert "fp-m" in (await load_tag_caches(db_session, lf.id)).materialization["id_address"]

    group = load_ai_groups()["id_address"]
    widened = dict(load_ai_groups())
    widened["id_address"] = replace(group, tag_ids=(*group.tag_ids, "address.newly_declared"))
    monkeypatch.setattr(tag_cache_store, "load_ai_groups", lambda: widened)

    restored = await load_tag_caches(db_session, lf.id)

    assert restored.materialization == {}, "a widened group asks again rather than serving a hole"


async def test_a_cache_larger_than_one_statement_still_saves(db_session) -> None:
    """The insert is chunked because a statement's parameter count is a 16-bit protocol field.

    Each row binds eight parameters, so one statement tops out at 4,095 rows while the per-kind cap
    allows 6,000 — reachable on exactly the document-heavy files this cache exists for. Unchunked,
    the save raised, was swallowed, and the biggest files in the system silently never cached.
    """
    lf = await _loan_file(db_session)
    caches = TagCaches()
    for i in range(_INSERT_CHUNK_ROWS + 250):
        caches.stage_a[f"fp-{i}"] = _judged()

    assert await save_tag_caches(db_session, lf.id, caches) == _INSERT_CHUNK_ROWS + 250

    restored = await load_tag_caches(db_session, lf.id)
    assert len(restored.stage_a) == _INSERT_CHUNK_ROWS + 250
