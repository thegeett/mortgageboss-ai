"""IH-1 — insurance adequacy: the DWELLING loss-settlement basis (LP-447). Unblocked by LP-446 (which added the
typed-core ``replacement_cost_or_coinsurance_basis`` field the LP-431 STOP was waiting on).

Priya's ruling (ADR-340, effective 2026-03-18) RETIRED the coverage-vs-loan arithmetic and replaced it with a
BASIS check: replacement cost -> satisfied; actual cash value -> fired; null/unreadable -> couldnt_check; no
homeowners policy -> not_applicable. A deterministic normalise-then-compare — NO AI, NO threshold -> activates
(36 -> 37).

These pin: the value vocabulary normaliser (an EXPLICIT allow-list, mixed casing folded) and — the load-bearing
safety — an UNRECOGNISED basis -> couldnt_check, NEVER satisfied (fail closed, D3); the branches (RC satisfied /
ACV fired / unreadable couldnt_check / no binder not_applicable); the anti-conflation (a forms_and_endorsements
row cannot drive the dwelling basis); IH-1's reason is DISTINCT from IH-3's (the boundary); IH-1 is LIVE +
eligible via the no-ai-dependency gate.
"""

from __future__ import annotations

import pytest
from app.verification.eval.fire_path_scenarios import (
    EXPECTED_INS_BASIS_ACV,
    EXPECTED_INS_BASIS_RC,
    build_insurance_acv_snapshot,
    build_insurance_in_force_snapshot,
    build_insurance_replacement_cost_snapshot,
    build_insurance_unreadable_basis_snapshot,
    build_statement_break_snapshot,
)
from app.verification.eval.lf6t3n_fixture import build_lf6t3n_snapshot
from app.verification.rule_engine.activation_bars import is_eligible, load_activation_bars
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import DocumentEntry
from app.verification.tag_materialization.declarations import load_declarations
from app.verification.tag_materialization.derived import (
    _dwelling_settlement_basis,
    _normalize_settlement_basis,
)
from app.verification.tag_materialization.producer import materialize_tags

pytestmark = pytest.mark.anyio

_SPEC = load_rule_spec("IH-1")


def _binder_verdicts(results: list) -> list[Verdict]:
    """The verdicts on the homeowners_insurance binder subject(s) — dropping the not_applicable results the
    per-document rule emits for any non-binder subject."""
    return [r.verdict for r in results if r.verdict is not Verdict.NOT_APPLICABLE]


async def _materialize(snap):
    return await materialize_tags(snap, only_groups=frozenset())  # parsed + derived, NO AI


# --------------------------------------------------------------------------- #
# D3 — the value vocabulary normaliser (an explicit allow-list, NOT a fuzzy matcher)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    ["replacement cost", "Replacement Cost", "REPLACEMENT COST", "  replacement   cost  ", "RCV",
     "guaranteed replacement cost", "Extended Replacement Cost"],
)  # fmt: skip
def test_replacement_cost_phrasings_normalize(raw: str) -> None:
    assert _normalize_settlement_basis(raw) == "replacement_cost"


@pytest.mark.parametrize("raw", ["actual cash value", "Actual Cash Value", "ACV", " acv "])
def test_actual_cash_value_phrasings_normalize(raw: str) -> None:
    assert _normalize_settlement_basis(raw) == "actual_cash_value"


@pytest.mark.parametrize(
    "raw",
    ["see policy declarations", "market value", "agreed value", "functional replacement cost — see form",
     "stated value", "", "replacement cost NOT included"],
)  # fmt: skip
def test_unrecognised_basis_returns_none_fail_closed(raw: str) -> None:
    # THE SAFETY: a term outside the allow-list is None → the recipe abstains to "unknown" → IH-1 couldnt_check.
    # NEVER guessed into replacement_cost. This is the D3 fail-closed contract (an unreadable basis is not a pass).
    assert _normalize_settlement_basis(raw) is None


# --------------------------------------------------------------------------- #
# The recipe — reads ONLY the typed dwelling field, never a non-binder / a list (the anti-conflation)
# --------------------------------------------------------------------------- #
def test_recipe_abstains_for_a_non_binder_subject() -> None:
    doc = DocumentEntry(content_id="x", document_type="pay_stub", belongs_to=None, fields={})
    value, _ = _dwelling_settlement_basis(None, "x", doc)  # type: ignore[arg-type]
    assert value == "unknown"


def test_recipe_reads_the_typed_dwelling_field_only_not_a_list() -> None:
    # The Occidental anti-conflation (ADR-351): the recipe reads replacement_cost_or_coinsurance_basis, and the
    # forms_and_endorsements list is NEVER consulted — a personal-property / ACV-roof endorsement (a list row)
    # cannot be read as the dwelling basis. DocumentEntry.fields carries only the typed field here; the recipe's
    # source is that field alone.
    from app.verification.snapshot.fields import Field, FieldSource

    binder = DocumentEntry(
        content_id="b",
        document_type="homeowners_insurance",
        belongs_to=None,
        fields={
            "replacement_cost_or_coinsurance_basis": Field.present(
                "Replacement Cost", source=FieldSource.EXTRACTED
            )
        },
    )
    value, reason = _dwelling_settlement_basis(None, "b", binder)  # type: ignore[arg-type]
    assert value == "replacement_cost"
    assert "Replacement Cost" in reason  # the stated phrasing is surfaced for the evidence line


# --------------------------------------------------------------------------- #
# The branches, on the real-shaped binder scenarios (materialized end to end)
# --------------------------------------------------------------------------- #
async def test_replacement_cost_binder_satisfies() -> None:
    mat = await _materialize(build_insurance_replacement_cost_snapshot())
    assert _binder_verdicts(evaluate_deterministic_rule(_SPEC, mat)) == [Verdict.SATISFIED]
    # the normaliser folded "Replacement Cost" -> the controlled value
    tag = next(
        t["ins.dwelling_settlement_basis"]
        for t in mat.tags.by_subject.values()
        if "ins.dwelling_settlement_basis" in t
        and str(t["ins.dwelling_settlement_basis"].value) == EXPECTED_INS_BASIS_RC
    )
    assert tag.value == EXPECTED_INS_BASIS_RC


async def test_actual_cash_value_binder_fires() -> None:
    mat = await _materialize(build_insurance_acv_snapshot())
    results = evaluate_deterministic_rule(_SPEC, mat)
    assert _binder_verdicts(results) == [Verdict.FIRED]
    fired = next(r for r in results if r.verdict is Verdict.FIRED)
    assert "actual-cash-value" in fired.reasoning and fired.how_to_fix
    assert (
        EXPECTED_INS_BASIS_ACV
    )  # the expected controlled value is exported for the fixture record


async def test_unrecognised_basis_couldnt_checks_never_satisfied() -> None:
    # THE FAIL-CLOSED PROOF end to end: a binder whose stated basis is not a recognised term → couldnt_check,
    # NEVER satisfied. A false PASS on an unreadable adequacy basis is the harm this guards.
    mat = await _materialize(build_insurance_unreadable_basis_snapshot())
    verdicts = _binder_verdicts(evaluate_deterministic_rule(_SPEC, mat))
    assert verdicts == [Verdict.COULDNT_CHECK]
    assert Verdict.SATISFIED not in verdicts


async def test_binder_with_no_stated_basis_couldnt_checks() -> None:
    # A real binder (the IH-3 in-force scenario) states NO dwelling basis → couldnt_check (never a guessed pass).
    # This is DISTINCT from "no binder at all" (not_applicable, below): a policy exists but its basis is absent.
    mat = await _materialize(build_insurance_in_force_snapshot())
    assert _binder_verdicts(evaluate_deterministic_rule(_SPEC, mat)) == [Verdict.COULDNT_CHECK]


async def test_no_homeowners_policy_is_not_applicable() -> None:
    # Priya's table: no homeowners policy on the file → not_applicable (IH-1 judges an EXISTING policy's
    # adequacy — so no policy = nothing to judge). A file of CLASSIFIED non-binder documents (here two bank
    # statements) → every subject out of scope → NOT_APPLICABLE, never couldnt_check (that is IH-3's missing-
    # binder treatment; IH-1 differs deliberately — it is not IH-1's job to flag a missing policy).
    mat = await _materialize(build_statement_break_snapshot())
    results = evaluate_deterministic_rule(_SPEC, mat)
    assert results and all(r.verdict is Verdict.NOT_APPLICABLE for r in results)


async def test_lf6t3n_has_no_binder_so_no_adequacy_verdict() -> None:
    # LF-6T3N carries no homeowners binder → IH-1 judges no policy's adequacy: NO satisfied and NO fired. Its
    # classified non-binder docs are not_applicable; its UNCLASSIFIED ("unknown"-type) docs couldnt_check (we
    # cannot rule out that an unclassified document is a policy — the honest §8 abstention, mirroring AS-6).
    mat = await _materialize(build_lf6t3n_snapshot())
    verdicts = {r.verdict for r in evaluate_deterministic_rule(_SPEC, mat)}
    assert Verdict.SATISFIED not in verdicts and Verdict.FIRED not in verdicts
    assert verdicts <= {Verdict.NOT_APPLICABLE, Verdict.COULDNT_CHECK}


# --------------------------------------------------------------------------- #
# The IH-3 boundary — both read the binder, their reasons must be provably distinct
# --------------------------------------------------------------------------- #
async def test_ih1_reason_is_distinct_from_ih3() -> None:
    ih3 = load_rule_spec("IH-3")
    # IH-1 talks about the loss-settlement BASIS; IH-3 about the effective DATE / coverage gap. On the SAME
    # adequate binder, IH-1's satisfied reason names the settlement basis and never the effective date.
    mat = await _materialize(build_insurance_replacement_cost_snapshot())
    ih1_reason = next(
        r.reasoning
        for r in evaluate_deterministic_rule(_SPEC, mat)
        if r.verdict is Verdict.SATISFIED
    )
    assert "settle" in ih1_reason.lower() and "basis" in ih1_reason.lower()
    assert "effective date" not in ih1_reason.lower() and "closing" not in ih1_reason.lower()
    # and the two specs read DIFFERENT load-bearing tags (no input overlap)
    ih1_tags = set(_SPEC.deterministic.load_bearing_tags)
    ih3_tags = set(ih3.deterministic.load_bearing_tags)
    assert ih1_tags.isdisjoint(ih3_tags)
    assert ih1_tags == {"ins.dwelling_settlement_basis"}


# --------------------------------------------------------------------------- #
# The producer subject match (anti-structural-death) + LIVE + eligible
# --------------------------------------------------------------------------- #
def test_basis_tag_is_produced_at_the_document_subject_ih1_reads() -> None:
    assert _SPEC.subject_enumeration == "per_document"
    decls = load_declarations()
    assert decls["ins.dwelling_settlement_basis"].subject == "document"


def test_ih1_is_live_and_eligible_no_ai_dependency() -> None:
    assert "IH-1" in ACTIVE_RULE_IDS
    bar = load_activation_bars()["IH-1"]
    assert bar.status == "no-ai-dependency"
    assert bar.load_bearing_ai_tags == () and bar.threshold is None
    assert bar.input_resolves is True and is_eligible(bar) is True
    # the regulatory basis is on record in the rationale (ADR-340) so a future reader can re-check it
    assert "2026-03-18" in bar.rationale
