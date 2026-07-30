"""LP-414 — two separable jobs: REPAIR LF-6T3N's placeholder field names (Part A, an equivalence-gated
defect fix) and a STANDALONE fire-path scenario fixture (Part B).

Part A pins: the repaired contract/property fields now MATERIALIZE their tags (contract.sales_price /
property.purchase_price / contract.loan_sales_price → the real 365000), the PC-7 realism anchor
(contract.days_until_closing == "1") did NOT move, NO live rule reads any repaired tag (the equivalence is
structural, not luck), and the full 27-rule verdict distribution on LF-6T3N is byte-stable.

Part B pins: each scenario FIRES its target (AS-8 broken; PC-7 past + far-future) or materializes its input
(housing taxes/HOA), and the fixtures are standalone (own id namespace, disjoint from LF-6T3N / income /
owner-match — the LP-393-1 discipline).
"""

from __future__ import annotations

from collections import Counter

import pytest
from app.verification.eval.fire_path_scenarios import (
    EXPECTED_HOA_MONTHLY,
    EXPECTED_TAXES_MONTHLY,
    build_far_future_closing_snapshot,
    build_past_closing_snapshot,
    build_statement_break_snapshot,
    build_subject_housing_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.eval.stubs import stub_materialization_reasoners
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_LOAN = "loan"
_AS8 = load_rule_spec("AS-8")
_PC7 = load_rule_spec("PC-7")


async def _parsed_derived(snap):
    """Materialize parsed + derived only (no AI) — the keyless seam."""
    return await materialize_tags(snap, only_groups=frozenset())


def _loan_tag(mat, tag_id: str) -> str | None:
    tag = mat.tags.by_subject.get(_LOAN, {}).get(tag_id)
    return None if tag is None else str(tag.value)


# ======================================================================= #
# PART A — the repair, equivalence-gated
# ======================================================================= #
async def test_repaired_fields_now_materialize_their_tags() -> None:
    # The LP-407-2 gap: contract.sales_price / property.purchase_price / contract.loan_sales_price all read
    # `unknown`/absent on a file that VISIBLY has the documents, because the fixture carried placeholder field
    # names. After the rename they read the real 365000.
    mat = await _parsed_derived(build_lf6t3n_snapshot())
    # contract.sales_price is a DOCUMENT tag (on the purchase agreement pa1)
    pa_price = mat.tags.by_subject.get("pa1", {}).get("contract.sales_price")
    assert pa_price is not None and str(pa_price.value) == "365000.00"
    assert _loan_tag(mat, "property.purchase_price") == "365000.00"
    assert _loan_tag(mat, "contract.loan_sales_price") == "365000.00"


async def test_pc7_realism_anchor_did_not_move() -> None:
    # The HARD GATE: PC-7 reads a contract field. The price rename must NOT disturb the closing date — the
    # anchor stays contract.days_until_closing == "1" and PC-7 stays satisfied (LP-412).
    mat = await _parsed_derived(build_lf6t3n_snapshot())
    assert _loan_tag(mat, "contract.days_until_closing") == "1"
    assert [r.verdict for r in evaluate_deterministic_rule(_PC7, mat)] == [Verdict.SATISFIED]


def test_no_live_rule_read_a_repaired_tag_when_lp414_shipped() -> None:
    # WHY the LP-414 repair was verdict-safe by construction (not luck): at the time, no live rule read any
    # repaired/gained tag. (LP-407-3 LATER made PC-2 live, which reads property.purchase_price +
    # contract.loan_sales_price — an intended NEW rule, not a repair regression; those two are excluded here.)
    # The rest are still read by no live rule. Reuses the orphan guard's own "hard read" machinery.
    from tests.verification.tag_materialization.test_vocabulary_orphans import _live_hard_reads

    live_reads = _live_hard_reads()
    for tag_id in (
        "contract.sales_price",  # PC-2 reads the loan-level PROMOTION, not this per-document tag
        "housing.taxes_monthly",
        "housing.hoa_monthly",
    ):
        assert tag_id not in live_reads, tag_id
    # LP-407-3: PC-2 (live) now reads these two — documented so this test stays honest, not stale.
    assert {"property.purchase_price", "contract.loan_sales_price"} <= live_reads


async def test_lf6t3n_full_verdict_distribution_is_stable() -> None:
    # The equivalence gate as a regression lock. LP-414: 302 evals; LP-407-3 +PC-2 (satisfied); LP-417 +IH-3
    # (couldnt_check); LP-407-4 +PC-3 (couldnt_check). LP-423 ACTIVATED IN-12 (per_borrower) → +2 evals, both
    # COULDNT_CHECK. LP-428 ACTIVATED IN-8 + IN-9 (both per_document over LF-6T3N's 30 documents) → +60 evals:
    # each gates to its own doc type (voe / employment_offer_letter), so 26 non-matching docs → not_applicable and
    # the 4 matching docs → couldnt_check (their presence tag is honest-unknown under the keyless stub; a real AI
    # would read yes/no). So +52 not_applicable + +8 couldnt_check → 367. LP-429 ACTIVATED AS-6 (per_document over
    # the 30 docs): 21 non-bank-statement docs → not_applicable, and the 9 statements/unclassified → couldnt_check
    # (owner_matches is honest-unknown under the stub; a real AI reads yes → satisfied, per the LP-429 real run).
    # So +21 not_applicable + +9 couldnt_check → 397. LP-430 ACTIVATED IN-15 (per_borrower): LF-6T3N's 2
    # borrowers have no VOE → income.terminated_employment = not_terminated → not_applicable, so +2
    # not_applicable. The lock is now 399 evals / couldnt_check 200. Any OTHER movement would be a regression.
    mat = await materialize_tags(
        build_lf6t3n_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    results, _ = await evaluate_rules(mat)
    assert len(results) == 399
    assert (
        Counter(r.verdict.value for r in results)
        == {
            "couldnt_check": 200,  # +AS-6 x9 (LP-429 — owner_matches unknown under the stub on 5 stmts + 4 unclassified)
            "not_applicable": 174,  # +AS-6 x21 (LP-429) +IN-15 x2 (LP-430 — no VOE on LF-6T3N → not_terminated)
            "satisfied": 21,  # +PC-2 (LP-407-3): both prices 365000 → satisfied
            "fired": 2,
            "needs_review": 2,
        }
    )
    loan_verdicts = {r.rule_id: r.verdict.value for r in results if r.subject_id == _LOAN}
    assert loan_verdicts == {
        "AS-8": "satisfied",
        "AS-10": "satisfied",
        "PC-7": "satisfied",
        "PC-2": "satisfied",  # LP-407-3 — the contract price matches the 1003 (365000)
        "IH-3": "couldnt_check",  # LP-417 — no homeowners binder on LF-6T3N (an honest absence)
        "PC-3": "couldnt_check",  # LP-407-4 — no MISMO subject-property address on LF-6T3N
        "ID-6": "fired",
        "IN-2": "fired",
        "IN-3": "couldnt_check",
        "IN-4": "couldnt_check",
        "OC-2": "couldnt_check",
    }


# ======================================================================= #
# PART B — the fire-path scenarios
# ======================================================================= #
async def test_statement_break_fires_as8() -> None:
    mat = await _parsed_derived(build_statement_break_snapshot())
    assert _loan_tag(mat, "stmt.continuity") == "broken"
    results = evaluate_deterministic_rule(_AS8, mat)
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert "balance" in results[0].reasoning.lower()


async def test_past_closing_fires_pc7_with_the_day_count() -> None:
    mat = await _parsed_derived(build_past_closing_snapshot())
    assert _loan_tag(mat, "contract.days_until_closing") == "-61"
    results = evaluate_deterministic_rule(_PC7, mat)
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert "passed" in results[0].reasoning and "-61" in results[0].reasoning


async def test_far_future_closing_fires_pc7() -> None:
    mat = await _parsed_derived(build_far_future_closing_snapshot())
    assert _loan_tag(mat, "contract.days_until_closing") == "153"
    results = evaluate_deterministic_rule(_PC7, mat)
    assert [r.verdict for r in results] == [Verdict.FIRED]
    assert "153" in results[0].reasoning


async def test_subject_housing_tags_materialize_real_figures() -> None:
    # DT-4 / DT-2 input provability with the REAL extractor field names (LF-6T3N's two conflicting bills
    # cannot show it — housing.taxes_monthly abstains there).
    mat = await _parsed_derived(build_subject_housing_snapshot())
    assert _loan_tag(mat, "housing.taxes_monthly") == EXPECTED_TAXES_MONTHLY
    assert _loan_tag(mat, "housing.hoa_monthly") == EXPECTED_HOA_MONTHLY


# ======================================================================= #
# Separation (LP-393-1) + equivalence
# ======================================================================= #
def test_scenario_fixtures_are_standalone_and_disjoint() -> None:
    # Own id namespace (95…), disjoint from LF-6T3N (1111…/2222…), income (93…), owner-match (94…). Each
    # scenario is a distinct loan. Never merged into, never importing, the other fixtures.
    from app.verification.eval import fire_path_scenarios as fp
    from app.verification.eval.owner_match_scenarios import build_owner_match_scenario_snapshot

    scenario_ids = {
        str(fp.build_statement_break_snapshot().loan_file_id),
        str(fp.build_past_closing_snapshot().loan_file_id),
        str(fp.build_far_future_closing_snapshot().loan_file_id),
        str(fp.build_subject_housing_snapshot().loan_file_id),
    }
    assert len(scenario_ids) == 4  # four distinct loans (one problem per file)
    assert all(i.startswith("95000000") for i in scenario_ids)

    # Disjoint from the other fixtures (both directions: their ids are not in the 95… space, ours not in theirs).
    lf6t3n_id = str(build_lf6t3n_snapshot().loan_file_id)
    owner_id = str(build_owner_match_scenario_snapshot().loan_file_id)
    assert lf6t3n_id not in scenario_ids and owner_id not in scenario_ids
    assert not lf6t3n_id.startswith("95000000") and owner_id.startswith("94000000")


def test_no_rule_activation_changed() -> None:
    from tests.expected_active import EXPECTED_ACTIVE_RULE_COUNT

    assert (
        len(ACTIVE_RULE_IDS) == EXPECTED_ACTIVE_RULE_COUNT
    )  # LP-414 fixture-only; PC-2 activated in LP-407-3
