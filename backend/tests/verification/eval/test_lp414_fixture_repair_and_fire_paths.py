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
    # borrowers have no VOE → not_terminated → not_applicable, +2 → 399. LP-433 ACTIVATED IN-16 (per_borrower):
    # LF-6T3N's 2 borrowers have W-2s → income.history_documentation = w2_or_1099 → satisfied, +2 satisfied.
    # LP-447 ACTIVATED IH-1 (per_document over the 30 docs): LF-6T3N has NO homeowners binder, so 26 classified
    # non-binder docs → not_applicable and the 4 unclassified ("unknown"-type) docs → couldnt_check (we cannot
    # rule out an unclassified doc is a policy — the honest §8 abstention, the AS-6 shape). So +26 not_applicable
    # +4 couldnt_check → 431. ⚠️ satisfied / needs_review MOVED at LP-508's review (23/2 → 21/4); fired is UNCHANGED — no
    # existing rule's verdict moved; IH-1 only adds honest not_applicable / couldnt_check where LF-6T3N has no
    # binder to judge. Any OTHER movement would be a regression.
    # LP-485 ACTIVATED CL-1 / CR-13 / PR-6 (all subject_enumeration: loan → ONE eval each): LF-6T3N carries no
    # loan estimate, no credit report and no appraisal, so all three derived numbers are "unknown" and the
    # gate routes each to couldnt_check. +3 couldnt_check → 434. ⚠️ THIS IS THE PROPERTY, ON A REAL FIXTURE:
    # a file missing the document reads couldnt_check, NEVER satisfied — the rules do not clear on absence.
    # satisfied / fired / needs_review stay 23 / 2 / 2.
    # LP-487 ACTIVATED IH-2 (per_document over the 30 docs) + IH-7 (loan-scoped): LF-6T3N has no homeowners
    # binder, so IH-2 gives 26 not_applicable + 4 couldnt_check on the unclassified docs (the IH-1 shape —
    # an unclassified document cannot be ruled out as a binder). LF-6T3N's MISMO states no property type,
    # so IH-7's applicability predicate is UNDETERMINED → 1 couldnt_check, NOT not_applicable: an unstated
    # property type must not silently skip the condo check. +26 not_applicable +5 couldnt_check → 465.
    # ⚠️ satisfied / fired / needs_review are UNCHANGED at 21 / 2 / 4. Neither new rule clears on absence,
    # and no existing rule's verdict moved. Any other movement would be a regression.
    # LP-488 ACTIVATED MI-1 (loan-scoped): LF-6T3N's MISMO states NO loan program, so MI-1's applicability
    # predicate is UNDETERMINED → 1 couldnt_check. ⚠️ NOT not_applicable — an unstated program must be
    # surfaced, which is exactly why the program axis is scoped as a PREDICATE and not an outcome. +1 → 466.
    # satisfied / fired / needs_review stay 21 / 2 / 4. LP-488 adds MI-4 (+1) and CO-1 (+1, no property type stated) → 468, then AU-3 (per_document over the
    # 30 docs, like IH-1/IH-2): 26 classified non-AUS docs → not_applicable, 4 unclassified → couldnt_check
    # (an unclassified document cannot be ruled out as AUS findings) → 498.
    # LP-490a ACTIVATED CR-1/CR-4/CR-6/CR-8/CR-10 on `ratify-pending` (ADR-378). LF-6T3N carries NO
    # credit report, so the per-LIABILITY rules (CR-1, CR-6, CR-8) yield no subjects at all and the two
    # per-BORROWER rules (CR-4, CR-10) abstain once per borrower: +4 couldnt_check → 502.
    # ⚠️ satisfied / fired / needs_review are UNCHANGED at 21 / 2 / 4 — five rules activated and no
    # existing verdict moved, and none of the five clears on a missing credit report.
    # LP-491 ACTIVATED TI-1 (per_document over the 30 docs, the IH-1/IH-2 shape): LF-6T3N carries no
    # title commitment, so 26 classified documents → not_applicable and the 4 unclassified → couldnt_check
    # (an unclassified document cannot be ruled out as a commitment). +26 na +4 cc → 532; then TI-2 and TI-6 the same way (+52 na, +8 cc) → 592. LP-492 adds PR-2 (+1 cc: LF-6T3N states no loan purpose, so its
    # applicability predicate is undetermined and is SURFACED rather than skipped) → 593. LP-492 then adds the four per-document appraisal rules the same way (+104 na, +16 cc) → 713. LP-493 adds PC-8 the same way (+25 na, +5 cc) → 743. ⚠️ LP-494 adds CO-3 and CO-4, both LOAN-scoped (one evaluation each, both couldnt_check — property_type is null on every stored file, the gap CO-1 and IH-7 already live with) → 745.
    # ⚠️ LP-495a adds RE-1, DT-6 and LO-2, all per_document over the 30 docs → +90 → 835.
    #   RE-1 / DT-6: 22 classified non-statement docs → not_applicable; 8 couldnt_check — the 4 real
    #   mortgage_statements (each states NO lender_name, the 54/71 corpus gap) plus the 4 'unknown'-type
    #   documents, which cannot be ruled out as statements. ⚠️ THE FAIL-CLOSED DIRECTION WORKING ON THE
    #   FLAGSHIP FIXTURE: LF-6T3N carries FOUR mortgage statements and its MISMO states NO liabilities at
    #   all, and RE-1 abstains on every one rather than reporting four undisclosed mortgages. A matcher
    #   that read 'no stated side' as 'nothing disclosed' would produce 4 false needs_review here.
    #   LO-2: 30 not_applicable — LF-6T3N carries no letter of explanation of any of the 8 LOE types, and
    #   LO-2 never reports a MISSING letter (applicability_expected: false — LO-1's held blocker).
    # ⚠️ satisfied / fired / needs_review UNCHANGED at 21 / 2 / 4. Three rules activated and no existing
    # verdict moved; none of the three clears on an absence. Any other movement would be a regression.
    # ⚠️ satisfied / fired / needs_review UNCHANGED at 21 / 2 / 4 — TI-1 never clears on a missing
    # commitment, which would be a false all-clear on the document that establishes ownership.
    mat = await materialize_tags(
        build_lf6t3n_snapshot(), ai_reasoners=stub_materialization_reasoners()
    )
    results, _ = await evaluate_rules(mat)
    assert len(results) == 835
    assert (
        Counter(r.verdict.value for r in results)
        == {
            "couldnt_check": 275,  # LP-495a +16 — RE-1 x8 and DT-6 x8 (4 lender-less statements + 4 unclassified docs, each)  # LP-494 +2 — CO-3 and CO-4, both abstaining on the null property_type  # +PC-8 x5 (LP-493 — the 4 unclassified docs + the purchase agreement)  # +PR-3/PR-4/PR-5/PR-7 x4 each (LP-492 — the 4 unclassified docs)  # +PR-2 x1 (LP-492 — LF-6T3N states no loan purpose)  # +TI-2 x4 +TI-6 x4 (LP-491 — the 4 unclassified docs, twice over)  # +TI-1 x4 (LP-491 — the 4 unclassified docs; no title commitment on LF-6T3N)  # +CR-4 x2 +CR-10 x2 (LP-490a — per-borrower, no credit report on LF-6T3N)  # +AU-3 x4 (LP-488 — the 4 unclassified docs; no AUS findings on LF-6T3N)  # +CO-1 x1 (LP-488 — LF-6T3N states no property type)  # +MI-4 x1 (LP-488 — same undetermined program predicate as MI-1)  # +MI-1 x1 (LP-488 — LF-6T3N states no loan program)  # +IH-1 x4 (LP-447); +CL-1/CR-13/PR-6 x1 each (LP-485 — no LE / credit
            # report / appraisal on LF-6T3N, so each abstains rather than clearing); +IH-2 x4 + IH-7 x1
            # (LP-487 — 4 unclassified docs that cannot be ruled out as binders, and an unstated property type)
            "not_applicable": 533,  # LP-495a +74 — RE-1 x22 + DT-6 x22 (classified non-statement docs) + LO-2 x30 (no LOE of any type on LF-6T3N)  # +PC-8 x25 (LP-493 — the 25 classified non-contract documents)  # +PR-3/PR-4/PR-5/PR-7 x26 each (LP-492 — the 26 classified non-appraisal docs)  # +TI-2 x26 +TI-6 x26 (LP-491 — the 26 classified non-commitment docs)  # +TI-1 x26 (LP-491 — 26 classified non-commitment documents)  # +AU-3 x26 (LP-488 — 26 classified non-AUS documents)  # +IH-1 x26 (LP-447 — 26 classified non-binder docs; no homeowners policy);
            # +IH-2 x26 (LP-487 — the same 26 classified non-binder docs)
            # ⚠️ LP-508 review: satisfied 23 -> 21, needs_review 2 -> 4. TWO subjects that used to
            # AUTO-SATISFY now route to a human. That is the distrusted-field guard finally reaching the
            # rules it was written for: ID-5 gates on id.borrower_id_expiration, derived from a
            # driver's-licence expiry the extractor hallucinated on docs 146/294, and until the fix the
            # guard resolved only IH-1's tag. This shift IS the fix landing on the real fixture — an
            # auto-asserted "the ID is valid" on a field with a confirmed wrong value is exactly what
            # ADR-377 exists to stop.
            "satisfied": 21,
            "fired": 2,  # UNCHANGED
            "needs_review": 4,
        }
    )
    loan_verdicts = {r.rule_id: r.verdict.value for r in results if r.subject_id == _LOAN}
    assert loan_verdicts == {
        "AS-8": "satisfied",
        "AS-10": "satisfied",
        "PC-7": "satisfied",
        "PC-2": "satisfied",  # LP-407-3 — the contract price matches the 1003 (365000)
        "IH-3": "couldnt_check",  # LP-417 — no homeowners binder on LF-6T3N (an honest absence)
        # LP-487 — IH-7's applicability predicate (property.type) is UNDETERMINED on LF-6T3N, whose MISMO
        # states no property type. ⚠️ couldnt_check, NOT not_applicable: an unstated property type must be
        # surfaced, never silently read as "not a condo".
        "IH-7": "couldnt_check",
        # LP-488 — MI-1's applicability predicate (program.type) is UNDETERMINED: LF-6T3N states no loan
        # program. ⚠️ couldnt_check, never not_applicable — an unstated program is surfaced, not skipped.
        "MI-1": "couldnt_check",
        "MI-4": "couldnt_check",  # LP-488 — the FHA side, same undetermined program predicate
        # LP-492 — PR-2's applicability predicate (loan.purpose) is UNDETERMINED on LF-6T3N, whose MISMO
        # states no purpose. ⚠️ couldnt_check, never not_applicable — an unstated purpose is surfaced.
        "PR-2": "couldnt_check",
        "CO-1": "couldnt_check",  # LP-488 — LF-6T3N states no property type (the condo predicate)
        # ⚠️ LP-494 — the SAME predicate, and the gap is worth naming: property_type is null on EVERY
        # stored file, so the whole condo lane (CO-1, CO-3, CO-4, IH-7) abstains on real data today.
        # That is a data-entry gap, not a rule defect, and it is logged in priya-open-questions.md §16.
        "CO-3": "couldnt_check",  # LP-494 — fidelity presence; same unstated property type
        "CO-4": "couldnt_check",  # LP-494 — date-keyed reserve floor; same unstated property type
        "PC-3": "couldnt_check",  # LP-407-4 — no MISMO subject-property address on LF-6T3N
        # LP-485 — the date-compare family. LF-6T3N has no loan estimate, no credit report and no
        # appraisal, so each abstains. ⚠️ NOT "satisfied": a rule must never clear on a missing document.
        "CL-1": "couldnt_check",
        "CR-13": "couldnt_check",
        "PR-6": "couldnt_check",
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
