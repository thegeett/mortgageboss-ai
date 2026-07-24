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

# distinctive phrases from LP-398's PUBLISHED probe reasoning — none may appear in the blind sheet.
_AI_REASONING = (
    "matches borrower",
    "trust entity",
    "limited liability",
    "could potentially",
    "joint account with",
    "does not match either",
    "'bob' = 'robert'",
)
# the AI's tolerance clauses — the prompt must NOT restate them (it would teach her the answer key).
_TOLERANCE_WORDS = ("middle initial", "nickname", "maiden", "tolerant")


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_generation_is_deterministic_and_matches_the_committed_file(tmp_path: Path) -> None:
    fresh = write_owner_match_worksheet(tmp_path).read_text(encoding="utf-8")
    assert (
        write_owner_match_worksheet(tmp_path).read_text(encoding="utf-8") == fresh
    )  # deterministic
    assert _COMMITTED.read_text(encoding="utf-8") == fresh  # the committed sheet is in sync


def test_all_eight_rows_blind_no_golden_or_prediction() -> None:
    rows = _rows(_COMMITTED.read_text(encoding="utf-8"))
    assert len(rows) == 8 and {r["tag_id"] for r in rows} == {"stmt.owner_matches_borrower"}
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
        assert (
            "loan_borrowers: Jordan A Rivera; Robert Chen" in ctx
        )  # the roster to compare against


def test_the_prompt_does_not_restate_the_ai_tolerance_rules() -> None:
    low = _COMMITTED.read_text(encoding="utf-8").lower()
    for word in _TOLERANCE_WORDS:
        assert word not in low, f"the prompt teaches the AI's answer key: {word!r}"
    # it DOES ask the neutral core question with the allowed values
    assert "match one of the loan's borrowers" in low and "yes / no / unknown" in low


def test_row_order_does_not_group_negatives_then_positives() -> None:
    order = [r["subject_id"] for r in _rows(_COMMITTED.read_text(encoding="utf-8"))]
    positives = [i for i, s in enumerate(order) if s in ("own-p1", "own-p2")]
    # the two positives are INTERSPERSED — not both at the end, and they split the run of negatives.
    assert positives == [1, 4]  # own-p1 at index 1, own-p2 at index 4 (deterministic, non-grouping)
    assert order[0].startswith("own-n") and order[-1].startswith(
        "own-n"
    )  # not a positives block at an edge
