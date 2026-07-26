"""LP-403 — widen the holder_name_variance gate to `yes OR unknown` so a flagged-for-evidence (owner=unknown)
document keeps its recorded difference (LP-402's coupling finding).

Keyless: the live re-score (owner_matches 11/11 + non_borrower_co_holder 11/11 unchanged; the flag/unknown cases
now RECORD a difference instead of `none`; the 5 real LF-6T3N goldens intact; residual taxonomy + no-case
divergences) is reported in docs/tickets/LP-403.md. These pin: the widened gate clause; the value set unchanged;
the sibling prompts untouched; AS-6 untouched.
"""

from __future__ import annotations

from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.declarations import (
    _allowed_values_by_tag,
    load_ai_groups,
)


def test_the_variance_gate_is_yes_or_unknown_none_only_for_no() -> None:
    flat = " ".join(load_ai_groups()["stmt_facts"].system_prompt.lower().split())
    # the widened gate: describe when owner_matches is yes OR unknown (a flagged plausible borrower keeps its
    # difference); `none` only for a genuine `no`.
    assert 'when owner_matches_borrower is "yes" or "unknown"' in flat
    assert '"none" when owner_matches_borrower is "no"' in flat


def test_the_variance_value_set_is_unchanged() -> None:
    # only WHEN the tag fires changed — not WHAT it can say.
    variance = _allowed_values_by_tag()["stmt.holder_name_variance"]
    assert variance == (
        "none",
        "middle_absent",
        "middle_differs",
        "nickname",
        "surname_differs",
        "other",
        "unknown",
    )


def test_the_sibling_prompts_are_untouched() -> None:
    # owner_matches (LP-402) + co_holder + is_reserve clauses are unchanged — the widening touches only variance.
    low = load_ai_groups()["stmt_facts"].system_prompt.lower()
    assert "essentially certain" in low and "flag for evidence" in low  # owner_matches, LP-402
    assert "is there an additional account holder" in low  # co_holder
    assert "usable as reserves" in low  # is_reserve
    assert _allowed_values_by_tag()["stmt.owner_matches_borrower"] == ("yes", "no", "unknown")
    assert _allowed_values_by_tag()["stmt.non_borrower_co_holder"] == ("yes", "no", "unknown")


def test_as6_untouched_and_nothing_activated() -> None:
    spec = load_rule_spec("AS-6")
    assert spec.deterministic is not None
    assert list(spec.deterministic.load_bearing_tags) == ["stmt.owner_matches_borrower"]
    assert len(ACTIVE_RULE_IDS) == 24
