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

from time import perf_counter

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
    groups_run = 0
    for group in ai_groups.values():
        if not in_scope(group.subject) or (
            only_groups is not None and group.key not in only_groups
        ):
            continue
        groups_run += 1
        allowed_by_tag = {
            tag_id: declarations[tag_id].allowed_values
            for tag_id in group.tag_ids
            if tag_id in declarations
        }
        produced = await produce_ai_group_tags(
            snapshot,
            group,
            allowed_by_tag,
            reasoner=reasoners.get(group.key),
            cache=ai_cache,
            breaker=breaker,
            metrics=metrics,
        )
        _merge(by_subject, produced)

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
