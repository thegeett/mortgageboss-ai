"""LP-644 §1 review — a cached group must not be counted as a model call.

THE DEFECT THIS PINS. The first version counted one call per AI GROUP, recorded in the producer
after `produce_ai_group_tags` returned. A group every one of whose subjects is already cached
dispatches nothing at all — its `representatives` list is empty and the batch loop never runs — so a
re-run of an unchanged file reported a full call count having made almost none.

WHY THAT IS WORSE THAN AN AMBIGUOUS FIELD NAME. Every projection in LP-644 is a call count times a
mean latency, so an inflated count inflates the estimated AI time, which is the number deciding
whether the rest of that ticket is worth doing. Measurement built to replace a stale estimate,
reading high in exactly the case — a warm cache — where the truth is lowest.
"""

from __future__ import annotations

import json

from app.core.stage_timing import StageTiming
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
    produce_ai_group_tags,
)
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations


async def test_a_group_the_cache_answers_counts_no_calls() -> None:
    from tests.verification.tag_materialization.test_producers import _doc, _snapshot

    calls_made = 0

    async def counting_reasoner(context_json: str) -> AiGroupResult:
        nonlocal calls_made
        calls_made += 1
        subjects = json.loads(context_json)["subjects"]
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    # BOTH of the group's tags: only a COMPLETE judgment is cached, and a
                    # partial one would leave the second pass dispatching again — the test would
                    # then pass for the wrong reason on a fixture that never exercised the cache.
                    tags={
                        "address_normalized": AiTagJudgment("1 MAIN ST", 0.9, "stub"),
                        "current_address_type": AiTagJudgment("residence", 0.9, "stub"),
                    },
                )
                for s in subjects
            ],
            0,
            0,
            "stub-model",
            False,
        )

    group = load_ai_groups()["id_address"]
    allowed = {t: load_declarations()[t].allowed_values for t in group.tag_ids}
    snap = _snapshot(docs=[_doc("d1", fields={"address": "1 Main St"})])
    cache: dict[str, dict[str, object]] = {}

    first = StageTiming()
    await produce_ai_group_tags(
        snap, group, allowed, reasoner=counting_reasoner, cache=cache, timing=first
    )
    dispatched_first = calls_made

    # THE SAME SNAPSHOT AGAIN, sharing the cache — the re-run this measurement misreported.
    second = StageTiming()
    await produce_ai_group_tags(
        snap, group, allowed, reasoner=counting_reasoner, cache=cache, timing=second
    )

    assert dispatched_first >= 1, (
        "the fixture must dispatch on the first pass or this asserts nothing"
    )
    assert first.calls == dispatched_first, "the first pass miscounted its own dispatches"
    assert calls_made == dispatched_first, (
        "the cache did not answer the second pass — wrong fixture"
    )
    assert second.calls == 0, (
        "a group answered entirely from cache was counted as a model call, which inflates the AI-time "
        f"estimate on exactly the warm-cache re-run where it is lowest — reported {second.calls}"
    )
