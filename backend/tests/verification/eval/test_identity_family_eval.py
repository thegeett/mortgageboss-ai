"""LP-323-ID-C — the IDENTITY family GOLDEN EVAL (the full case matrix).

The LP-317 harness is AS-1/transaction-shaped (FixtureTxn + the four txn.* tags), so it cannot run the
ID rules (consistency over borrower documents, per_document/per_borrower judgment, loan/date
deterministic). This is the dedicated ID golden harness — SAME discipline (finding-level verdict +
tag-level golden labels + provenance + the cost property + the armor), keyless via the Reasoner stub.

EVALUATE, DON'T FIX. Every rule gets both directions (a must-FIRE + a must-not-fire), the fail-closed
cases (absent / unknown / low-confidence — each a DISTINCT reason), a variance case, provenance, a
tag-level check, and the LP-323-ID-A §4 domain edge. N/As are asserted explicitly. Case 12 (gated calc)
is N/A for the whole family (no ID rule reads a calculator). A rule is evaluated by calling its evaluator
directly (activation gates the orchestrator, not the evaluator) — ID-8 is unactivated; ID-5 went live
per-borrower at LP-389-A and is evaluated here at its true borrower/loan subjects.

Known limitation asserted here (NOT a bug to fix): ID-6 UNDER-FIRES on the LP-326 STARTER 1003
field-set (see test_id6_case13_known_underfire_starter_fieldset). The doc records it as the top Priya item.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.deterministic import evaluate_deterministic_rule
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rule_engine.result import RuleEvaluation, Verdict
from app.verification.rules.kinds import RuleKindName, kind_for
from app.verification.rules.specs import RuleSpecNotFound, load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_LF = uuid4()
_B1 = uuid4()
_B2 = uuid4()


# --------------------------------------------------------------------------- #
# Fixture builders (realistic snapshot shapes — documents, borrowers, tags)
# --------------------------------------------------------------------------- #
def _tag(value: object, *, conf: float | None = 0.9, by: TagProducedBy = TagProducedBy.AI) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture-labeled",
        source_facts=("raw",),
        produced_by=by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _parsed(value: object) -> Tag:
    return _tag(value, conf=None, by=TagProducedBy.PARSED)


def _doc(cid: str, *, dtype: str = "doc", borrower=_B1) -> DocumentEntry:
    return DocumentEntry(
        content_id=cid,
        document_type=dtype,
        belongs_to=(BorrowerRef(borrower_id=borrower, name="Sam"),) if borrower else None,
    )


def _snap(*, docs=None, by_subject=None) -> Snapshot:
    return Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(list(docs or [])),
        tags=TagsSection.present(by_subject or {}),
    )


class _Reasoner:
    """A keyless stub for the fuzzy/judgment leg — records whether the AI was invoked (the cost property)."""

    def __init__(self, value: str = "agree", *, conf: float | None = 0.9) -> None:
        self.value = value
        self.conf = conf
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(
            RuleJudgment(self.value, self.conf, "because"), 1, 1, "stub", False
        )


def _verdicts(results: list[RuleEvaluation]) -> list[Verdict]:
    return [r.verdict for r in results]


def _addr_docs(a_type_a: tuple[str, str], b_type_b: tuple[str, str] | None = None, *, borrower=_B1):
    """Documents each stating an id.address_normalized + id.current_address_type (LP-325 co-location)."""
    docs, by_subject = [], {}
    for i, (addr, atype) in enumerate([a_type_a] + ([b_type_b] if b_type_b else [])):
        cid = f"addoc{i}"
        docs.append(_doc(cid, borrower=borrower))
        by_subject[cid] = {
            "id.address_normalized": _tag(addr),
            "id.current_address_type": _tag(atype),
        }
    return docs, by_subject


# --------------------------------------------------------------------------- #
# ID-1 — Borrower name consistency (fuzzy)
# --------------------------------------------------------------------------- #
def _id1(borrower_docs: dict[str, str], reasoner):
    docs = [_doc(cid) for cid in borrower_docs]
    by_subject = {cid: {"id.name_normalized": _tag(name)} for cid, name in borrower_docs.items()}
    return evaluate_consistency_rule(
        load_rule_spec("ID-1"), _snap(docs=docs, by_subject=by_subject), reasoner=reasoner
    )


async def test_id1_case1_must_fire_genuinely_different_names() -> None:
    stub = _Reasoner("disagree")
    r = await _id1({"app": "Robert Smith", "cr": "Michael Jones"}, stub)
    assert _verdicts(r) == [Verdict.FIRED]
    assert (
        r[0].reasoning and "app" in r[0].reasoning and "cr" in r[0].reasoning
    )  # case 9 provenance


async def test_id1_case2_must_not_fire_exact_match_no_ai_call() -> None:
    stub = _Reasoner("disagree")  # would fire if consulted — proves it is NOT consulted
    r = await _id1({"app": "Robert Smith", "cr": "Robert Smith"}, stub)
    assert _verdicts(r) == [Verdict.SATISFIED]
    assert stub.calls == 0  # case 2 + THE COST PROPERTY: an exact match makes NO AI call


async def test_id1_case5_absent_tag_couldnt_check() -> None:
    # Only one source has a name → <2 stated instances → couldnt_check (a single source is not agreement).
    r = await _id1({"app": "Robert Smith"}, _Reasoner())
    assert _verdicts(r) == [Verdict.COULDNT_CHECK] and "needs at least two" in r[0].reasoning


async def test_id1_case6_unknown_value_excluded_like_absent_gate_owns_distinctness() -> None:
    # CASE 6 — OBSERVATION (not a bug): a CONSISTENCY rule's gather EXCLUDES an "unknown"-valued source
    # (absent≠unknown≠empty — an unknown name is not a value to compare), so an unknown value COLLAPSES
    # into the SAME "nothing to compare" couldnt_check as an absent tag. The distinct-reason guarantee
    # (unknown → a reason distinct from absent) is a GATE property — demonstrated on the deterministic
    # ID-6 (test_id6_case6_unknown_distinct_reason_from_absent) and the judgment ID-8. Documented.
    r = await _id1({"app": "unknown", "cr": "Robert Smith"}, _Reasoner())
    assert _verdicts(r) == [Verdict.COULDNT_CHECK] and "needs at least two" in r[0].reasoning


async def test_id1_case7_low_confidence_tag_needs_review() -> None:
    docs = [_doc("app"), _doc("cr")]
    by_subject = {
        "app": {"id.name_normalized": _tag("Robert Smith", conf=0.2)},  # below floor 0.5
        "cr": {"id.name_normalized": _tag("Robert Smith", conf=0.9)},
    }
    r = await evaluate_consistency_rule(
        load_rule_spec("ID-1"), _snap(docs=docs, by_subject=by_subject), reasoner=_Reasoner()
    )
    assert _verdicts(r) == [Verdict.NEEDS_REVIEW]  # NOT confident-satisfied


async def test_id1_case8_and_13_nickname_and_maiden_variance_ai_agrees() -> None:
    # case 8 variance + case 13 DOMAIN EDGE (married-between-docs: maiden vs married surname) — exact
    # differs → the AI judges benign → satisfied, ratification-pending (a real model would use the
    # name-change signal; the harness proves the fuzzy leg is reached and its verdict honored).
    stub = _Reasoner("agree")
    r = await _id1({"app": "Robert Smith", "dl": "Bob Smith"}, stub)  # nickname
    assert _verdicts(r) == [Verdict.SATISFIED] and stub.calls == 1 and r[0].ratification_pending

    stub2 = _Reasoner("agree")
    r2 = await _id1({"dl": "Jane Doe", "app": "Jane Smith"}, stub2)  # maiden→married (case 13)
    assert _verdicts(r2) == [Verdict.SATISFIED] and stub2.calls == 1


def test_id1_case10_tag_level_name_normalized_labels() -> None:
    # TAG LEVEL (case 10): the id.name_normalized tag values are the golden labels the rule rests on —
    # a systematically wrong name tag must be caught here, independent of the finding.
    by_subject = {"app": {"id.name_normalized": _tag("Robert Smith")}}
    tag = by_subject["app"]["id.name_normalized"]
    assert tag.value == "Robert Smith" and tag.produced_by is TagProducedBy.AI


# ID-1 cases 3/4 (boundary) + 11 (armor) + 12 (calc) = N/A (no threshold, not a judgment, no calc).


# --------------------------------------------------------------------------- #
# ID-2 — SSN consistency (exact) — extend the LP-325 tests to the full matrix
# --------------------------------------------------------------------------- #
async def _id2(hashes: dict[str, str | None]):
    # id.ssn_hash is a PARSED per-document tag; a null/blank SSN source produces NO tag (absent≠empty),
    # so it is EXCLUDED from the compare. Distinct SSN strings → distinct hashes → a discrepancy.
    docs, by_subject = [], {}
    for cid, h in hashes.items():
        docs.append(_doc(cid))
        if h is not None:
            by_subject[cid] = {"id.ssn_hash": _parsed(f"hash:{h}")}
    return await evaluate_consistency_rule(
        load_rule_spec("ID-2"), _snap(docs=docs, by_subject=by_subject)
    )


async def test_id2_case1_must_fire_differing_ssn() -> None:
    r = await _id2({"app": "111-22-3333", "cr": "999-88-7777"})
    assert _verdicts(r) == [Verdict.FIRED] and r[0].reasoning  # case 1 + case 9


async def test_id2_case2_must_not_fire_matching() -> None:
    assert _verdicts(await _id2({"app": "111-22-3333", "cr": "111-22-3333"})) == [Verdict.SATISFIED]


async def test_id2_case5_and_13_null_hash_excluded_then_lt2_couldnt_check() -> None:
    # DOMAIN EDGE: a null/blank hash source is EXCLUDED (not a false match); <2 remaining → couldnt_check.
    r = await _id2({"app": "111-22-3333", "cr": None})
    assert _verdicts(r) == [Verdict.COULDNT_CHECK] and "needs at least two" in r[0].reasoning


async def test_id2_case13_itin_vs_ssn_fires() -> None:
    # DOMAIN EDGE: ITIN on one doc, SSN on another (synthetic-identity signal) → differing hashes → FIRED.
    r = await _id2({"1003": "900-70-0000", "credit": "111-22-3333"})  # 9xx = ITIN range
    assert _verdicts(r) == [Verdict.FIRED]


# ID-2 cases 3/4/7-boundary/11/12 = N/A (exact, no threshold, no AI, not judgment, no calc). Case 6
# (unknown value) and 7 (low-conf) share the consistency gate path proven in ID-1/ID-3.


# --------------------------------------------------------------------------- #
# ID-3 — DOB consistency (exact + date normalization)
# --------------------------------------------------------------------------- #
async def _id3(dobs: dict[str, str]):
    docs = [_doc(cid) for cid in dobs]
    by_subject = {cid: {"id.dob": _parsed(v)} for cid, v in dobs.items()}
    return await evaluate_consistency_rule(
        load_rule_spec("ID-3"), _snap(docs=docs, by_subject=by_subject)
    )


async def test_id3_case1_must_fire_different_dob() -> None:
    assert _verdicts(await _id3({"app": "1985-03-04", "cr": "1986-03-04"})) == [Verdict.FIRED]


async def test_id3_case2_and_8_format_variance_normalized_satisfied() -> None:
    # case 8 variance: 03/04/1985 vs 1985-03-04 → the declared `date` normalizer canonicalizes → satisfied.
    assert _verdicts(await _id3({"app": "03/04/1985", "cr": "1985-03-04"})) == [Verdict.SATISFIED]


async def test_id3_case13_ambiguous_date_not_silently_equal() -> None:
    # DOMAIN EDGE (LP-328): a slash-date coerce_date can't resolve ("13/04/1985" — 13 is not a US
    # month) is left VERBATIM and compared LITERALLY, so a GENUINE mismatch is never masked. Here the
    # other source is a DIFFERENT date (14 April), so the literal compare correctly FIRES.
    r = await _id3({"app": "13/04/1985", "cr": "1985-04-14"})
    assert _verdicts(r) == [Verdict.FIRED]
    # KNOWN coerce_date limitation (LP-323-ID-B review, accepted): the SAME date written DD/MM vs ISO
    # ("13/04/1985" vs "1985-04-13") would ALSO literal-compare as different → a FALSE discrepancy. It
    # is fail-SAFE (surfaced for review, never a silent false match) and pending DD/MM parsing — NOT
    # asserted as correct here (an eval golden label must not encode a false-positive).


def test_id3_case3_4_11_12_are_na() -> None:
    # Explicit N/A: no numeric threshold (3/4), not a judgment (11), no calc (12).
    assert load_rule_spec("ID-3").consistency.compare_mode == "exact"


# --------------------------------------------------------------------------- #
# ID-4 — Current address consistency (fuzzy + residence filter)
# --------------------------------------------------------------------------- #
async def test_id4_case1_must_fire_different_residence() -> None:
    stub = _Reasoner("disagree")
    docs, by_subject = _addr_docs(("123 Main St", "residence"), ("500 Oak Ave", "residence"))
    r = await evaluate_consistency_rule(
        load_rule_spec("ID-4"), _snap(docs=docs, by_subject=by_subject), reasoner=stub
    )
    assert _verdicts(r) == [Verdict.FIRED] and r[0].reasoning


async def test_id4_case2_exact_match_no_ai_call() -> None:
    stub = _Reasoner("disagree")
    docs, by_subject = _addr_docs(("123 Main St", "residence"), ("123 Main St", "residence"))
    r = await evaluate_consistency_rule(
        load_rule_spec("ID-4"), _snap(docs=docs, by_subject=by_subject), reasoner=stub
    )
    assert _verdicts(r) == [Verdict.SATISFIED] and stub.calls == 0  # COST property


async def test_id4_case13_mailing_only_couldnt_check_not_discrepancy() -> None:
    # DOMAIN EDGE: the DL is a PO-box/mailing; only ONE residence remains → couldnt_check, NOT a discrepancy.
    stub = _Reasoner("disagree")
    docs, by_subject = _addr_docs(("123 Main St", "residence"), ("PO Box 9", "mailing"))
    r = await evaluate_consistency_rule(
        load_rule_spec("ID-4"), _snap(docs=docs, by_subject=by_subject), reasoner=stub
    )
    assert (
        _verdicts(r) == [Verdict.COULDNT_CHECK]
        and stub.calls == 0
        and "residence" in r[0].reasoning
    )


async def test_id4_case8_benign_variance_ai_agrees_ratification_pending() -> None:
    stub = _Reasoner("agree")
    docs, by_subject = _addr_docs(
        ("123 N Main St Apt 4", "residence"), ("123 North Main Street #4", "residence")
    )
    r = await evaluate_consistency_rule(
        load_rule_spec("ID-4"), _snap(docs=docs, by_subject=by_subject), reasoner=stub
    )
    assert _verdicts(r) == [Verdict.SATISFIED] and stub.calls == 1 and r[0].ratification_pending


# --------------------------------------------------------------------------- #
# ID-5 — ID expiration, PER BORROWER (LP-389-A) — evaluated directly at the TRUE subjects
# --------------------------------------------------------------------------- #
def _id5(*, expiration: str | None, closing: str = "2026-05-01"):
    # LP-389-A: the borrower's OWN id.borrower_id_expiration under the borrower subject + the loan's one
    # contract.loan_closing_date under "loan", with a belongs_to document so the per_borrower enumerator
    # yields the borrower. NOT the pre-fix fiction that placed both tags at "loan" (where ID-5 wrongly read).
    by_subject: dict = {"loan": {"contract.loan_closing_date": _parsed(closing)}}
    if expiration is not None:
        by_subject[str(_B1)] = {"id.borrower_id_expiration": _parsed(expiration)}
    docs = [_doc("dl", dtype="drivers_license", borrower=_B1)]
    return evaluate_deterministic_rule(
        load_rule_spec("ID-5"), _snap(docs=docs, by_subject=by_subject)
    )


def test_id5_case1_must_fire_expired_before_closing() -> None:
    (r,) = _id5(expiration="2026-04-30")
    assert r.verdict is Verdict.FIRED and "2026-04-30" in r.reasoning


def test_id5_case2_must_not_fire_valid() -> None:
    assert _id5(expiration="2026-12-31")[0].verdict is Verdict.SATISFIED


def test_id5_case3_4_boundary_equals_closing_ge_default() -> None:
    # BOUNDARY (case 3/4): expiration == closing → the encoded `>=` default → satisfied (PRIYA-PENDING).
    assert _id5(expiration="2026-05-01")[0].verdict is Verdict.SATISFIED


def test_id5_case5_and_13_absent_expiration_couldnt_check_not_fired() -> None:
    # DOMAIN EDGE: a non-expiring state ID (no expiration) → couldnt_check, NOT fired.
    (r,) = _id5(expiration=None)
    assert r.verdict is Verdict.COULDNT_CHECK and "ID expiration" in r.reasoning


def test_id5_case13_closing_slip_expires_at_closing() -> None:
    # DOMAIN EDGE: valid at application, the closing date SLIPPED past expiration → fires at closing.
    (r,) = _id5(expiration="2026-04-30", closing="2026-06-15")
    assert r.verdict is Verdict.FIRED


# --------------------------------------------------------------------------- #
# ID-6 — 1003 completeness (deterministic, loan)
# --------------------------------------------------------------------------- #
def _id6(value: str | None):
    tags = (
        {"loan": {"id.app_required_fields_present": _tag(value, by=TagProducedBy.DERIVED)}}
        if value
        else {}
    )
    return evaluate_deterministic_rule(load_rule_spec("ID-6"), _snap(by_subject=tags))


def test_id6_case1_must_fire_incomplete() -> None:
    (r,) = _id6("incomplete + list")
    assert r.verdict is Verdict.FIRED and r.reasoning


def test_id6_case2_must_not_fire_complete() -> None:
    assert _id6("complete")[0].verdict is Verdict.SATISFIED


def test_id6_case5_absent_couldnt_check() -> None:
    (r,) = _id6(None)
    assert r.verdict is Verdict.COULDNT_CHECK and "could not be found" in r.reasoning


def test_id6_case6_unknown_distinct_reason_from_absent() -> None:
    # CASE 6 (the DISTINCT-reason property, at the GATE): an "unknown" gated tag → couldnt_check with a
    # reason DISTINCT from absent (case 5). This is where the family's absent≠unknown contract lives —
    # a consistency rule collapses them (test_id1_case6), the gate keeps them distinct.
    (unknown,) = _id6("unknown")
    (absent,) = _id6(None)
    assert unknown.verdict is Verdict.COULDNT_CHECK and "could not be read" in unknown.reasoning
    assert absent.verdict is Verdict.COULDNT_CHECK and "could not be found" in absent.reasoning
    assert unknown.reasoning != absent.reasoning  # case 6 ≠ case 5


def test_id6_case13_known_underfire_starter_fieldset() -> None:
    # KNOWN LIMITATION captured for REAL (not a bug to fix here): id.app_required_fields_present is
    # DERIVED from LP-326's STARTER field set (borrower name, SSN, loan amount, property address) — it
    # does NOT include the Declarations section / co-borrower fields. So a 1003 that HAS the four
    # starter fields but is MISSING Declarations DERIVES "complete" → ID-6 SATISFIED = a false-green.
    # This runs the ACTUAL derived recipe over a Declarations-less MISMO (not a hardcoded value), so the
    # eval genuinely captures the under-fire; the authoritative field set is Priya's (top Priya item).
    from app.verification.snapshot.fields import Field, FieldSource
    from app.verification.snapshot.model import MismoSection
    from app.verification.tag_materialization.declarations import load_declarations
    from app.verification.tag_materialization.derived import produce_derived_tags

    starter = {
        key: Field.present("x", source=FieldSource.EXTRACTED)
        for key in ("borrower.1.name", "borrower.1.ssn", "loan.amount", "property.address")
    }  # the 4 starter fields present; NO Declarations / co-borrower field
    snap = Snapshot(
        loan_file_id=_LF,
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present([]),
        tags=TagsSection.present({}),
        mismo=MismoSection.present(starter),
    )
    decl = load_declarations()["id.app_required_fields_present"]
    derived_value = produce_derived_tags(decl, snap)["loan"]["id.app_required_fields_present"].value
    assert (
        derived_value == "complete"
    )  # THE UNDER-FIRE: a Declarations-less 1003 derives "complete"
    assert _id6(derived_value)[0].verdict is Verdict.SATISFIED  # → ID-6 wrongly satisfies it


# --------------------------------------------------------------------------- #
# ID-7 — Marital/title consistency (deterministic, per_document, title-scoped, expected)
# --------------------------------------------------------------------------- #
def _id7(docs_types: dict[str, tuple[str, str | None]]):
    """docs_types = {content_id: (document_type, title_vesting_consistent | None)}."""
    docs, by_subject = [], {}
    for cid, (dtype, tv) in docs_types.items():
        docs.append(_doc(cid, dtype=dtype))
        if tv is not None:
            by_subject[cid] = {"id.title_vesting_consistent": _tag(tv)}
    return evaluate_deterministic_rule(
        load_rule_spec("ID-7"), _snap(docs=docs, by_subject=by_subject)
    )


def test_id7_case1_must_fire_inconsistent_vesting() -> None:
    (r,) = _id7({"title": ("title_commitment", "no")})
    assert r.verdict is Verdict.FIRED and r.reasoning


def test_id7_case2_must_not_fire_consistent() -> None:
    assert _id7({"title": ("title_commitment", "yes")})[0].verdict is Verdict.SATISFIED


def test_id7_case6_title_present_unknown_couldnt_check() -> None:
    (r,) = _id7({"title": ("title_commitment", "unknown")})
    assert r.verdict is Verdict.COULDNT_CHECK  # in-scope but degraded — Tab 1


def test_id7_case13_scope_and_absent_document() -> None:
    # DOMAIN EDGE: a non-title doc alongside a title → paystub not_applicable, title evaluated.
    by = {
        r.subject_id: r.verdict
        for r in _id7({"pay": ("paystub", None), "title": ("title_commitment", "yes")})
    }
    assert by["pay"] is Verdict.NOT_APPLICABLE and by["title"] is Verdict.SATISFIED
    # DOMAIN EDGE (LP-330): a file with NO title commitment (title is EXPECTED) → couldnt_check, Tab 1 BLOCKS.
    (miss,) = _id7({"pay": ("paystub", None), "w2": ("w2", None)})
    assert miss.verdict is Verdict.COULDNT_CHECK and "title commitment" in miss.reasoning


# --------------------------------------------------------------------------- #
# ID-8 — Citizenship eligibility (per-borrower judgment) — UNACTIVATED, evaluated directly
# --------------------------------------------------------------------------- #
async def _id8(borrower_citizenship: dict, program: str | None, reasoner):
    docs = [_doc(f"d{i}", borrower=b) for i, b in enumerate(borrower_citizenship)]
    by_subject = {
        str(b): ({"id.citizenship": _parsed(c)} if c is not None else {})
        for b, c in borrower_citizenship.items()
    }
    if program:
        by_subject["loan"] = {"program.type": _parsed(program)}
    return await evaluate_judgment_rule(
        load_rule_spec("ID-8"), _snap(docs=docs, by_subject=by_subject), reasoner=reasoner
    )


async def test_id8_case1_2_11_fire_clean_and_armor() -> None:
    stub = _Reasoner("no")  # ineligible
    evals = await _id8({_B1: "non_permanent"}, "conventional", stub)
    assert evals[0].evaluation.verdict is Verdict.NEEDS_REVIEW  # a judgment never auto-fires
    assert evals[
        0
    ].evaluation.ratification_pending  # CASE 11 ARMOR — every verdict ratification-pending

    stub2 = _Reasoner("yes")  # eligible
    evals2 = await _id8({_B1: "us_citizen"}, "conventional", stub2)
    assert evals2[0].evaluation.ratification_pending  # even a clean 'yes' is ratification-pending


async def test_id8_case13_per_borrower_isolation_one_absent_couldnt_check() -> None:
    # DOMAIN EDGE (LP-331): borrower B1's citizenship absent → B1 couldnt_check; B2 still evaluates.
    stub = _Reasoner("yes")
    evals = {
        e.evaluation.subject_id: e.evaluation
        for e in await _id8({_B1: None, _B2: "us_citizen"}, "conventional", stub)
    }
    assert (
        evals[str(_B1)].verdict is Verdict.COULDNT_CHECK
        and "citizenship" in evals[str(_B1)].reasoning
    )
    assert evals[str(_B2)].verdict is Verdict.NEEDS_REVIEW  # B2 unaffected + provenance
    assert evals[str(_B2)].reasoning and stub.calls == 1  # gate-before-AI: no call for gated B1


# --------------------------------------------------------------------------- #
# ID-9 — POA acceptability (per-document judgment, POA-scoped)
# --------------------------------------------------------------------------- #
async def _id9(docs_types: dict[str, tuple[str, str | None]], reasoner):
    docs, by_subject = [], {}
    for cid, (dtype, poa) in docs_types.items():
        docs.append(_doc(cid, dtype=dtype))
        if poa is not None:
            by_subject[cid] = {"id.poa_present_and_acceptable": _tag(poa)}
    return await evaluate_judgment_rule(
        load_rule_spec("ID-9"), _snap(docs=docs, by_subject=by_subject), reasoner=reasoner
    )


async def test_id9_case1_2_11_and_scope() -> None:
    stub = _Reasoner("no")  # unacceptable POA (case 1 must-fire → needs_review)
    (ev,) = await _id9({"poa": ("power_of_attorney", "no")}, stub)
    assert (
        ev.evaluation.verdict is Verdict.NEEDS_REVIEW and ev.evaluation.ratification_pending
    )  # armor
    assert ev.evaluation.reasoning  # case 9 provenance

    # SCOPE: a W-2 is not in scope → not_applicable (Tab 4), no AI call.
    stub2 = _Reasoner("no")
    (na,) = await _id9({"w2": ("w2", None)}, stub2)
    assert na.evaluation.verdict is Verdict.NOT_APPLICABLE and stub2.calls == 0


async def test_id9_case13_interested_party_and_dated_after_note() -> None:
    # DOMAIN EDGE: the acceptability tag encodes the interested-party / dated-after-note failures; the
    # rule surfaces "no" → needs_review, ratification-pending (the fraud/acceptability signal blocks).
    stub = _Reasoner("no")
    (ev,) = await _id9({"poa": ("power_of_attorney", "no")}, stub)
    assert ev.evaluation.verdict is Verdict.NEEDS_REVIEW and ev.evaluation.ratification_pending


# --------------------------------------------------------------------------- #
# ID-10 — OFAC / sanctions — OUT OF SCOPE (Tab 4, never couldnt_check)
# --------------------------------------------------------------------------- #
def test_id10_is_out_of_scope_not_applicable_no_spec() -> None:
    rk = kind_for("ID-10")
    assert (
        rk is not None and rk.kind is RuleKindName.OUT_OF_SCOPE
    )  # → not_applicable, never couldnt_check
    with pytest.raises(RuleSpecNotFound):
        load_rule_spec("ID-10")  # no spec, no tags — the registry evaluates nothing (Tab 4)


# --------------------------------------------------------------------------- #
# BOTH-DIRECTIONS GUARD — every in-scope ID rule has a credible must-FIRE case (no eval fatigue)
# --------------------------------------------------------------------------- #
def test_every_in_scope_id_rule_has_a_must_fire_case_in_this_module() -> None:
    # A rule with only a doesn't-fire case is NOT evaluated. This asserts an actual must-fire test
    # FUNCTION exists for each in-scope rule — checked against the module's live callables (NOT a
    # source-string grep, which would trivially match this list itself and could never fail).
    defined = {
        name for name, obj in globals().items() if name.startswith("test_") and callable(obj)
    }
    for rid, prefix in [
        ("ID-1", "test_id1_case1_must_fire"),
        ("ID-2", "test_id2_case1_must_fire"),
        ("ID-3", "test_id3_case1_must_fire"),
        ("ID-4", "test_id4_case1_must_fire"),
        ("ID-5", "test_id5_case1_must_fire"),
        ("ID-6", "test_id6_case1_must_fire"),
        ("ID-7", "test_id7_case1_must_fire"),
        ("ID-8", "test_id8_case1_2_11"),
        ("ID-9", "test_id9_case1_2_11"),
    ]:
        assert any(name.startswith(prefix) for name in defined), (
            f"{rid} is missing a must-fire case — a rule with no fire case is NOT evaluated"
        )
