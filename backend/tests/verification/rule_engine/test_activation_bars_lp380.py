"""LP-380 — activation bars: the declared decision surface for which inert rules may go live.

These pin the discipline: the table is COMPLETE (every inert rule has a proposed bar + rationale); a rule with
an UNMEASURED tag is BLOCKED ON CALIBRATION, never "just below a bar" (the two statuses are visually and
behaviourally distinct — else a rule ships on a tag nobody measured); every bar is validated=false (Priya's
sign-off flips it, not this ticket); the bar is DECLARED and resolved by data, no per-rule evaluator branch;
and it reconciles with LP-376-B as one safety with two settings (below-bar → needs_review, judgment → ratify).
Nothing is activated: ACTIVE_RULE_IDS is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.verification.rule_engine import activation_bars as ab
from app.verification.rule_engine.activation_bars import (
    ActivationBar,
    ActivationBarError,
    activation_mode,
    load_activation_bars,
)
from app.verification.rule_engine.registry import _BASE_ACTIVE, ACTIVE_RULE_IDS


def _bar(status: str, ships: str, threshold: float | None) -> ActivationBar:
    return ActivationBar("X-1", status, ships, threshold, False, (), "", "test")


# --------------------------------------------------------------------------- #
# COMPLETE — every inert rule has a proposed bar + rationale
# --------------------------------------------------------------------------- #
def test_bars_cover_exactly_the_inert_rules() -> None:
    bars = load_activation_bars()
    specs = {
        p.stem for p in (Path(ab.__file__).resolve().parents[1] / "rules/specs").glob("*.yaml")
    }
    # Anchored to _BASE_ACTIVE, not the live set: a rule LP-389 activated (IN-1/IN-5) KEEPS its bar as the
    # record of why it went live, so the candidate set stays a stable 27 (23 + OC-1 LP-406-4 + AS-8 LP-406-2b
    # + IN-6 LP-406-3b + PC-7 LP-406-1b) rather than shrinking on activation.
    candidates = specs - set(_BASE_ACTIVE)
    assert set(bars) == candidates  # no candidate rule missing, no base-active rule sneaking in
    assert all(
        b.rationale.strip() for b in bars.values()
    )  # none blank — the proposal Priya reasons over


def test_the_honest_activation_state_is_reported() -> None:
    # 11 of 27 are calibratable-now; the rest are blocked on calibration / a producer / a wiring decision.
    # OC-1 (LP-406-4) not-calibratable-yet + HELD; AS-8/IN-6/PC-7 are all LIVE now (AS-8 no-ai, LP-406-2b;
    # IN-6 calibratable-now validated + PC-7 no-ai-threshold-pending validated, both LP-412).
    bars = load_activation_bars()
    by = {
        s: sum(1 for b in bars.values() if b.status == s) for s in {b.status for b in bars.values()}
    }
    # The calibratable-now STATUS count is unchanged by activation (a signed-off bar keeps its status, only
    # moving unvalidated -> validated). AS-6 (LP-429) is now among the validated calibratable-now bars.
    assert (
        by["calibratable-now"] == 14
    )  # +IN-6 (LP-406-3b) +IN-12 (LP-423) +IN-8 +IN-9 (LP-426/LP-428) +AS-6 (LP-397/LP-429) — all now validated
    assert by.get("not-calibratable-yet", 0) >= 1 and by.get("no-ai-dependency", 0) >= 1
    assert (
        by.get("no-ai-threshold-pending", 0) == 1
    )  # PC-7 (LP-411 — the third case, held on Priya's window)
    # LP-390-7 signed off AS-2 + AS-12; LP-390-9 signed off IN-3; LP-393-6 signed off IN-7/IN-10/IN-11/AS-11;
    # LP-429 signed off AS-6 — all validated calibratable-now rules.
    assert all(
        bars[r].validated
        for r in ("IN-1", "IN-5", "AS-2", "AS-12", "IN-3", "IN-7", "IN-10", "IN-11", "AS-11")
    )
    assert bars["AS-6"].status == "calibratable-now" and bars["AS-6"].threshold is not None
    assert bars[
        "AS-6"
    ].validated  # LP-429 — Priya signed off (validating it activated it, LP-393-6)


# --------------------------------------------------------------------------- #
# not-calibratable-yet ≠ bar-unmet — the load-bearing distinction
# --------------------------------------------------------------------------- #
def test_unmeasured_rule_is_blocked_not_below_a_bar() -> None:
    # an unmeasured rule has NO threshold and resolves to 'blocked' — never 'needs_review' (which would imply a
    # measured score that merely fell short). Conflating them would ship a rule on a tag nobody measured.
    for status in ("not-calibratable-yet", "needs-producer", "no-ai-dependency"):
        bar = _bar(status, "auto", None)
        assert bar.threshold is None
        assert activation_mode(bar, 0.999) == "blocked"
    # a CALIBRATABLE rule below its bar is a different thing: needs_review, not blocked
    assert activation_mode(_bar("calibratable-now", "auto", 0.98), 0.90) == "needs_review"


def test_loader_rejects_a_threshold_on_a_non_calibratable_rule() -> None:
    # These loader-rejection tests use the neutral synthetic label "X-1" (not a real rule id) — the rejected
    # bar shapes below are invalid on purpose, and "AS-2" is now a real validated calibratable-now rule.
    with pytest.raises(ActivationBarError, match="threshold must be null"):
        ab.parse_bar(
            "X-1",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": 0.9,
                "validated": False,
                "rationale": "x",
            },
        )


def test_loader_rejects_a_boolean_threshold() -> None:
    # A YAML bool is an int in Python (bool ⊂ int); `threshold: true` must fail loud, never coerce to a
    # silent 1.0 bar in an otherwise fail-loud loader.
    with pytest.raises(ActivationBarError, match="proposed threshold in"):
        ab.parse_bar(
            "X-1",
            {
                "status": "calibratable-now",
                "ships": "auto",
                "threshold": True,
                "validated": False,
                "rationale": "x",
            },
        )


def test_loader_rejects_validating_a_non_calibratable_rule() -> None:
    # Priya can sign off a bar, but NOT on a rule blocked on calibration — that would sign off a tag nobody
    # measured. Only calibratable-now may be validated.
    with pytest.raises(ActivationBarError, match="cannot be signed off as live-able"):
        ab.parse_bar(
            "X-1",
            {
                "status": "not-calibratable-yet",
                "ships": "auto",
                "threshold": None,
                "validated": True,
                "rationale": "x",
            },
        )


def test_loader_rejects_non_bool_validated() -> None:
    with pytest.raises(ActivationBarError, match="validated must be a boolean"):
        ab.parse_bar(
            "X-1",
            {
                "status": "no-ai-dependency",
                "ships": "auto",
                "threshold": None,
                "validated": "yes",
                "rationale": "x",
            },
        )


# --------------------------------------------------------------------------- #
# Priya's sign-off — IN-1/IN-5 (LP-389) + AS-2/AS-12 (LP-390-7) + IN-3 (LP-390-9) are validated; rest stay false
# --------------------------------------------------------------------------- #
def test_exactly_the_signed_off_bars_are_validated() -> None:
    bars = load_activation_bars()
    validated = {rid for rid, b in bars.items() if b.validated}
    # IN-1/IN-5 (LP-389) + AS-2/AS-12 (LP-390-7) + IN-3 (LP-390-9) + IN-7/IN-10/IN-11/AS-11 (LP-393-6) +
    # IN-6 (calibratable) + PC-7 (no-ai-threshold-pending) — LP-412 signed off the last two.
    assert (
        validated
        == {
            "IN-1",
            "IN-5",
            "AS-2",
            "AS-12",
            "IN-3",
            "IN-7",
            "IN-10",
            "IN-11",
            "AS-11",
            "IN-6",  # LP-412 — 0.95, "same as IN-5"
            "PC-7",  # LP-412 — the two-sided window (any past date; 90-day far-future)
            "IN-12",  # LP-423 — inherits IN-11's validated 0.9 (deterministic Schedule-C gate)
            "IN-8",  # LP-428 — Priya signed off 0.95 (voe_present 100%, synthetic caveat weighed)
            "IN-9",  # LP-428 — Priya signed off 0.95 (offer_letter_present 100%, caveats weighed)
            "AS-6",  # LP-429 — Priya signed off 0.95 (routing 11/11; the reason-only variance tag excluded)
        }
    )  # NOTE: PC-2 (LP-407-3) is no-ai-dependency with validated:false — it is NOT in this signed-off set.
    assert all(b.validated is False for rid, b in bars.items() if rid not in validated)
    # A validated bar is one the loader PERMITS `validated: true` on — calibratable-now (an AI-accuracy bar,
    # real threshold) OR no-ai-threshold-pending (LP-411 — a Priya window sign-off, null threshold, e.g. PC-7).
    # Never a blocked rule (the loader rejects that — the AS-5 invariant).
    for rid in validated:
        b = bars[rid]
        if b.status == "calibratable-now":
            assert b.threshold is not None
        else:
            assert b.status == "no-ai-threshold-pending" and b.threshold is None


def test_thresholds_exist_only_where_calibratable() -> None:
    for b in load_activation_bars().values():
        assert (b.threshold is not None) == (b.status == "calibratable-now")
        if b.threshold is not None:
            assert 0.0 <= b.threshold <= 1.0


# --------------------------------------------------------------------------- #
# DECLARED, not branched — activation_mode depends only on bar DATA, not rule identity
# --------------------------------------------------------------------------- #
def test_mode_is_data_driven_not_per_rule() -> None:
    a = ActivationBar("IN-1", "calibratable-now", "auto", 0.98, False, (), "", "r")
    b = ActivationBar("ZZ-9", "calibratable-now", "auto", 0.98, False, (), "", "r")
    assert activation_mode(a, 0.99) == activation_mode(b, 0.99) == "auto"  # same data → same mode


# --------------------------------------------------------------------------- #
# Reconciled with LP-376-B — one safety, two settings
# --------------------------------------------------------------------------- #
def test_below_bar_routes_to_needs_review_and_judgment_ratifies() -> None:
    assert activation_mode(_bar("calibratable-now", "auto", 0.98), 0.97) == "needs_review"
    assert activation_mode(_bar("calibratable-now", "auto", 0.98), 0.98) == "auto"
    # a judgment rule NEVER auto-ships (LP-376-B) — it ratifies even at 100%
    assert activation_mode(_bar("calibratable-now", "ratify", 0.98), 1.0) == "ratify"


# --------------------------------------------------------------------------- #
# ACTIVATION — LP-380 activated nothing; LP-389 (the first pass) activated exactly IN-1/IN-5 via the gate
# --------------------------------------------------------------------------- #
def test_active_set_is_base_plus_lp389() -> None:
    assert (
        ACTIVE_RULE_IDS
        == (
            "AS-1",
            "OC-2",
            "ID-2",
            "ID-4",
            "ID-1",
            "ID-3",
            "ID-6",
            "ID-7",
            "ID-9",
            "ID-8",
            "IN-2",
            # LP-389 — the first activation pass, via the eligibility gate (activation_bars.is_eligible)
            "IN-1",
            "IN-5",
            "ID-5",  # LP-389-A — the subject mismatch fixed (per-borrower), input now resolves
            # LP-384 — the second activation pass: the stuck deterministic rules, verified on build_lf6t3n_plus
            "AS-9",
            "IN-4",
            "AS-10",
            # LP-390-7 — the first income-wave activation: AS-2 (auto) + AS-12 (ratify), Priya's 0.90 bars signed off
            "AS-2",
            "AS-12",
            "IN-3",  # LP-390-9 — YTD-annualized shortfall (auto), Priya signed off the 0.98 bar (same tag as IN-1)
            # LP-393-6 — the scenario-calibrated income/asset rules; Priya signed off her heights + chose AUTO
            # (IN-7 still ships RATIFY by kind — LP-376-B armor). is_declining/has_2yr_history/liquidation scored
            # on the LP-393-1 fixture; has_2yr_history RE-SCORED after her B14 ruling.
            "IN-7",
            "IN-10",
            "IN-11",
            "AS-11",
            # LP-406-2b — the first Bucket 2 rule live: AS-8 (statement chaining) on the derived stmt.continuity
            # tag; no-ai-dependency, input resolves ("chained" on LF-6T3N).
            "AS-8",
            # LP-412 — Priya signed off the last two Bucket 2 bars: IN-6 (0.95, "same as IN-5") and PC-7 (the
            # closing window). PC-7 is the first rule live via LP-411's no-ai-threshold-pending status.
            "IN-6",
            "PC-7",
            # LP-407-3 — the one surviving Bucket 2.5 rule: PC-2 (purchase price matches loan terms),
            # no-ai-dependency + exact compare (no threshold), input resolves (365000 on the repaired LF-6T3N).
            "PC-2",
            # LP-417 — the first Bucket 3 rule live: IH-3 (insurance effective date vs closing), a native
            # date compare off the already-extracted homeowners binder; no-ai-dependency, no threshold.
            "IH-3",
            # LP-407-4 — the last blocker-free rule: PC-3 (contract property address vs the loan file), a
            # deterministic address compare; no-ai-dependency, mismatch routes to needs_review (ADR-325).
            "PC-3",
            # LP-423 — IN-12 (self-employed 2yr history): calibratable-now, verdict inherits IN-11's validated
            # 0.9, gate is a deterministic Schedule-C fact (LP-422).
            "IN-12",
            # LP-428 — IN-8 (VOE present) + IN-9 (offer letter present): calibratable-now, both scored 100%
            # (12/12, two-sided) on Priya's blind labels (LP-426); she signed off 0.95 for each, weighing the
            # synthetic caveat. Structural presence checks → ships auto.
            "IN-8",
            "IN-9",
            # LP-429 — AS-6 (account ownership): the FIRST multi-tag rule; routing rests on owner_matches +
            # non_borrower_co_holder (both 11/11), Priya signed off 0.95. Structural → ships auto.
            "AS-6",
        )
    )
    # A bar persists after activation as the record of WHY the rule went live, so the bars now intersect the
    # active set at EXACTLY the activated candidates — never a base-active rule (those never had a bar).
    assert (
        set(load_activation_bars()) & set(ACTIVE_RULE_IDS)
        == {
            "IN-1",
            "IN-5",
            "ID-5",
            "AS-9",
            "IN-4",
            "AS-10",
            "AS-2",
            "AS-12",
            "IN-3",
            "IN-7",
            "IN-10",
            "IN-11",
            "AS-11",
            "AS-8",  # LP-406-2b — live via its bar (no-ai-dependency, input resolves)
            "IN-6",  # LP-412 — live via its bar (calibratable-now, validated)
            "PC-7",  # LP-412 — live via its bar (no-ai-threshold-pending, validated)
            "PC-2",  # LP-407-3 — live via its bar (no-ai-dependency, input resolves)
            "IH-3",  # LP-417 — live via its bar (no-ai-dependency, native date compare)
            "PC-3",  # LP-407-4 — live via its bar (no-ai-dependency, needs_review route)
            "IN-12",  # LP-423 — live via its bar (calibratable-now, validated; deterministic Schedule-C gate)
            "IN-8",  # LP-428 — live via its bar (calibratable-now, validated; Priya signed off 0.95)
            "IN-9",  # LP-428 — live via its bar (calibratable-now, validated; Priya signed off 0.95)
            "AS-6",  # LP-429 — live via its bar (calibratable-now, validated; routing 11/11, Priya signed off)
        }
    )
    assert not (set(load_activation_bars()) & set(_BASE_ACTIVE))
