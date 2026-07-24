"""LP-399 — the BLIND labeling worksheet for stmt.owner_matches_borrower.

Anti-anchoring is the ticket: LP-398 PUBLISHED all 8 AI answers (N1 yes, N2 unknown, N3/N4/N6 no, N5 yes, P1/P2
yes) and the clear-cut expectations live in code. NONE of that may reach the sheet — else Priya's labels measure
agreement with the AI, not judgment. These pin (deterministic, keyless): no golden/prediction/AI-reasoning in
the CSV; the context shows BOTH the holder AND the roster (judgeability — an absent roster is the LP-390-3
missing-field trap); the neutral prompt does NOT restate the AI's tolerance rules (that would hand her the
answer key); the row order does not group negatives-then-positives; and the committed file matches a fresh
generation.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.eval.owner_match_scenarios import (
    AMBIGUOUS_CASES,
    CLEARCUT_EXPECTATIONS,
    OWNER_MATCH_WORKSHEET_FILE,
    write_owner_match_worksheet,
)

_COMMITTED = Path(__file__).resolve().parents[4] / "docs/calibration" / OWNER_MATCH_WORKSHEET_FILE

# distinctive phrases from LP-398's AND LP-400's PUBLISHED probe reasoning — none may appear in the blind sheet.
_AI_REASONING = (
    "matches borrower",  # LP-398/400 owner_matches reasoning
    "trust entity",  # LP-398 N3
    "limited liability",  # LP-398 N6
    "could potentially",  # LP-398 N2 hedge
    "does not match either",  # LP-398 N4
    "a common feminine",  # LP-401 N2 (Roberta reasoning)
    "co-holder, who is not among",  # LP-400/401 co_holder reasoning
    "the middles conflict",  # variance reasoning
)
# the AI's SELECTION RULES — the prompt must not restate HOW to choose a value (it would teach her the answer
# key). NOTE: the VALUE names (middle_absent / nickname / surname_differs) legitimately appear — she picks from
# them (D3). These are the model's RULE phrases, which are NOT value names.
_TOLERANCE_WORDS = ("middle initial", "maiden", "be tolerant", "tolerant of")


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_generation_is_deterministic_and_matches_the_committed_file(tmp_path: Path) -> None:
    fresh = write_owner_match_worksheet(tmp_path).read_text(encoding="utf-8")
    assert (
        write_owner_match_worksheet(tmp_path).read_text(encoding="utf-8") == fresh
    )  # deterministic
    assert _COMMITTED.read_text(encoding="utf-8") == fresh  # the committed sheet is in sync


def test_thirtythree_rows_blind_no_golden_or_prediction() -> None:
    rows = _rows(_COMMITTED.read_text(encoding="utf-8"))
    # LP-401: 11 statements x 3 tags = 33 blind rows
    assert len(rows) == 33
    assert {r["tag_id"] for r in rows} == {
        "stmt.owner_matches_borrower",
        "stmt.holder_name_variance",
        "stmt.non_borrower_co_holder",
    }
    # every golden is EMPTY (she fills it) — no per-row answer anchors her
    assert all(not (r["golden_label"] or "").strip() for r in rows)
    assert all(not (r["labeler_note"] or "").strip() for r in rows)


def test_no_ai_reasoning_or_clearcut_answer_reaches_the_sheet() -> None:
    low = _COMMITTED.read_text(encoding="utf-8").lower()
    for phrase in _AI_REASONING:
        assert phrase not in low, f"AI reasoning leaked into the sheet: {phrase!r}"
    # the clear-cut constants exist in code; assert they are NOT encoded per-row (golden blank already proves
    # it, but pin that no row's context carries a bare "answer: yes/no" style leak beyond the allowed-values).
    for r in _rows(_COMMITTED.read_text(encoding="utf-8")):
        assert "expected" not in r["context"].lower() and "clear-cut" not in r["context"].lower()
    # the constants themselves are not empty (they DO exist in code — this is where they legitimately live)
    assert CLEARCUT_EXPECTATIONS and AMBIGUOUS_CASES


def test_context_shows_both_the_holder_and_the_roster() -> None:
    # judgeability (D-critical): without the roster she cannot compare, and would label `unknown` meaning
    # "I can't tell" (the LP-390-3 missing-field lesson) rather than a real judgment.
    for r in _rows(_COMMITTED.read_text(encoding="utf-8")):
        ctx = r["context"]
        assert "account_holder_name=" in ctx  # the holder on the statement
        # the full roster (LP-401 added Sarah Chen) — she compares against all borrowers
        assert "loan_borrowers: Jordan A Rivera; Robert Chen; Sarah Chen" in ctx


def test_the_prompt_shows_values_but_not_the_models_selection_rules() -> None:
    low = _COMMITTED.read_text(encoding="utf-8").lower()
    for word in _TOLERANCE_WORDS:
        assert word not in low, f"the prompt teaches the AI's answer key: {word!r}"
    # the neutral questions ARE asked, and the variance VALUES are shown (D3 — she can't pick blind otherwise)
    assert "match one of the loan's borrowers" in low
    assert "how does the name differ" in low
    assert (
        "middle_absent / middle_differs / nickname / surname_differs" in low
    )  # the taxonomy, as options
    assert "additional account holder who is not" in low  # the co-holder question


def test_row_order_groups_by_tag_and_does_not_cluster_positives() -> None:
    rows = _rows(_COMMITTED.read_text(encoding="utf-8"))
    # GROUP BY TAG (D4): a scenario's 3 rows sit 11 apart, so one answer can't bias the same scenario's next tag
    tags_in_order = [r["tag_id"] for r in rows]
    assert tags_in_order[:11] == ["stmt.owner_matches_borrower"] * 11
    assert tags_in_order[11:22] == ["stmt.holder_name_variance"] * 11
    assert tags_in_order[22:] == ["stmt.non_borrower_co_holder"] * 11
    # within each tag block, the positives are interspersed (P1 at index 1, P2 at index 5 — not grouped)
    for block_start in (0, 11, 22):
        block = [rows[block_start + i]["subject_id"] for i in range(11)]
        positives = [i for i, s in enumerate(block) if s in ("own-p1", "own-p2")]
        assert positives == [1, 5]  # deterministic, non-grouping
        assert block[0].startswith("own-n") and block[-1].startswith("own-n")
