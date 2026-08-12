"""LP-487 — IH-2 (mortgagee clause) and IH-7 (condo master policy).

⚠️ EVERY VERDICT ASSERTION HERE RUNS THROUGH A REAL RULE EVALUATION — materialize_tags() then
evaluate_rules() — never by calling a recipe or the gate directly. That is the LP-487 standing rule, and
it exists because LP-508 shipped a guard whose own test called ``evaluate_gate`` with tag ids: the
mechanism worked, the WIRING did not, and the guard reached 1 of the 5 rules it claimed to protect. A
green test over an unexercised path is ADR-286/289 at the test layer. The recipe-level tests below are
additions to the end-to-end ones, never substitutes.

⚠️ IH-2 CARRIES A CATALOG EDIT: rule_kinds.csv moved it from `ai_fuzzy_match` to `deterministic_only`
(135 rows unchanged). The kind predates typed extraction — the extractor already reads the clause into
`mortgagee_name` (14/15 bench binders), so the perception step is spent and only a string compare remains.

⚠️ IH-2 CAN NEVER FIRE, BY DESIGN. The corpus's one binder+CD pairing reads "Sistar Mortgage Company"
against "United Wholesale Mortgage": in correspondent deals the CD names the creditor and the clause
names the investor who will hold the loan, so a firing rule would be wrong on a CORRECT file. A mismatch
is needs_review — "confirm" — and a test below pins that no outcome in the spec can produce `fired`.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    build_ih2_clause_matches_snapshot,
    build_ih2_clause_mismatch_snapshot,
    build_ih2_loan_estimate_only_snapshot,
    build_ih2_no_lender_snapshot,
    build_ih7_absent_snapshot,
    build_ih7_adequate_snapshot,
    build_ih7_low_liability_snapshot,
    build_ih7_not_condo_snapshot,
    build_ih7_unreadable_basis_snapshot,
)
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rule_engine.result import Verdict
from app.verification.rules.distrust import distrusted_tag_ids
from app.verification.rules.kinds import EvaluationPath, load_rule_kinds
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import Snapshot
from app.verification.tag_materialization.derived import (
    _CLAUSE_TRUNCATE_MARKERS,
    _CONDO_MIN_LIABILITY_PER_OCCURRENCE,
    _CORPORATE_SUFFIX_TOKENS,
    _MASTER_POLICY_ACV_PHRASES,
    _MASTER_POLICY_RC_PHRASES,
    _lender_names_agree,
    _master_policy_basis,
    _normalise_lender_name,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio


async def _verdicts(builder, rule_id: str) -> list[Verdict]:
    """Run the rule END TO END: parsed + derived materialisation, then the real evaluator."""
    snapshot: Snapshot = await materialize_tags(builder(), only_groups=frozenset())
    evaluations, _tags = await evaluate_rules(snapshot, rule_ids=(rule_id,))
    return [e.verdict for e in evaluations]


async def _one(builder, rule_id: str) -> Verdict:
    """The single verdict on the subject the rule reads, dropping per-document not_applicables."""
    verdicts = await _verdicts(builder, rule_id)
    real = [v for v in verdicts if v is not Verdict.NOT_APPLICABLE]
    assert len(real) == 1, f"{rule_id}: expected one in-scope verdict, got {verdicts}"
    return real[0]


# --------------------------------------------------------------------------- #
# IH-2 — end to end
# --------------------------------------------------------------------------- #
async def test_ih2_clause_naming_the_lender_is_satisfied() -> None:
    """The real corpus variance: "United Wholesale Mortgage, LLC ISAOA" vs the CD's "United Wholesale
    Mortgage, LLC". The ISAOA suffix is an assignment clause, not a different entity."""
    assert await _one(build_ih2_clause_matches_snapshot, "IH-2") is Verdict.SATISFIED


async def test_ih2_mismatch_is_needs_review_never_fired() -> None:
    """⚠️ THE DECISION THIS RULE TURNS ON. Sistar (the CD's creditor) against United Wholesale Mortgage
    (the clause's mortgagee) is the correspondent case — BOTH may be correct. Firing here would be wrong
    on a correct file, repeatedly, and would train a processor to dismiss IH-2."""
    verdict = await _one(build_ih2_clause_mismatch_snapshot, "IH-2")
    assert verdict is Verdict.NEEDS_REVIEW
    assert verdict is not Verdict.FIRED


async def test_ih2_with_no_lender_anywhere_couldnt_checks() -> None:
    """A binder with a mortgagee but no CD and no LE — nothing to compare against. Fail closed: never a
    guessed match."""
    assert await _one(build_ih2_no_lender_snapshot, "IH-2") is Verdict.COULDNT_CHECK


async def test_ih2_falls_back_to_the_loan_estimate() -> None:
    """A file too early to have a Closing Disclosure is still checkable — otherwise IH-2 would be a
    permanent couldnt_check for most of a file's life."""
    assert await _one(build_ih2_loan_estimate_only_snapshot, "IH-2") is Verdict.SATISFIED


async def test_ih2_cannot_fire_from_any_outcome() -> None:
    """The needs_review decision is structural, not incidental to the fixtures above: NO outcome in the
    spec produces `fired`. If someone later adds one, this fails."""
    outcomes = load_rule_spec("IH-2").deterministic.outcomes
    assert Verdict.FIRED.value not in [o.verdict for o in outcomes]
    assert [o.verdict for o in outcomes] == ["satisfied", "needs_review", "couldnt_check"]


# --------------------------------------------------------------------------- #
# IH-2 — the normalisation vocabulary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("clause", "lender"),
    [
        ("United Wholesale Mortgage, LLC ISAOA", "United Wholesale Mortgage, LLC"),
        ("UNITED WHOLESALE MORTGAGE", "United Wholesale Mortgage, LLC"),
        ("United Wholesale Mortgage ISAOA/ATIMA", "United Wholesale Mortgage, LLC"),
        ("UNITED WHOLESALE MORTGAGE LLC", "United Wholesale Mortgage, LLC"),
        ("ROCKET MORTGAGE, LLC.", "Rocket Mortgage, LLC"),
        ("TRUIST BANK ISAOA/ATIMA", "Truist Bank"),
        ("FREEDOM MORTGAGE CORP", "Freedom Mortgage Corporation"),
        ("PARAMOUNT RESIDENTIAL MORTGAGE GROUP, INC.", "Paramount Residential Mortgage Group"),
        # The c/o case: Lakeview is the mortgagee, Loan Care is only its mailing agent.
        ("LAKEVIEW LOAN SERVICING LLC C/O LOAN CARE LLC", "Lakeview Loan Servicing, LLC"),
        # The entity-description case, absorbed by TOKEN-PREFIX matching rather than by a special rule.
        (
            "AMERIHOME MORTGAGE COMPANY, LLC, A DELAWARE LIMITED LIABILITY COMPANY, ISAOA, ATIMA",
            "AmeriHome Mortgage Company, LLC",
        ),
    ],
)
def test_the_real_corpus_mortgagee_forms_all_match(clause: str, lender: str) -> None:
    """Every mortgagee_name the bench corpus actually contains, against the lender it belongs to. These
    are carrier-printed forms, not invented shapes."""
    assert _lender_names_agree(_normalise_lender_name(clause), _normalise_lender_name(lender))


@pytest.mark.parametrize(
    ("clause", "lender"),
    [
        ("United Wholesale Mortgage", "Sistar Mortgage Company"),
        ("FREEDOM MORTGAGE CORP", "United Wholesale Mortgage, LLC"),
        ("First National Bank of Boston", "First National Bank of Chicago"),
    ],
)
def test_genuinely_different_names_do_not_match(clause: str, lender: str) -> None:
    assert not _lender_names_agree(_normalise_lender_name(clause), _normalise_lender_name(lender))


def test_a_name_that_normalises_to_nothing_never_matches() -> None:
    """ "LLC" alone is all suffix — nothing identifying survives. An empty token list must not compare
    equal to another empty one and read as a match."""
    assert _normalise_lender_name("LLC") == []
    assert not _lender_names_agree([], [])
    assert not _lender_names_agree([], ["rocket", "mortgage"])


def test_a_single_token_prefix_is_not_enough() -> None:
    """The tolerance is TWO tokens. "United" alone must not match "United Wholesale Mortgage"."""
    assert not _lender_names_agree(["united"], ["united", "wholesale", "mortgage"])


def test_ih2_vocabulary_matches_the_spec() -> None:
    """The spec's reference_values is where the vocabulary is reviewed; the recipe is what runs. Pinned
    identical so they cannot drift — the CR-12 arrangement."""
    values = load_rule_spec("IH-2").reference_values.values
    assert tuple(values["clause_truncate_markers"].split("|")) == _CLAUSE_TRUNCATE_MARKERS
    assert set(values["corporate_suffix_tokens"].split("|")) == _CORPORATE_SUFFIX_TOKENS
    assert values["min_prefix_tokens_for_match"] == "2"


# --------------------------------------------------------------------------- #
# IH-7 — end to end
# --------------------------------------------------------------------------- #
async def test_ih7_adequate_master_policy_is_satisfied() -> None:
    """Replacement-cost basis + $2M liability. ⚠️ The basis string is the corpus's longest REAL form —
    "REPLACEMENT COST AT AGREED VALUE WITH NO CO-INSURANCE" — which an exact-match vocabulary would
    abstain on."""
    assert await _one(build_ih7_adequate_snapshot, "IH-7") is Verdict.SATISFIED


async def test_ih7_missing_master_policy_fires() -> None:
    """A condo with no master policy is a real, actionable gap — the borrower's walls-in policy does not
    cover the building."""
    assert await _one(build_ih7_absent_snapshot, "IH-7") is Verdict.FIRED


async def test_ih7_liability_below_the_cited_floor_fires() -> None:
    """$500k against B7-4-01's $1M per-occurrence floor (page dated 08/05/2026)."""
    assert await _one(build_ih7_low_liability_snapshot, "IH-7") is Verdict.FIRED


async def test_ih7_is_not_applicable_off_condo() -> None:
    # Uses _verdicts, not _one: _one drops not_applicable, which is the whole assertion here.
    assert await _verdicts(build_ih7_not_condo_snapshot, "IH-7") == [Verdict.NOT_APPLICABLE]


async def test_ih7_unrecognised_basis_couldnt_checks_never_fires() -> None:
    """⚠️ FAIL CLOSED IN BOTH DIRECTIONS. An unrecognised coverage basis is not adequacy AND not
    inadequacy — firing on unfamiliar carrier wording would be as wrong as passing on it."""
    verdict = await _one(build_ih7_unreadable_basis_snapshot, "IH-7")
    assert verdict is Verdict.COULDNT_CHECK
    assert verdict is not Verdict.FIRED


async def test_ih7_condo_scoping_is_an_applicability_predicate() -> None:
    """⚠️ WHY THIS MATTERS: the applicability layer resolves an ABSENT predicate tag to couldnt_check and
    only a DEFINITELY-FALSE one to not_applicable. Had the scoping been an outcome, a file that simply
    does not state its property type would have been skipped silently instead of surfaced."""
    applicability = load_rule_spec("IH-7").deterministic.applicability
    assert applicability is not None
    assert (applicability.tag, applicability.op, applicability.value) == (
        "property.type",
        "eq",
        "condo",
    )


# --------------------------------------------------------------------------- #
# IH-7 — the coverage-basis vocabulary
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "Guaranteed Replacement Cost",
        "Replacement Cost",
        "REPLACEMENT COST AT AGREED VALUE WITH NO CO-INSURANCE",
        "Replacement Cost (RCV) at Agreed Value with no coinsurance; 100% replacement cost for "
        "portion of building insured by Association",
    ],
)  # fmt: skip
def test_the_four_real_master_policy_bases_are_recognised(raw: str) -> None:
    """All four master policies in the bench corpus, verbatim. An EXACT closed-set match would abstain on
    three of them and leave IH-7 permanently couldnt_check — the reason the vocabulary is matched as a
    leading phrase."""
    assert _master_policy_basis(raw) == "replacement_cost"


def test_actual_cash_value_is_recognised_as_inadequate() -> None:
    assert _master_policy_basis("Actual Cash Value") == "actual_cash_value"


def test_a_mixed_basis_abstains_whichever_phrase_leads() -> None:
    """⚠️ ADR-376's protection, kept intact through the widening. A policy stating two bases for two parts
    of the building has neither as ITS basis; calling it actual_cash_value would fire IH-7 on a policy
    that may well be adequate for the structure."""
    assert _master_policy_basis("ACV roof, replacement cost dwelling") is None
    assert _master_policy_basis("Replacement cost dwelling, ACV roof") is None


@pytest.mark.parametrize("raw", ["Special Form", "see schedule", "agreed value", ""])
def test_an_unrecognised_basis_abstains(raw: str) -> None:
    assert _master_policy_basis(raw) is None


def test_ih7_vocabulary_and_threshold_match_the_spec() -> None:
    values = load_rule_spec("IH-7").reference_values.values
    assert tuple(values["replacement_cost_phrases"].split("|")) == _MASTER_POLICY_RC_PHRASES
    assert tuple(values["actual_cash_value_phrases"].split("|")) == _MASTER_POLICY_ACV_PHRASES
    assert values["min_general_liability_per_occurrence"] == str(
        int(_CONDO_MIN_LIABILITY_PER_OCCURRENCE)
    )


# --------------------------------------------------------------------------- #
# The catalog edit, the gate, and the distrust boundary
# --------------------------------------------------------------------------- #
def test_ih2_is_deterministic_in_the_catalog() -> None:
    """The LP-487 catalog edit. `structural` + `exact_match=True` is what forces `deterministic_only`;
    the loader rejects the pair being inconsistent, so both cells are pinned here."""
    rule_kinds = load_rule_kinds()
    assert len(rule_kinds) == 135, "the catalog edit must not change the row count"
    ih2 = rule_kinds["IH-2"]
    assert ih2.evaluation_path is EvaluationPath.DETERMINISTIC_ONLY
    assert ih2.exact_match is True


def test_both_rules_are_live_and_earned_it_through_the_gate() -> None:
    bars = load_activation_bars()
    for rule_id in ("IH-2", "IH-7"):
        assert rule_id in ACTIVE_RULE_IDS
        assert is_eligible(bars[rule_id]), (
            f"{rule_id} is live but does not pass the eligibility gate"
        )


def test_neither_rule_reads_a_distrusted_field() -> None:
    """⚠️ THE OVERLAP CHECK, run through the SPECS rather than by eye. IH-1's basis field is distrusted
    (LP-508) and lives on the same document type as IH-2's mortgagee — so "it's a homeowners field" is
    not a safe way to reason about this. If a future distrust entry ever covers one of these tags, the
    rule silently starts degrading to needs_review and this test says so."""
    distrusted = distrusted_tag_ids()
    for rule_id in ("IH-2", "IH-7"):
        gated = set(load_rule_spec(rule_id).deterministic.gated_tags)
        assert not (gated & set(distrusted)), (
            f"{rule_id} gates on a distrusted tag: {gated & set(distrusted)}"
        )
