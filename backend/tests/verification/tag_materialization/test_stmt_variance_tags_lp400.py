"""LP-400 — stmt.holder_name_variance + stmt.non_borrower_co_holder: SURFACE name discrepancies + non-borrower
co-holders instead of swallowing them (Priya's ruling: a name variance flags for attention but the document
still COUNTS; a joint account flags a non-borrower co-holder — neither is a rejection).

Keyless: the live probe (N1 -> middle_differs, N5 -> co_holder yes, the 5 LF-6T3N goldens unchanged) is reported
in docs/tickets/LP-400.md. These pin: both new tags are declared + produced by stmt_facts on the document
subject; owner_matches_borrower + is_reserve_eligible are semantically UNCHANGED (same enums — their goldens
stay valid); the variance values are DESCRIPTIVE observables (middle_differs SPLIT from middle_absent, not a
verdict); unknown is reachable; and AS-6 is untouched (consuming these is a later ticket).
"""

from __future__ import annotations

import json

import pytest
from app.verification.eval.owner_match_scenarios import build_owner_match_scenario_snapshot
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.declarations import (
    _allowed_values_by_tag,
    load_ai_groups,
    load_declarations,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_NEW = ("stmt.holder_name_variance", "stmt.non_borrower_co_holder")


def test_both_new_tags_are_declared_on_the_document_subject_via_stmt_facts() -> None:
    decls = load_declarations()
    for tag in _NEW:
        assert tag in decls and decls[tag].subject == "document"
        assert (
            str(decls[tag].data) == "stmt_facts"
        )  # co-located in the existing group (one call, D5)
    group = load_ai_groups()["stmt_facts"]
    assert set(_NEW) <= set(group.tag_ids)  # produced by stmt_facts
    assert group.include_borrower_roster is True  # both new tags need the roster to compare


def test_owner_matches_and_reserve_are_semantically_unchanged() -> None:
    # THE equivalence that matters: the existing tags' enums are untouched, so their goldens stay valid.
    av = _allowed_values_by_tag()
    assert av["stmt.owner_matches_borrower"] == ("yes", "no", "unknown")
    assert av["stmt.is_reserve_eligible"] == ("yes", "no", "partial")
    # both still in the group, unmoved
    assert "stmt.owner_matches_borrower" in load_ai_groups()["stmt_facts"].tag_ids
    assert "stmt.is_reserve_eligible" in load_ai_groups()["stmt_facts"].tag_ids


def test_the_variance_values_are_descriptive_observables_not_verdicts() -> None:
    av = _allowed_values_by_tag()
    variance = av["stmt.holder_name_variance"]
    assert variance is not None
    # a DIFFERENT middle is SPLIT from a DROPPED middle — else the tag re-collapses N1 (risky) and P1 (benign)
    assert "middle_differs" in variance and "middle_absent" in variance
    assert "none" in variance and "unknown" in variance  # a baseline + honest abstention
    # they describe the KIND of difference — NOT a judgment of whether it matters (that is the rule's)
    assert not any(v in variance for v in ("acceptable", "flag", "needs_attention", "reject"))
    assert av["stmt.non_borrower_co_holder"] == ("yes", "no", "unknown")


def test_as6_is_not_activated_by_this_ticket() -> None:
    # LP-400 declared the variance/co_holder tags but AS-6 did not yet consume them. (LP-404 later made
    # AS-6 read all three statement-holder tags — but still did not activate it.)
    spec = load_rule_spec("AS-6")
    assert spec.deterministic is not None
    assert set(spec.deterministic.load_bearing_tags) == {
        "stmt.owner_matches_borrower",
        "stmt.holder_name_variance",
        "stmt.non_borrower_co_holder",
    }
    assert "AS-6" not in ACTIVE_RULE_IDS  # AS-6 not activated by this ticket (still held)


# --------------------------------------------------------------------------- #
# a stub-driven materialization: all four tags produce, each with a reason
# --------------------------------------------------------------------------- #
class _Stub:
    def __init__(self) -> None:
        self.saw_roster = False

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        self.saw_roster = all("loan_borrowers" in s for s in subjects)
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "owner_matches_borrower": AiTagJudgment("yes", 0.9, "r"),
                        "is_reserve_eligible": AiTagJudgment("yes", 0.9, "r"),
                        "holder_name_variance": AiTagJudgment("middle_differs", 0.9, "M vs A"),
                        "non_borrower_co_holder": AiTagJudgment("no", 0.9, "single holder"),
                    },
                )
                for s in subjects
            ],
            1,
            1,
            "stub",
            False,
        )


async def test_all_four_tags_produce_on_a_statement() -> None:
    stub = _Stub()
    out = await materialize_tags(
        build_owner_match_scenario_snapshot(),
        ai_reasoners={"stmt_facts": stub},
        only_groups=frozenset({"stmt_facts"}),
    )
    assert stub.saw_roster  # the roster reached the group (both new tags depend on it)
    tags = out.tags.by_subject["own-n1"]
    for tag in ("stmt.owner_matches_borrower", "stmt.is_reserve_eligible", *_NEW):
        assert tag in tags and tags[tag].reasoning  # produced, with a reason


async def test_unknown_is_reachable_on_both_new_tags() -> None:
    # honest abstention stays first-class — a coerced/absent judgment becomes unknown-with-reason, never a guess.
    class _Abstain:
        async def __call__(self, context_json: str) -> AiGroupResult:
            subjects = json.loads(context_json)["subjects"]
            return AiGroupResult(
                [
                    AiSubjectJudgment(
                        index=int(s["index"]),
                        tags={
                            "holder_name_variance": AiTagJudgment("unknown", 0.4, "cannot tell"),
                            "non_borrower_co_holder": AiTagJudgment("unknown", 0.4, "cannot tell"),
                        },
                    )
                    for s in subjects
                ],
                1,
                1,
                "stub",
                False,
            )

    out = await materialize_tags(
        build_owner_match_scenario_snapshot(),
        ai_reasoners={"stmt_facts": _Abstain()},
        only_groups=frozenset({"stmt_facts"}),
    )
    tags = out.tags.by_subject["own-n3"]
    assert tags["stmt.holder_name_variance"].value == "unknown"
    assert tags["stmt.non_borrower_co_holder"].value == "unknown"
