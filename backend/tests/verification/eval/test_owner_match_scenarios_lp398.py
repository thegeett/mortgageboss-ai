"""LP-398 — the negative-case fixture for stmt.owner_matches_borrower (the direction AS-6 exists to catch).

Keyless: the live probe (all 8 values + reasoning, the N2 clear-cut miss, and the N1/N5 ambiguous outputs) is
REPORTED in docs/tickets/LP-398.md, not asserted (model non-determinism). These pin the fixture's structure:
it is standalone (own 94-namespace ids, disjoint from LF-6T3N and the income fixture, imported by neither); its
roster is NON-empty (else every case abstains — the LP-379-B trap); the clear-cut expectations live in code, the
two ambiguous cases (N1, N5) carry NO encoded answer (anti-anchoring, LP-337); and all 8 statements materialize
against this fixture's roster only.
"""

from __future__ import annotations

import json

import pytest
from app.verification.eval.income_scenarios import build_income_calibration_snapshot
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.eval.owner_match_scenarios import (
    AMBIGUOUS_CASES,
    CLEARCUT_EXPECTATIONS,
    build_owner_match_scenario_snapshot,
)
from app.verification.snapshot.fields import Field
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.ai import AiGroupResult, AiSubjectJudgment, AiTagJudgment
from app.verification.tag_materialization.producer import materialize_tags
from app.verification.tag_materialization.subjects import loan_borrower_roster

pytestmark = pytest.mark.anyio

_SNAP = build_owner_match_scenario_snapshot()


def _all_ids(snap: Snapshot) -> set[str]:
    ids = {str(snap.loan_file_id)}
    ids |= {e.content_id for e in snap.documents.entries}
    for name, field in snap.mismo.facts.items():
        if name.endswith(".borrower_id") and isinstance(field, Field) and field.is_present:
            ids.add(str(field.value))
    return ids


def test_fixture_is_standalone_and_disjoint_from_the_others() -> None:
    mine = _all_ids(_SNAP)
    assert mine.isdisjoint(_all_ids(build_lf6t3n_snapshot()))  # no LF-6T3N collision
    assert mine.isdisjoint(
        _all_ids(build_income_calibration_snapshot())
    )  # no income-fixture collision
    # own 94-namespace (not LF-6T3N's 1111/2222, not the income fixture's 93)
    assert all(cid.startswith("own-") for e in _SNAP.documents.entries for cid in [e.content_id])
    assert str(_SNAP.loan_file_id).startswith("94")


def test_the_other_fixtures_are_byte_unchanged() -> None:
    # building this fixture must not mutate the shared builders (they are independent functions, but pin it).
    lf = build_lf6t3n_snapshot()
    inc = build_income_calibration_snapshot()
    assert {str(r.borrower_id) for e in lf.documents.entries for r in (e.belongs_to or ())} == {
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    }
    assert len(inc.documents.entries) == 34  # the income fixture's document count, untouched


def test_the_roster_is_non_empty_so_the_group_can_compare() -> None:
    # D2 — the whole probe depends on this: an empty roster would make every case abstain structurally.
    # LP-401 added Sarah Chen (for N7's surname case); the original two are unchanged (D1).
    assert loan_borrower_roster(_SNAP) == ["Jordan A Rivera", "Robert Chen", "Sarah Chen"]


def test_clearcut_and_ambiguous_are_split_and_the_ambiguous_ones_are_unanchored() -> None:
    # clear-cut owner_matches expectations live HERE (asserted); the ambiguous cases carry NO answer anywhere.
    # LP-401: +N9 (both-borrowers control -> yes); N2 RECLASSIFIED to ambiguous (3-run instability); +N7/N8.
    assert CLEARCUT_EXPECTATIONS == {
        "N3": "no",
        "N4": "no",
        "N6": "no",
        "P1": "yes",
        "P2": "yes",
        "N9": "yes",
    }
    assert set(AMBIGUOUS_CASES) == {"N1", "N2", "N5", "N7", "N8"}
    assert not (set(AMBIGUOUS_CASES) & set(CLEARCUT_EXPECTATIONS))  # never both — no leaked answer


class _Echo:
    """A stub that records each statement's context and echoes a fixed judgment (keyless determinism)."""

    def __init__(self) -> None:
        self.rosters: list[object] = []

    async def __call__(self, context_json: str) -> AiGroupResult:
        subjects = json.loads(context_json)["subjects"]
        for s in subjects:
            self.rosters.append(s.get("loan_borrowers"))
        return AiGroupResult(
            [
                AiSubjectJudgment(
                    index=int(s["index"]),
                    tags={
                        "owner_matches_borrower": AiTagJudgment("no", 0.9, "stub"),
                        "is_reserve_eligible": AiTagJudgment("yes", 0.9, "stub"),
                    },
                )
                for s in subjects
            ],
            1,
            1,
            "stub",
            False,
        )


async def test_all_eight_statements_materialize_against_this_fixtures_roster() -> None:
    stub = _Echo()
    out = await materialize_tags(
        _SNAP, ai_reasoners={"stmt_facts": stub}, only_groups=frozenset({"stmt_facts"})
    )
    produced = [
        sid for sid, tags in out.tags.by_subject.items() if "stmt.owner_matches_borrower" in tags
    ]
    assert len(produced) == 11  # LP-401: 8 original + N7/N8/N9 statements all produced a comparison
    # per-scenario isolation: every statement was compared against THIS fixture's roster, nothing else.
    assert stub.rosters and all(
        r == ["Jordan A Rivera", "Robert Chen", "Sarah Chen"] for r in stub.rosters
    )
