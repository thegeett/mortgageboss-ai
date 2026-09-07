"""The vocabulary-driven materialization orchestrator (LP-326) — run every DECLARED production.

Reads the tag declarations (``tag_production.yaml``) and materializes each into the
snapshot's tags layer via the GENERIC producers, dispatched by the tag's declared MODE — never a
per-family branch. Parsed + derived are deterministic; AI groups reuse the LP-313 machinery. Produced
tags are MERGED into the existing tags layer (Stage A/B tags are preserved), keyed under each tag's
declared SUBJECT (the LP-325 gather contract keys id.* facts under the document subject).

``only_subjects`` scopes a run to a subject set — the live orchestrator runs the id.* families
(document / loan) and leaves the transaction Stage-A tags to their existing producer (equivalence is
proven separately). Returns a NEW frozen snapshot; the raw layer is never touched.
"""

from __future__ import annotations

from functools import partial
from time import perf_counter

from app.ai.concurrency import dispatch_bounded
from app.ai.stage_metrics import StageMetrics
from app.core.logging import get_logger
from app.verification.snapshot.model import DocumentEntry, Snapshot, TagsSection
from app.verification.snapshot.tag import Tag
from app.verification.tag_materialization.ai import AiTagCache, Reasoner, produce_ai_group_tags
from app.verification.tag_materialization.breaker import AiInfraBreaker
from app.verification.tag_materialization.declarations import (
    ProductionMode,
    load_ai_groups,
    load_declarations,
)
from app.verification.tag_materialization.derived import produce_derived_tags
from app.verification.tag_materialization.parsed import produce_parsed_tag
from app.verification.tag_materialization.subjects import subject_type

logger = get_logger(__name__)

#: LP-644 §2 — AI GROUPS in flight at once (the outer level). FOUR, not eight: this multiplies with
#: `ai._MAX_CONCURRENT_BATCHES`, so four groups of eight batches is already 32 concurrent calls —
#: four times Stage B's bound. §4 is where any of these get raised, together and on measured TPM.
_MAX_CONCURRENT_GROUPS = 4


def _merge(into: dict[str, dict[str, Tag]], produced: dict[str, dict[str, Tag]]) -> None:
    for subject_id, tags in produced.items():
        into.setdefault(subject_id, {}).update(tags)


async def materialize_tags(
    snapshot: Snapshot,
    *,
    ai_reasoners: dict[str, Reasoner] | None = None,
    ai_cache: AiTagCache | None = None,
    only_subjects: frozenset[str] | None = None,
    only_groups: frozenset[str] | None = None,
    breaker: AiInfraBreaker | None = None,
    metrics: StageMetrics | None = None,
    pass_name: str = "materialization",
) -> Snapshot:
    """Materialize every declared tag into the tags layer.

    ``only_subjects`` scopes parsed/derived/ai to a subject set; ``only_groups`` further scopes the AI
    pass to specific groups (a caller that needs only some AI families avoids running — and, without a
    stub, calling the real model for — the rest).

    ``metrics`` (LP-644 §1, optional, mutated in place) accumulates the AI pass's calls, tokens and
    latency across every group, and the wall time of the WHOLE materialization — parsed and derived
    included. Those two phases make no AI calls, so counting them here is what stops §2's projected
    saving from being read as larger than the stage can actually give back. ``pass_name`` names the
    caller in that log line: LP-391's pending-check pass materializes a DIFFERENT group set on a
    throwaway snapshot, and two identically-named lines per run would be unreadable.
    """
    stage_started = perf_counter()
    reasoners = ai_reasoners or {}
    declarations = load_declarations()
    ai_groups = load_ai_groups()

    def in_scope(subject: str) -> bool:
        return only_subjects is None or subject in only_subjects

    # Start from the existing tags layer (Stage A/B), never clobbering it.
    by_subject: dict[str, dict[str, Tag]] = {
        sid: dict(tags)
        for sid, tags in ({} if snapshot.tags.absent else snapshot.tags.by_subject).items()
    }

    # Order is parsed → ai → DERIVED-LAST (LP-333). A derived recipe may AGGREGATE other materialized
    # tags (the income recipes read a borrower's documented income across its documents), so it must see
    # the parsed + AI tags produced THIS run — not the original (pre-materialization) tags layer. Derived
    # therefore runs last, against a snapshot carrying the freshly-built tags. A loan-level recipe that
    # reads only raw MISMO (id.app_required_fields_present) is unaffected (identical output either order).

    # 1. parsed — map the declared extraction field for each subject (absent field → absent tag).
    for decl in declarations.values():
        if decl.mode is not ProductionMode.PARSED or not in_scope(decl.subject):
            continue
        st = subject_type(decl.subject)
        field_name = decl.data.split(":", 1)[0]
        for subject_id, raw in st.enumerate(snapshot):
            # LP-454 review — a document_type filter scopes a parsed:document tag to its intended document
            # type, so a field-name shared by several extractors (report_date, earnest_money_amount) does not
            # mis-materialise the tag on the wrong document. Only document subjects carry a document_type.
            if decl.document_type is not None and (
                not isinstance(raw, DocumentEntry) or raw.document_type != decl.document_type
            ):
                continue
            tag = produce_parsed_tag(decl, subject_id, st.read_field(raw, field_name))
            if tag is not None:
                by_subject.setdefault(subject_id, {})[decl.tag_id] = tag

    # 2. ai — one bounded structuring pass per AI group (co-locating its tags on one subject).
    # LP-644 §1 review — counted HERE, by the loop that actually runs them, rather than recomputed
    # from the same predicate at the log line. The two copies were equivalent by De Morgan today, so
    # nothing was wrong; but `groups` is the number sizing §2's outer parallelisation, and a second
    # copy of a scoping rule is the kind that drifts silently the next time the scoping changes.
    scoped = [
        group
        for group in ai_groups.values()
        if in_scope(group.subject) and (only_groups is None or group.key in only_groups)
    ]
    groups_run = len(scoped)

    # LP-644 §2, the OUTER of the two levels and the bigger win. The ticket calls this stage "doubly
    # sequential" and names it the least-known fact in it: 23 groups awaited in turn, each awaiting
    # its own batches in turn, nothing overlapping anything.
    #
    # ⚠️ THE BOUNDS MULTIPLY. Each group may itself have `ai._MAX_CONCURRENT_BATCHES` (8) in flight,
    # so N groups here means up to N x 8 concurrent calls. That is why this bound is 4 and not 8: a
    # worst case of 32 already exceeds Stage B's 8, and §4 — not this ticket — is where a bound gets
    # raised, on measured TPM rather than on arithmetic.
    #
    # AND THE WORST CASE IS NOT RARE, so do not read 4 as the working figure. The live pass runs 20
    # groups (`_required_ai_groups`), and the batch counts are not all 1: `txn_stage_a` enumerates
    # EVERY transaction, which on the document-heavy file this ticket is sized against is hundreds —
    # far past the 8-batch bound on its own; `id_address`, `id_name` and `income_docs` declare
    # `applies_to: all`, so they enumerate every document (44 on that file = 3 batches each); and the
    # four liability groups run 1-2. A realistic peak is a dozen concurrent calls and the 32 cap is
    # reachable, so this stage — not Stage B — is what sets the run's ceiling on requests in flight.
    #
    # ⚠️ THE SHARED BREAKER NO LONGER SEES A SERIAL SEQUENCE. Each group's apply loop is atomic (it
    # contains no await), so a group's own batches still reach `AiInfraBreaker` in input order — but
    # the GROUPS reach it in completion order, so "5 consecutive failures" is now counted over an
    # interleaving that depends on which group finished first. A mix of failing and succeeding groups
    # can therefore trip the breaker on a file where the serial order would not have, and vice versa.
    # The breaker's own docstring still claims "a pass materializes its groups sequentially in one
    # event-loop task" as the reason it needs no synchronisation; that sentence is now stale.
    #
    # No dispatch gate is passed here: `produce_ai_group_tags` never raises `AIClientError` (it
    # resolves per batch, fail-closed) and its own inner dispatch already carries the gate. What it
    # CAN raise is `AiBackendUnavailable` from the breaker, which is not an `AIClientError` — so
    # `dispatch_bounded` closes its gate and re-raises it after collecting siblings, which is exactly
    # the abort the breaker exists to cause.
    outcomes = await dispatch_bounded(
        [
            partial(
                produce_ai_group_tags,
                snapshot,
                group,
                {
                    tag_id: declarations[tag_id].allowed_values
                    for tag_id in group.tag_ids
                    if tag_id in declarations
                },
                reasoner=reasoners.get(group.key),
                cache=ai_cache,
                breaker=breaker,
                metrics=metrics,
            )
            for group in scoped
        ],
        concurrency=_MAX_CONCURRENT_GROUPS,
    )

    # MERGE IN DECLARATION ORDER. Groups co-locate tags on subjects and two groups can write the same
    # subject, so a later group's tags overwrite an earlier one's on collision — `_merge` is
    # last-writer-wins per tag id. Merging in completion order would make that outcome depend on
    # which coroutine finished first; merging in the original order keeps it exactly as it was.
    for outcome in outcomes:
        if outcome.result is not None:
            _merge(by_subject, outcome.result)

    # 3. derived — deterministic recipes, run LAST against the snapshot carrying the parsed + AI tags so
    #    a recipe that aggregates them sees them (the LP-333 data-flow fix). ``working`` is a transient
    #    READ view over the live ``by_subject`` map: model_construct skips re-validating the (already
    #    validated) Tag objects — the one authoritative validated build is the return below, not this
    #    hot-path view. Because it references ``by_subject``, a derived recipe also sees any derived tag
    #    merged EARLIER in this loop, so a recipe may depend only on a tag produced before it (parsed, AI,
    #    or an earlier-declared derived tag in tag_production.yaml) — never a later-declared derived tag.
    working = snapshot.model_copy(
        update={"tags": TagsSection.model_construct(by_subject=by_subject, absent=False)}
    )
    for decl in declarations.values():
        if decl.mode is ProductionMode.DERIVED and in_scope(decl.subject):
            _merge(by_subject, produce_derived_tags(decl, working))

    # LP-644 §1 — the stage has no `*_production_done` line of its own (Stage A and B do), so this
    # is where materialization becomes visible at all. `groups` is the outer sequential loop §2
    # would parallelise; `ai_calls` is the inner one. Both counts are needed to size that change:
    # 23 groups making 26 calls and 23 groups making 200 are the same table row and very different
    # work.
    if metrics is not None:
        metrics.wall_seconds = perf_counter() - stage_started
        logger.info(
            "materialization_production_done",
            pass_name=pass_name,
            groups=groups_run,
            input_tokens=metrics.input_tokens,
            output_tokens=metrics.output_tokens,
            **metrics.as_log_fields(),
        )

    return snapshot.model_copy(update={"tags": TagsSection.present(by_subject)})


__all__ = ["materialize_tags"]
