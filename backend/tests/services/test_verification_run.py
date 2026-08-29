"""The verification orchestrator (LP-321) — full run, partial-snapshot semantics, caching.

Keyless (stub reasoners). Proves: a full raw→A→B→rules→findings run end to end; dependency order;
partial-snapshot graceful degradation (a stage failure never fails the run — affected rules
couldnt_check WITH REASON, others still run); the cache-by-fingerprint reuse; and degradation
visibility. DB-backed via the rollback fixture.
"""

from __future__ import annotations

from collections import Counter
from uuid import UUID, uuid4

from app.ai.client import AIClientError
from app.models import Company, EvaluationOutcome
from app.services.loan_files import create_loan_file
from app.services.verification_run import (
    Reasoners,
    TagCaches,
    _merge_judgment_tags,
    _required_ai_groups,
    _retire_eligible_rules,
    _scan_tag_degradations,
    run_verification,
)
from app.verification.eval.cases import EvalCase, FixtureTxn
from app.verification.eval.harness import _build_snapshot, load_fixture_snapshot
from app.verification.eval.stubs import (
    StubStageAReasoner,
    StubStageBReasoner,
    stub_materialization_reasoners,
)
from app.verification.rule_engine.oc2 import JUDGMENT_TAG, LOAN_SUBJECT
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from sqlalchemy.ext.asyncio import AsyncSession

# A large UNSOURCED transfer (fires) + a large VERIFIED transfer with its matching debit (satisfied).
_UNSOURCED = FixtureTxn(
    key="TRANSFER INBOUND NO ORIGIN",
    amount="40000.00",
    date="2026-05-10",
    transaction_type="transfer",
    is_money_in="in",
    apparent_category="transfer_own",
    has_source="no",
    expect_strength="none",
    expect_outcome="open",
)
_VERIFIED_IN = FixtureTxn(
    key="ONLINE TRANSFER FROM SAVINGS",
    amount="60000.00",
    date="2026-05-12",
    transaction_type="transfer",
    is_money_in="in",
    apparent_category="transfer_own",
    has_source="yes",
    cite_candidate=True,
    expect_strength="verified",
    expect_outcome="satisfied",
)
_VERIFIED_DEBIT = FixtureTxn(
    key="ONLINE TRANSFER TO CHECKING",
    amount="60000.00",
    date="2026-05-11",
    transaction_type="transfer",
    is_money_in="out",
    apparent_category="transfer_own",
)
_TXNS = (_UNSOURCED, _VERIFIED_IN, _VERIFIED_DEBIT)


def _snapshot(
    txns: tuple[FixtureTxn, ...], loan_file_id: UUID, *, income: str = "10000"
) -> Snapshot:
    snap = _build_snapshot(
        EvalCase(case_id="orch", title="orchestrator", level="finding", txns=txns, income=income)
    )
    return snap.model_copy(update={"loan_file_id": loan_file_id, "run_id": uuid4()})


async def _loan_file_id(db: AsyncSession) -> UUID:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    return lf.id


async def _no_snapshot_findings(_payload: str, _keys: frozenset[str] = frozenset()) -> list:
    """LP-586 — the snapshot cross-source pass, stubbed to find nothing.

    Every AI seam in this run is injected for the same reason: a keyless test would otherwise make a
    real call, get an AuthenticationError, and DEGRADE the run — which is how the missing seam here
    was caught (`assert not run.degraded` failed with "not refreshed: AuthenticationError").
    """
    return []


def _reasoners(txns: tuple[FixtureTxn, ...], *, oc2: object = None) -> Reasoners:
    return Reasoners(
        stage_a=StubStageAReasoner(txns),
        stage_b=StubStageBReasoner(txns),
        oc2=oc2,  # type: ignore[arg-type]
        materialization=stub_materialization_reasoners(),
        snapshot_findings=_no_snapshot_findings,
    )


class _CountingStageA(StubStageAReasoner):
    def __init__(self, txns: tuple[FixtureTxn, ...]) -> None:
        super().__init__(txns)
        self.calls = 0

    async def __call__(self, context_json: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await super().__call__(context_json)


# --------------------------------------------------------------------------- #
# Full run + dependency order
# --------------------------------------------------------------------------- #


async def test_full_run_end_to_end(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    snap = _snapshot(_TXNS, lf_id)
    run = await run_verification(
        db_session,
        run_id=snap.run_id,
        loan_file_id=lf_id,
        base_snapshot=snap,
        reasoners=_reasoners(_TXNS),
    )
    # The pipeline flowed all the way to persisted findings.
    outcomes = {f.rule_id: f for f in run.findings if f.rule_id == "AS-1"}
    by_subject = {f.subject_key: f.evaluation_outcome for f in run.findings if f.rule_id == "AS-1"}
    # AS-1: the unsourced large deposit FIRED (open); the verified one is satisfied.
    assert EvaluationOutcome.OPEN in by_subject.values()
    assert EvaluationOutcome.SATISFIED in by_subject.values()
    assert outcomes  # AS-1 produced findings
    # Reproducibility metadata recorded.
    assert run.model and run.vocab_version == snap.snapshot_version
    assert not run.degraded  # a clean run


async def test_dependency_order_stage_b_sees_stage_a_output(db_session: AsyncSession) -> None:
    # Stage B only produces has_identified_source for a deposit Stage A tagged money-in — so its
    # presence proves B ran AFTER A over A's output; findings prove rules ran after tags.
    lf_id = await _loan_file_id(db_session)
    snap = _snapshot(_TXNS, lf_id)
    run = await run_verification(
        db_session,
        run_id=snap.run_id,
        loan_file_id=lf_id,
        base_snapshot=snap,
        reasoners=_reasoners(_TXNS),
    )
    deposit = next(
        t
        for e in run.snapshot.documents.entries
        for t in (e.transactions or ())
        if t.description.value == "ONLINE TRANSFER FROM SAVINGS"
    )
    tags = run.snapshot.tags.by_subject[deposit.content_id]
    assert "txn.is_money_in" in tags  # Stage A
    assert "txn.has_identified_source" in tags  # Stage B (consumed A's is_money_in)
    assert "txn.source_strength" in tags  # Stage B derived (LP-314a)
    assert run.findings  # rules + findings ran after tags


# --------------------------------------------------------------------------- #
# Partial-snapshot semantics — a stage failure never fails the run
# --------------------------------------------------------------------------- #


async def test_stage_b_per_call_failure_degrades_gracefully(db_session: AsyncSession) -> None:
    # Stage B's reasoner raises AIClientError on every deposit → the producer fails CLOSED per call
    # (has_identified_source becomes unknown-with-reason), NOT a crash.
    lf_id = await _loan_file_id(db_session)
    snap = _snapshot(_TXNS, lf_id)

    class _FailingStageB:
        async def __call__(self, context_json: str) -> object:
            raise AIClientError("stage B down")

    run = await run_verification(
        db_session,
        run_id=snap.run_id,
        loan_file_id=lf_id,
        base_snapshot=snap,
        reasoners=Reasoners(
            stage_a=StubStageAReasoner(_TXNS),
            stage_b=_FailingStageB(),
            materialization=stub_materialization_reasoners(),
        ),  # type: ignore[arg-type]
    )
    # The run COMPLETED with a coherent result set.
    as1 = [f for f in run.findings if f.rule_id == "AS-1"]
    # Money-in deposits with no source tag → couldnt_check WITH a reason (the gate), not a fabricated
    # fired/satisfied.
    assert all(f.evaluation_outcome is EvaluationOutcome.COULDNT_CHECK for f in as1)
    assert as1  # they were evaluated (not skipped)
    # A rule that does NOT depend on the failed Stage-B tags STILL RAN — OC-2 (occupancy) evaluated.
    assert any(f.rule_id == "OC-2" for f in run.findings)
    # Degradation is VISIBLE (which tags degraded + why), not hidden.
    assert run.degraded
    assert any("failed" in d.reason.lower() for d in run.degradations)


async def test_stage_b_wholesale_exception_is_backstopped(db_session: AsyncSession) -> None:
    # A NON-AIClientError from Stage B escapes the producer's per-call catch → the orchestrator
    # backstop degrades the whole stage (keeps the pre-B snapshot), never crashing the run.
    lf_id = await _loan_file_id(db_session)
    snap = _snapshot(_TXNS, lf_id)

    class _ExplodingStageB:
        async def __call__(self, context_json: str) -> object:
            raise ValueError("boom")

    run = await run_verification(
        db_session,
        run_id=snap.run_id,
        loan_file_id=lf_id,
        base_snapshot=snap,
        reasoners=Reasoners(
            stage_a=StubStageAReasoner(_TXNS),
            stage_b=_ExplodingStageB(),
            materialization=stub_materialization_reasoners(),
        ),  # type: ignore[arg-type]
    )
    assert any(d.stage == "stage_b" and "ValueError" in d.reason for d in run.degradations)
    # Stage A tags survived; Stage B tags are absent → AS-1 couldnt_check (gate on absent has_source).
    deposit = next(
        t
        for e in run.snapshot.documents.entries
        for t in (e.transactions or ())
        if t.description.value == "TRANSFER INBOUND NO ORIGIN"
    )
    assert "txn.has_identified_source" not in run.snapshot.tags.by_subject[deposit.content_id]
    as1 = [f for f in run.findings if f.rule_id == "AS-1"]
    assert all(f.evaluation_outcome is EvaluationOutcome.COULDNT_CHECK for f in as1)


# --------------------------------------------------------------------------- #
# Caching — reuse frozen tags for unchanged inputs
# --------------------------------------------------------------------------- #


async def test_rerun_with_unchanged_inputs_reuses_tags(db_session: AsyncSession) -> None:
    # The cache is keyed by content fingerprint (loan-file-agnostic), so a fresh loan file per run
    # isolates finding persistence (cross-run finding reconciliation is LP-322) while the SAME caches
    # exercise tag reuse.
    caches = TagCaches()
    counting_a = _CountingStageA(_TXNS)
    reasoners = Reasoners(
        stage_a=counting_a,
        stage_b=StubStageBReasoner(_TXNS),
        materialization=stub_materialization_reasoners(),
    )

    lf1 = await _loan_file_id(db_session)
    run1_snap = _snapshot(_TXNS, lf1)
    await run_verification(
        db_session,
        run_id=run1_snap.run_id,
        loan_file_id=lf1,
        base_snapshot=run1_snap,
        caches=caches,
        reasoners=reasoners,
    )
    calls_after_run1 = counting_a.calls
    assert calls_after_run1 > 0  # produced on the first run

    # Re-run with the SAME facts + the SAME caches → every tag is a cache HIT.
    lf2 = await _loan_file_id(db_session)
    run2_snap = _snapshot(_TXNS, lf2)
    await run_verification(
        db_session,
        run_id=run2_snap.run_id,
        loan_file_id=lf2,
        base_snapshot=run2_snap,
        caches=caches,
        reasoners=reasoners,
    )
    assert counting_a.calls == calls_after_run1  # no re-production — all reused


async def test_rerun_with_one_changed_document_reproduces_only_that_entity(
    db_session: AsyncSession,
) -> None:
    caches = TagCaches()

    lf1 = await _loan_file_id(db_session)
    run1_snap = _snapshot(_TXNS, lf1)
    counting1 = _CountingStageA(_TXNS)
    await run_verification(
        db_session,
        run_id=run1_snap.run_id,
        loan_file_id=lf1,
        base_snapshot=run1_snap,
        caches=caches,
        reasoners=Reasoners(
            stage_a=counting1,
            stage_b=StubStageBReasoner(_TXNS),
            materialization=stub_materialization_reasoners(),
        ),
    )
    # Change ONE transaction's amount → its content fingerprint changes → only it re-produces.
    changed = (
        FixtureTxn(**{**_UNSOURCED.__dict__, "amount": "41000.00"}),
        _VERIFIED_IN,
        _VERIFIED_DEBIT,
    )
    lf2 = await _loan_file_id(db_session)
    run2_snap = _snapshot(changed, lf2)
    counting2 = _CountingStageA(changed)
    await run_verification(
        db_session,
        run_id=run2_snap.run_id,
        loan_file_id=lf2,
        base_snapshot=run2_snap,
        caches=caches,
        reasoners=Reasoners(
            stage_a=counting2,
            stage_b=StubStageBReasoner(changed),
            materialization=stub_materialization_reasoners(),
        ),
    )
    # The unchanged two are cache hits; only the changed entity re-produced (one small batch),
    # NOT a full re-tag of all three.
    assert counting2.calls == 1


# --------------------------------------------------------------------------- #
# Real-data outcome (LF-6T3N frozen trace, rules over the already-tagged snapshot)
# --------------------------------------------------------------------------- #


async def test_lf6t3n_dti_gated_forces_as1_couldnt_check(db_session: AsyncSession) -> None:
    # LIVE behavior (LP-321a): LF-6T3N has no insurance binder → the DTI GATES
    # (housing.insurance_monthly unknown → auto_amount None → LP-318 gated calc) → AS-1's threshold
    # input is unavailable → AS-1 couldnt_checks its money-in subjects. The fixture previously stored
    # a STRIPPED DTI (gated=False, breakdown=[]) so AS-1 evaluated normally and the test asserted
    # "0 fired" as a green FICTION disagreeing with the live pipeline; corrected here to the live
    # gated-DTI → AS-1-couldnt_check outcome.
    lf_id = await _loan_file_id(db_session)
    frozen = load_fixture_snapshot("lf6t3n_tagged_snapshot.json")
    snap = frozen.model_copy(update={"loan_file_id": lf_id, "run_id": uuid4()})
    run = await run_verification(
        db_session,
        run_id=snap.run_id,
        loan_file_id=lf_id,
        base_snapshot=snap,
        produce_tags=False,
    )

    # GUARD: the fixture's DTI must gate exactly as the live calc does. If a future PII-reduction
    # silently strips it back to gated=False, this FAILS instead of passing on a fiction.
    dti = run.snapshot.calculations.dti
    assert dti is not None and dti.gated is True
    assert dti.value["back_end_dti"] is None  # a gated calc emits no confident ratio
    assert "insurance" in (dti.gate_reason or "")
    insurance = next(x for x in dti.breakdown if x.key == "housing.insurance")
    assert insurance.from_tag == "housing.insurance_monthly" and insurance.amount is None

    # AS-1: its subjects are COULDNT_CHECK (the threshold input is gated) — NOT satisfied, NOT fired.
    # The deposits are unevaluated-for-threshold, NOT cleared (distinguish couldnt_check from satisfied).
    as1 = [f for f in run.findings if f.rule_id == "AS-1"]
    assert as1  # AS-1 evaluated its subjects
    assert all(f.evaluation_outcome is not EvaluationOutcome.OPEN for f in as1)  # 0 fired
    assert all(f.evaluation_outcome is not EvaluationOutcome.SATISFIED for f in as1)  # 0 cleared
    assert any(
        f.evaluation_outcome is EvaluationOutcome.COULDNT_CHECK for f in as1
    )  # gated through

    # The Stage-A/B SOURCING is unaffected by the DTI gate — the large deposits still carry the
    # verified / self_asserted distinction per the real trace (assert it separately so that coverage
    # is not lost when the DTI gates).
    strengths = Counter(
        tags["txn.source_strength"].value
        for tags in run.snapshot.tags.by_subject.values()
        if "txn.source_strength" in tags
    )
    assert strengths["verified"] >= 1
    assert strengths["self_asserted"] >= 1


# --------------------------------------------------------------------------- #
# Degradation visibility (structural) + judgment-tag write-back (LP-321 review)
# --------------------------------------------------------------------------- #


def _degraded_tag(value: str, *, produced_by: TagProducedBy, confidence: float | None) -> Tag:
    return Tag(
        value=value,
        confidence=confidence,
        reasoning="not returned by structuring pass",
        source_facts=("x",),
        produced_by=produced_by,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def test_scan_tag_degradations_flags_omitted_but_not_genuine_or_parsed_unknowns() -> None:
    # STRUCTURAL fail-closed marker: value="unknown" + produced_by=AI + confidence None. This catches
    # the "not returned" omission a reason-string match missed, while a genuine AI unknown (has a
    # confidence) and a parsed passthrough (produced_by != AI) are NOT degradations.
    snap = _snapshot(_TXNS, uuid4())
    by_subject = {
        "txn1": {
            "txn.is_money_in": _degraded_tag(
                "unknown", produced_by=TagProducedBy.AI, confidence=None
            )
        },
        "txn2": {
            "txn.is_money_in": _degraded_tag(
                "unknown", produced_by=TagProducedBy.AI, confidence=0.4
            )
        },
        "txn3": {
            "txn.amount": _degraded_tag(
                "unknown", produced_by=TagProducedBy.PARSED, confidence=None
            )
        },
    }
    snap = snap.model_copy(update={"tags": TagsSection.present(by_subject)})
    assert {d.subject for d in _scan_tag_degradations(snap)} == {"txn1:txn.is_money_in"}


def test_judgment_tag_is_merged_into_the_tags_layer_under_the_loan_subject() -> None:
    # A judgment rule's produced tag must land in the tags layer (not be discarded).
    snap = _snapshot(_TXNS, uuid4())
    tag = Tag(
        value="no",
        confidence=0.8,
        reasoning="signals contradict a primary",
        source_facts=(LOAN_SUBJECT,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.RULE_JUDGMENT,
        stage=TagStage.B,
    )
    # LP-327: tags are keyed {subject_id: {tag_id: Tag}} — OC-2's loan verdict lands under LOAN_SUBJECT.
    merged = _merge_judgment_tags(snap, {LOAN_SUBJECT: {JUDGMENT_TAG: tag}})
    assert merged.tags.by_subject[LOAN_SUBJECT][JUDGMENT_TAG].value == "no"
    # No judgment tags produced (OC-2 couldnt_check today) → the snapshot is returned unchanged.
    assert _merge_judgment_tags(snap, {}) is snap


def test_retire_eligible_excludes_as1_when_the_documents_section_is_degraded() -> None:
    # AS-1 enumerates its subjects from the documents section; if that section is absent (a build
    # degradation) it is NOT retire-eligible — a degraded run must not retire AS-1 findings. OC-2
    # (single loan-level subject) stays eligible.
    healthy = _snapshot(_TXNS, uuid4())
    assert "AS-1" in _retire_eligible_rules(healthy)

    degraded = healthy.model_copy(update={"documents": DocumentsSection.failed("build failed")})
    eligible = _retire_eligible_rules(degraded)
    assert "AS-1" not in eligible  # not retire-eligible on a degraded documents section
    assert "OC-2" in eligible


def _doc_snapshot(entries: list[DocumentEntry]) -> Snapshot:
    return _snapshot(_TXNS, uuid4()).model_copy(
        update={"documents": DocumentsSection.present(entries)}
    )


def test_retire_eligible_excludes_per_borrower_rules_when_no_borrower_resolved() -> None:
    # ID-2/ID-4 enumerate per-borrower from documents' belongs_to. Documents present but NO borrower
    # resolved (belongs_to unresolved) is a DEGRADATION, not "the borrowers are gone" — the rules must
    # NOT be retire-eligible then (else a real prior identity finding retires to false-green).
    borrower = uuid4()
    resolved = _doc_snapshot(
        [
            DocumentEntry(
                content_id="d1",
                document_type="doc",
                belongs_to=(BorrowerRef(borrower_id=borrower, name="Sam"),),
                fields={},
            )
        ]
    )
    assert {"ID-2", "ID-4"} <= _retire_eligible_rules(resolved)  # a borrower resolved → eligible

    # Every ACTIVE per-borrower rule (derived from subject_enumeration, not a hardcoded list) — not
    # just ID-2/ID-4 — is eligible when a borrower resolved.
    assert {"ID-1", "ID-2", "ID-3", "ID-4"} <= _retire_eligible_rules(resolved)

    unresolved = _doc_snapshot(
        [DocumentEntry(content_id="d1", document_type="doc", belongs_to=None, fields={})]
    )
    eligible = _retire_eligible_rules(unresolved)
    # ALL per-borrower rules drop (zero borrowers → degraded, not "gone"); loan rules stay.
    assert {"ID-1", "ID-2", "ID-3", "ID-4"}.isdisjoint(eligible)
    assert "OC-2" in eligible and "ID-6" in eligible  # loan-level rules are always eligible


def test_retire_guard_covers_every_document_derived_shape() -> None:
    # The guard is generalized (LP-327): per_deposit / per_borrower / per_document / per_account (LP-336)
    # / per_liability (LP-480) all derive their subjects from the documents section, so a rule on ANY of
    # them is covered automatically — no per-shape special-casing left to forget.
    #
    # ⚠️ Asserted against KNOWN_ENUMERATORS rather than a hand-written literal (the LP-480 review): the
    # literal form silently went stale when per_liability was added, which is exactly the omission that
    # would have let a degraded run retire every prior tradeline finding. Now a NEW enumerator fails this
    # test until someone classifies it. ``loan`` is the sole document-INDEPENDENT shape (always exactly
    # one subject) → always retire-eligible; every other shape draws on the documents section.
    from app.services.verification_run import _DOCUMENT_DERIVED_ENUMERATIONS
    from app.verification.rule_engine.enumerators import KNOWN_ENUMERATORS

    assert KNOWN_ENUMERATORS - {"loan"} == _DOCUMENT_DERIVED_ENUMERATIONS, (
        "a new subject_enumeration must be classified as document-derived (add it to "
        "_DOCUMENT_DERIVED_ENUMERATIONS) or document-independent (add it to this test's exclusions)"
    )
    # documents absent → AS-1 (per_deposit) drops via the SAME generic path (not by rule-id name).
    absent = _snapshot(_TXNS, uuid4()).model_copy(
        update={"documents": DocumentsSection.failed("build failed")}
    )
    eligible = _retire_eligible_rules(absent)
    assert "AS-1" not in eligible
    assert {"ID-1", "ID-2", "ID-3", "ID-4"}.isdisjoint(eligible)
    assert "OC-2" in eligible and "ID-6" in eligible


def test_required_ai_groups_runs_only_what_active_rules_consume() -> None:
    # The materialization stage runs ONLY the AI groups a live rule reads (derived from the active
    # rules' load-bearing tags). id_address feeds ID-4/OC-2; id_name feeds ID-1; id_title feeds ID-7;
    # id_poa feeds ID-9 (all four now active). (ID-2's id.ssn_hash and ID-3's id.dob are PARSED, so
    # they contribute no AI group.)
    groups = _required_ai_groups()
    assert {"id_address", "id_name", "id_title", "id_poa"} <= groups


def _evaluation(
    rule_id: str,
    subject_id: str,
    verdict,
    reasoning: str = "the subject's own reasoning",
    *,
    load_bearing_tags=(),
    apply=None,
    evidence=None,
    derivation=None,
    requested_documents=(),
    how_to_fix=None,
):
    """A minimal RuleEvaluation for the collapse tests (bug-005)."""
    from app.verification.rule_engine.result import RuleEvaluation

    return RuleEvaluation(
        rule_id=rule_id,
        subject_id=subject_id,
        verdict=verdict,
        verdict_confidence=0.9,
        load_bearing_tags=load_bearing_tags,
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=True,
        reasoning=reasoning,
        how_to_fix=how_to_fix,
        apply=apply,
        evidence=evidence,
        derivation=derivation,
        requested_documents=requested_documents,
    )


def _tag(tag_id: str, value: str):
    from app.verification.rule_engine.result import LoadBearingTag

    return LoadBearingTag(tag_id=tag_id, value=value, confidence=0.9, reasoning=None)


def test_a_uniform_pass_collapses_to_one_row() -> None:
    """bug-005 — CR-12 asks one question per credit-report tradeline, so a CLEAN report produced 24
    green rows each saying a version of "this account is not under dispute". Individually correct,
    collectively a wall, and a processor scrolling past 24 identical passes is being trained to scroll
    past the rule."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.enumerators import LOAN_SUBJECT
    from app.verification.rule_engine.result import Verdict

    passes = [_evaluation("CR-12", f"lst{i:016x}", Verdict.SATISFIED) for i in range(24)]
    [collapsed] = _collapse_uniform_passes(passes)

    assert collapsed.rule_id == "CR-12"
    assert collapsed.subject_id == LOAN_SUBJECT
    assert collapsed.verdict is Verdict.SATISFIED
    assert "dispute remark" in collapsed.reasoning
    assert collapsed.load_bearing_tags == (), "they belong to subjects this row no longer names"
    assert collapsed.how_to_fix is None, "a pass has nothing to remediate"


def test_one_dissenting_verdict_keeps_every_subject() -> None:
    """THE FALSE-GREEN THIS MUST NOT BECOME. Naming WHICH account is the entire point of asking per
    account; a summary hiding one disputed tradeline behind 23 clean ones is exactly the shape this
    codebase refuses everywhere else."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    group = [_evaluation("CR-12", f"lst{i:016x}", Verdict.SATISFIED) for i in range(23)]
    group.append(_evaluation("CR-12", "lstdisputed00001", Verdict.FIRED))

    kept = _collapse_uniform_passes(group)
    assert len(kept) == 24
    assert any(r.verdict is Verdict.FIRED for r in kept)


def test_a_rule_that_does_not_declare_it_is_untouched() -> None:
    """Absent means "show every subject", and that stays the default: most per-subject rules are worth
    seeing per subject even when they pass — CR-1's four satisfied liabilities name four real debts."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    group = [_evaluation("CR-1", f"lst{i:016x}", Verdict.SATISFIED) for i in range(4)]
    assert len(_collapse_uniform_passes(group)) == 4


def test_out_of_scope_subjects_are_not_dissent() -> None:
    """THE REASON THE COLLAPSE NEVER FIRED ON THE FILE IT WAS WRITTEN FOR. `NOT_APPLICABLE` results are
    still in `results` here — they are dropped at PERSIST, not at evaluation — so CR-12's four
    not-applicable MISMO liabilities sat beside its 24 satisfied tradelines and an "all satisfied" test
    read them as disagreement."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.enumerators import LOAN_SUBJECT
    from app.verification.rule_engine.result import Verdict

    group = [_evaluation("CR-12", f"lst{i:016x}", Verdict.SATISFIED) for i in range(24)]
    group += [_evaluation("CR-12", f"lia{i:016x}", Verdict.NOT_APPLICABLE) for i in range(4)]

    out = _collapse_uniform_passes(group)
    summaries = [r for r in out if r.subject_id == LOAN_SUBJECT]
    assert len(summaries) == 1
    assert "dispute remark" in summaries[0].reasoning
    assert len([r for r in out if r.verdict is Verdict.NOT_APPLICABLE]) == 4, "carried through"


def test_a_uniform_couldnt_check_with_one_shared_sentence_collapses() -> None:
    """RE-1's two mortgage statements each said "Identify which of the TWO United Wholesale Mortgage
    statements corresponds to the mortgage liability disclosed on the application" — one sentence about
    the pair, printed once per half of the pair."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.enumerators import LOAN_SUBJECT
    from app.verification.rule_engine.result import Verdict

    shared = "which statement corresponds to the stated liability could not be resolved"
    group = [
        _evaluation("RE-1", "docaaaa", Verdict.COULDNT_CHECK, reasoning=shared),
        _evaluation("RE-1", "docbbbb", Verdict.COULDNT_CHECK, reasoning=shared),
    ]

    [only] = _collapse_uniform_passes(group)
    assert only.subject_id == LOAN_SUBJECT
    assert only.verdict is Verdict.COULDNT_CHECK
    assert only.reasoning == shared


def test_different_reasons_still_speak_for_themselves() -> None:
    """The safety property that makes collapsing a NON-pass outcome honest: two subjects failing for
    DIFFERENT reasons share no sentence, so there is nothing to promote and both stand."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    group = [
        _evaluation(
            "RE-1", "docaaaa", Verdict.COULDNT_CHECK, reasoning="the lender name is missing"
        ),
        _evaluation(
            "RE-1", "docbbbb", Verdict.COULDNT_CHECK, reasoning="the payment is unreadable"
        ),
    ]
    assert len(_collapse_uniform_passes(group)) == 2


def test_a_uniform_non_pass_does_not_collapse_unless_the_spec_declares_it() -> None:
    """bug-007 — THE GUARD THAT WAS VACUOUS. Collapsing any uniform outcome whose subjects shared
    identical reasoning read as a safety property and was none: a deterministic rule renders its
    outcome template verbatim and substitutes only declared operands, so CR-12 (`operands: {}`) says
    the same words on every disputed tradeline BY CONSTRUCTION. Three disputed accounts collapsed into
    one "Whole file" red whose prose was singular and named none of them — the false-green CR-12's own
    spec comment promises it will never become, arrived at from the other direction."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    shared = "the credit report shows THIS TRADELINE as disputed by the consumer"
    group = [
        _evaluation("CR-12", "lstcapone", Verdict.FIRED, reasoning=shared),
        _evaluation("CR-12", "lstbofa00", Verdict.FIRED, reasoning=shared),
        _evaluation("CR-12", "lstchase0", Verdict.FIRED, reasoning=shared),
    ]

    kept = _collapse_uniform_passes(group)
    assert len(kept) == 3, (
        "CR-12 does not declare `unresolved`; its sentence is about ONE tradeline"
    )
    assert {r.subject_id for r in kept} == {"lstcapone", "lstbofa00", "lstchase0"}


def test_a_collapsed_non_pass_keeps_what_makes_it_actionable() -> None:
    """bug-007 — the fields that were dropped by omission rather than by decision. `apply` is the
    sharpest: LP-576 records that for a rule that can never fire "the Apply IS the human's answer to
    it", and a collapsed needs_review built with the field defaulted shipped with no button at all."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.enumerators import LOAN_SUBJECT
    from app.verification.rule_engine.result import Verdict

    shared = "which statement corresponds to the stated liability could not be resolved"
    change = {"action": "identify_statement"}
    group = [
        _evaluation(
            "RE-1",
            "docaaaa",
            Verdict.NEEDS_REVIEW,
            reasoning=shared,
            load_bearing_tags=(_tag("doc.lender", "United Wholesale Mortgage"),),
            apply=change,
            evidence="both statements name the same lender.",
            derivation="Threshold: n/a",
            requested_documents=("mortgage_statement",),
            how_to_fix="Identify which statement corresponds to the stated liability.",
        ),
        _evaluation(
            "RE-1",
            "docbbbb",
            Verdict.NEEDS_REVIEW,
            reasoning=shared,
            load_bearing_tags=(_tag("doc.lender", "United Wholesale Mortgage"),),
            apply=change,
            evidence="both statements name the same lender.",
            derivation="Threshold: n/a",
            requested_documents=("mortgage_statement",),
            how_to_fix="Identify which statement corresponds to the stated liability.",
        ),
    ]

    [only] = _collapse_uniform_passes(group)
    assert only.subject_id == LOAN_SUBJECT
    assert only.apply == change, "no apply is no button, on the outcome whose answer IS the apply"
    assert only.evidence == "both statements name the same lender."
    assert only.derivation == "Threshold: n/a"
    assert only.requested_documents == ("mortgage_statement",)
    assert only.load_bearing_tags == (_tag("doc.lender", "United Wholesale Mortgage"),), (
        "on a non-pass the tags are what name the subjects the row stands for"
    )
    assert only.how_to_fix is not None


def test_a_collapsed_non_pass_carries_only_what_its_subjects_agreed_on() -> None:
    """One subject's arithmetic on a row standing for all of them is a quieter version of the same
    false summary the collapse exists to avoid. Disagreement drops the field rather than picking one;
    the documents are a union, because waiting on either is waiting on both."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    shared = "which statement corresponds to the stated liability could not be resolved"
    group = [
        _evaluation(
            "RE-1",
            "docaaaa",
            Verdict.COULDNT_CHECK,
            reasoning=shared,
            apply={"action": "a"},
            derivation="Threshold: $1,000.00",
            requested_documents=("mortgage_statement",),
        ),
        _evaluation(
            "RE-1",
            "docbbbb",
            Verdict.COULDNT_CHECK,
            reasoning=shared,
            apply={"action": "b"},
            derivation="Threshold: $2,000.00",
            requested_documents=("closing_disclosure",),
        ),
    ]

    [only] = _collapse_uniform_passes(group)
    assert only.apply is None, "two different changes cannot both be THE change on one row"
    assert only.derivation is None
    assert only.requested_documents == ("mortgage_statement", "closing_disclosure")


def test_a_pass_still_drops_the_per_subject_fields() -> None:
    """They belong to subjects the row no longer names, and a pass has nothing to remediate — the
    bug-007 widening is for the outcomes a processor has to act on, not for green."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    passes = [
        _evaluation(
            "CR-12",
            f"lst{i:016x}",
            Verdict.SATISFIED,
            load_bearing_tags=(_tag("liab.creditor_name", f"Creditor {i}"),),
            apply={"action": "nothing"},
            requested_documents=("credit_report",),
        )
        for i in range(24)
    ]

    [collapsed] = _collapse_uniform_passes(passes)
    assert collapsed.load_bearing_tags == ()
    assert collapsed.apply is None
    assert collapsed.evidence is None
    assert collapsed.derivation is None
    assert collapsed.requested_documents == ()
    assert collapsed.how_to_fix is None


def test_a_rule_a_human_has_answered_per_subject_stays_per_subject() -> None:
    """bug-007 — COLLAPSING IS PART OF A FINDING'S IDENTITY, and that makes it destructive after the
    fact. Reconciliation keys on `(rule_id, subject_id)` and never re-keys a finding it carries
    forward, so a group that turns uniform retires every per-subject row and mints one loan-level row
    in their place — and a retired finding takes its resolution with it, turning a processor's APPLIED
    or OVERRIDDEN answer back into fresh OPEN work."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    shared = "which statement corresponds to the stated liability could not be resolved"
    group = [
        _evaluation("RE-1", "docaaaa", Verdict.COULDNT_CHECK, reasoning=shared),
        _evaluation("RE-1", "docbbbb", Verdict.COULDNT_CHECK, reasoning=shared),
    ]

    assert len(_collapse_uniform_passes(group)) == 1, "with nothing resolved it collapses"
    kept = _collapse_uniform_passes(group, humanly_resolved_rule_ids=frozenset({"RE-1"}))
    assert len(kept) == 2
    assert {r.subject_id for r in kept} == {"docaaaa", "docbbbb"}


def test_a_resolved_subject_on_another_rule_does_not_block_this_one() -> None:
    """The guard is per rule, and it has to be: one answered CR-1 finding must not freeze RE-1's
    shape, or the first resolution on a file would un-collapse everything."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    shared = "which statement corresponds to the stated liability could not be resolved"
    group = [
        _evaluation("RE-1", "docaaaa", Verdict.COULDNT_CHECK, reasoning=shared),
        _evaluation("RE-1", "docbbbb", Verdict.COULDNT_CHECK, reasoning=shared),
    ]

    assert len(_collapse_uniform_passes(group, humanly_resolved_rule_ids=frozenset({"CR-1"}))) == 1


def test_a_pass_collapses_even_where_a_human_has_answered() -> None:
    """The guard protects RESOLVED work, and nothing resolves a green: `_persistable` files a
    satisfied verdict as an outcome, not as a task. Freezing the pass collapse too would bring the
    24-row wall back on every file a processor had ever touched."""
    from app.services.verification_run import _collapse_uniform_passes
    from app.verification.rule_engine.result import Verdict

    passes = [_evaluation("CR-12", f"lst{i:016x}", Verdict.SATISFIED) for i in range(24)]
    assert (
        len(_collapse_uniform_passes(passes, humanly_resolved_rule_ids=frozenset({"CR-12"}))) == 1
    )
