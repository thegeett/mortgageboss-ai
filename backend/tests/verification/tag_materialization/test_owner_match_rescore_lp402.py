"""LP-402 — Priya's owner_matches rule (yes=certain / unknown=flag-for-evidence / no=non-person), the co-holder
label correction, and the re-score.

Keyless: the live re-score (owner_matches 11/11, non_borrower_co_holder 11/11, the 5 LF-6T3N goldens still yes,
and the holder_name_variance REGRESSION the conservative change surfaced) is reported in docs/tickets/LP-402.md.
These pin: the corrected committed labels; the refined owner_matches prompt (conservative, reversing LP-390-8a's
tolerance); the OTHER stmt_facts prompts unchanged; AS-6 untouched.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import load_ai_groups

_CSV = Path(__file__).resolve().parents[4] / "docs/calibration/owner-match-scenario-labels.csv"
_OM = "stmt.owner_matches_borrower"
_CO = "stmt.non_borrower_co_holder"


def _labels() -> dict[tuple[str, str], str]:
    return {
        (r["tag_id"], r["subject_id"]): (r["golden_label"] or "").strip()
        for r in csv.DictReader(io.StringIO(_CSV.read_text(encoding="utf-8")))
    }


def test_co_holder_labels_corrected_single_holder_is_no() -> None:
    g = _labels()
    # the 6 single-holder cells corrected to `no` (Priya: "a SECOND extra holder"; the AI was right)
    for sid in ("own-n1", "own-n3", "own-n4", "own-n6", "own-n7", "own-p2"):
        assert g[(_CO, sid)] == "no", sid
    # the real joint-with-non-borrower cases stay `yes`; both-borrowers control stays `no`
    assert g[(_CO, "own-n5")] == "yes" and g[(_CO, "own-n8")] == "yes"
    assert g[(_CO, "own-n9")] == "no"


def test_owner_matches_labels_follow_her_rule() -> None:
    g = _labels()
    # yes = essentially certain (dropped middle / joint-with-borrower)
    for sid in ("own-p1", "own-n5", "own-n8", "own-n9"):
        assert g[(_OM, sid)] == "yes", sid
    # unknown = plausible-but-unverified (flag for evidence): nickname (P2), surname (N7), given-variant (N2)
    for sid in ("own-n2", "own-n7", "own-p2"):
        assert g[(_OM, sid)] == "unknown", sid
    # no = a genuine non-match: non-persons (N3/N4/N6) + N1 (a DIFFERENT middle = a likely different person)
    for sid in ("own-n1", "own-n3", "own-n4", "own-n6"):
        assert g[(_OM, sid)] == "no", sid


def test_corrections_preserve_the_original_labels_as_notes() -> None:
    rows = {
        (r["tag_id"], r["subject_id"]): r
        for r in csv.DictReader(io.StringIO(_CSV.read_text(encoding="utf-8")))
    }
    # a co-holder correction keeps the original `yes`/`unknown` in the note; an owner_matches one keeps `no`
    assert "Original: yes" in rows[(_CO, "own-n7")]["labeler_note"]
    assert "Original: no" in rows[(_OM, "own-n2")]["labeler_note"]
    assert "LP-402" in rows[(_OM, "own-n2")]["labeler_note"]


def test_owner_matches_prompt_is_conservative_reversing_tolerance() -> None:
    prompt = load_ai_groups()["stmt_facts"].system_prompt
    low = prompt.lower()
    # her rule, encoded: certain / flag-for-evidence / conflicting-middle-is-a-non-match
    assert "essentially certain" in low
    assert "flag for evidence" in low
    assert "conflicting middle" in low
    # the LP-390-8a tolerance ("Be TOLERANT ... a MATCH if EITHER") is gone for owner_matches' confidence
    assert "be tolerant of harmless variation" not in low


def test_the_other_stmt_facts_prompts_are_unchanged() -> None:
    # only owner_matches' prompt changed; variance / co_holder / is_reserve clauses are untouched (their goldens
    # + design stay valid). The variance clause still gates on owner_matches == "yes" (the LP-402 coupling
    # finding — its widening is a follow-up ticket, NOT done here).
    low = load_ai_groups()["stmt_facts"].system_prompt.lower()
    # the variance clause still GATES on owner_matches == "yes" (the coupling finding — un-gating it is a
    # follow-up ticket, not done here)
    assert 'when owner_matches_borrower is "yes"' in low
    assert "is there an additional account holder" in low  # co_holder clause, unchanged
    assert "usable as reserves" in low  # is_reserve clause, unchanged


def test_as6_untouched_and_nothing_activated() -> None:
    spec = load_rule_spec("AS-6")
    assert spec.deterministic is not None
    assert list(spec.deterministic.load_bearing_tags) == ["stmt.owner_matches_borrower"]
    assert len(ACTIVE_RULE_IDS) == 24
