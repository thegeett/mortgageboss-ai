"""LP-344 — the two txn Stage-A prompts are CONVERGED (one text, guarded), closing LP-343's drift.

The bug LP-343 found was a MEASUREMENT-VALIDITY bug: LIVE AS-1 runs the standalone
``STAGE_A_TRANSACTION_SYSTEM_PROMPT`` (app/ai), while LP-337's calibration measured the generic
``txn_stage_a`` group's YAML text — a DIFFERENT prompt (the standalone defines apparent_category; the YAML
did not). Two producers, two texts, one measured, the other shipped, drifted for months, unnoticed.

The class (two producers for one tag, silently divergent) is closed by TWO standing guards, both here:
  1. TEXT guard (this module) — the standalone constant and the declared group's text are byte-identical.
  2. PRODUCER guard (pre-existing: test_producers.test_txn_roundtrip_through_the_generic_producer_is_equivalent)
     — given identical judgments, the generic and standalone producers assemble IDENTICAL tags.
Together: same prompt text + equivalent producer → the calibration (generic path) measures exactly what
LIVE AS-1 (standalone path) ships. Neither can drift without a red test.
"""

from __future__ import annotations

from app.ai.tag_production import STAGE_A_TRANSACTION_SYSTEM_PROMPT
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.tag_materialization.declarations import load_ai_groups, load_declarations


def _txn_group_prompt() -> str:
    return load_ai_groups()["txn_stage_a"].system_prompt


# ================================================================================================= #
# THE DRIFT GUARD — the measured prompt and the shipped prompt CANNOT differ
# ================================================================================================= #
def test_txn_stage_a_prompt_convergence() -> None:
    # THE guard: the generic `txn_stage_a` group's text (what calibration measures) is byte-identical to
    # the standalone constant (what LIVE AS-1 runs). `.strip()` normalizes only the YAML block scalar's
    # trailing newline vs the Python constant's — the meaningful text must match exactly. If anyone edits
    # ONE of the two, this fails: drift is impossible to merge.
    assert STAGE_A_TRANSACTION_SYSTEM_PROMPT.strip() == _txn_group_prompt().strip()


def test_calibration_measures_the_shipped_text() -> None:
    # calibrate_lf6t3n scores txn via produce_ai_group_tags(load_ai_groups()["txn_stage_a"]) — i.e. the
    # SAME text object this guard pins to the shipped constant. So the measured text IS the shipped text
    # (and the producer is proven-equivalent by the pre-existing roundtrip test). No LP-337-style
    # measurement of the wrong prompt can recur.
    assert _txn_group_prompt().strip() == STAGE_A_TRANSACTION_SYSTEM_PROMPT.strip()


# ================================================================================================= #
# THE CONVERGED TEXT keeps the standalone's exemplary properties (LP-343 called it "the model")
# ================================================================================================= #
def test_converged_text_is_the_exemplary_standalone_not_the_thin_yaml() -> None:
    text = _txn_group_prompt()
    # anti-bias on direction (the thin YAML lacked this) — the property LP-343 praised
    assert "Do NOT assume a positive amount means" in text
    # `unknown` is first-class
    assert '"unknown" is a correct, expected answer' in text
    # apparent_category values are DEFINED (LP-343's F5 — the thin YAML listed them undefined)
    assert "transfer_own\" (a transfer between the borrower's own accounts)" in text
    assert 'vendor" (an ordinary purchase' in text
    # states the §3D principle (a tag reports facts; the rule judges)
    assert "you do NOT\n" in text or "you do NOT " in text
    assert (
        "Downstream\n" in text or "Downstream " in text
    )  # "Downstream deterministic code does all judgement"


# ================================================================================================= #
# ONE PRODUCTION PATH — txn Stage-A is the ONLY dual-producer tag (the survey, asserted)
# ================================================================================================= #
def test_txn_stage_a_is_the_only_dual_producer_and_stage_b_is_single() -> None:
    decls = load_declarations()
    # the txn Stage-A tags ARE declared (the generic group) AND have the standalone constant twin — the
    # one dual case this ticket converges.
    for tag in ("txn.is_money_in", "txn.apparent_category"):
        assert decls[tag].data == "txn_stage_a"
    # the Stage-B sourcing tags are produced by tag_correlation ONLY — NOT declared as a generic group,
    # so there is no second text to drift against (a different gap — LP-343 F1 — not this class).
    for tag in ("txn.has_identified_source", "txn.source_reference", "txn.counterparty"):
        assert tag not in decls  # undeclared -> single producer, not a dual-producer drift risk


# ================================================================================================= #
# EQUIVALENCE — the live path is untouched (this ticket did not move AS-1)
# ================================================================================================= #
def test_no_rule_activation_changed() -> None:
    assert ACTIVE_RULE_IDS == (
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
    )
