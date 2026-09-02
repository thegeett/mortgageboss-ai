"""LP-640 — the consolidated finding's CROSS-RUN lifecycle, against a real database.

The consolidation itself is unit-tested in
``tests/verification/rule_engine/test_unidentified_document_consolidation_lp640.py``. What that
cannot reach is the half of the change that only exists once a row is written: the consolidated
evaluation carries a SYNTHETIC rule id (``UNIDENTIFIED-DOCUMENTS``) that no spec file declares, and
that id has to survive ``uq_findings_loan_file_rule_subject`` across runs.

That is the failure this file exists to catch. A synthetic id passes every in-memory test and then
mints a second row on the second run, because ``_load_prior_findings`` filters by
``evaluated_rule_ids`` and the caller's frozenset — built from the loaded specs — cannot contain an
id with no spec. The reconciler adds it explicitly; these tests prove the addition is load-bearing by
driving the whole mint → carry-forward → retire → revive cycle.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.models import (
    Company,
    EvaluationOutcome,
    FindingCategory,
    FindingEvent,
    FindingEventType,
)
from app.schemas.verification import RuleFindingPublic
from app.services.loan_files import create_loan_file
from app.services.rule_findings import (
    ReconcileRunResult,
    consolidate_unidentified_documents,
    persist_evaluation_findings,
    reconcile_evaluation_findings,
)
from app.services.verification_run import _collapse_uniform_passes
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_CONSOLIDATED = "UNIDENTIFIED-DOCUMENTS"
# The evaluated set a caller really passes: real rule ids only. `UNIDENTIFIED-DOCUMENTS` is
# deliberately ABSENT, because no spec file carries it — that is the whole point of the test.
_RULES = frozenset({"AS-1", "IN-8"})
_CATS = {"AS-1": FindingCategory.ASSETS, "IN-8": FindingCategory.INCOME}


def _blocked(rule_id: str, document_id: str) -> RuleEvaluation:
    """A rule that abstained because it cannot tell what ``document_id`` is."""
    return RuleEvaluation(
        rule_id=rule_id,
        subject_id=document_id,
        verdict=Verdict.COULDNT_CHECK,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning=f"{rule_id} could not tell whether this document is in scope",
        how_to_fix="Identify the document.",
        unidentified_document=True,
    )


def _ordinary(rule_id: str, subject: str) -> RuleEvaluation:
    """An unrelated finding that must never be folded into the consolidated row."""
    return RuleEvaluation(
        rule_id=rule_id,
        subject_id=subject,
        verdict=Verdict.FIRED,
        verdict_confidence=0.9,
        load_bearing_tags=(LoadBearingTag("txn.amount", "20000.00", 0.9, "because", ("sub",)),),
        threshold_used=Decimal("5000"),
        priya_validated=False,
        gated_pending_signoff=True,
        reasoning="a large deposit with no identified source",
        how_to_fix=None,
    )


async def _loan_file_id(db: AsyncSession) -> UUID:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    return lf.id


async def _reconcile(
    db: AsyncSession, lf_id: UUID, results: list[RuleEvaluation]
) -> ReconcileRunResult:
    return await reconcile_evaluation_findings(
        db,
        loan_file_id=lf_id,
        verification_id=None,
        run_id=uuid4(),
        results=results,
        evaluated_rule_ids=_RULES,
        category_by_rule=_CATS,
    )


async def _event_types(db: AsyncSession, finding_id: UUID) -> list[FindingEventType]:
    rows = await db.execute(
        select(FindingEvent)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.occurred_at)
    )
    return [e.event_type for e in rows.scalars().all()]


# --------------------------------------------------------------------------- #
# Mint — one row for many blocked rules
# --------------------------------------------------------------------------- #


async def test_many_blocked_rules_mint_exactly_one_loan_level_finding(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    result = await _reconcile(
        db_session,
        lf,
        [_blocked(r, d) for d in ("docA", "docB", "docC") for r in ("AS-1", "IN-8")],
    )

    [minted] = result.minted
    assert minted.rule_id == _CONSOLIDATED
    assert minted.subject_key == "loan"
    # The verdict is UNCHANGED — this collapses the queue, never the conclusion (LP-391).
    assert minted.evaluation_outcome is EvaluationOutcome.COULDNT_CHECK
    # Filed under DOCUMENTATION, not the ASSETS default fallback.
    assert minted.category is FindingCategory.DOCUMENTATION
    assert "3 documents" in minted.message
    assert "6 checks" in minted.message


# --------------------------------------------------------------------------- #
# Carry-forward — THE uniqueness-index test
# --------------------------------------------------------------------------- #


async def test_a_second_run_carries_the_same_row_forward_and_does_not_collide(
    db_session: AsyncSession,
) -> None:
    """The regression this file exists for: a synthetic id must not mint twice.

    Without ``UNIDENTIFIED-DOCUMENTS`` in ``evaluated_rule_ids``, ``_load_prior_findings`` never
    loads the run-1 row, run 2 mints a second one, and the flush violates
    ``uq_findings_loan_file_rule_subject``.
    """
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    [minted] = r1.minted

    r2 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    await db_session.flush()  # the collision, if any, surfaces here

    assert r2.minted == []
    [carried] = r2.carried_forward
    assert carried.id == minted.id
    assert await _event_types(db_session, minted.id) == [
        FindingEventType.CREATED,
        FindingEventType.CARRIED_FORWARD,
    ]


async def test_the_row_is_reused_even_as_the_blocked_documents_change(
    db_session: AsyncSession,
) -> None:
    """Identity is the LOAN, not the documents — so a changing document set is one row, re-rendered."""
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA"), _blocked("IN-8", "docB")])
    [minted] = r1.minted
    assert "2 documents" in minted.message

    # One of the two gets typed: same row, re-rendered in the singular.
    r2 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    same = (r2.carried_forward + r2.outcome_changed)[0]
    assert same.id == minted.id
    assert "1 document" in same.message
    assert "2 documents" not in same.message


# --------------------------------------------------------------------------- #
# Retire + revive
# --------------------------------------------------------------------------- #


async def test_typing_the_last_document_retires_the_finding(db_session: AsyncSession) -> None:
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    [minted] = r1.minted

    # Every document now classifies: nothing consolidates this run.
    r2 = await _reconcile(db_session, lf, [_ordinary("AS-1", "dep1")])

    [retired] = r2.retired
    assert retired.id == minted.id
    assert retired.evaluation_outcome is EvaluationOutcome.NO_LONGER_APPLIES
    # Immortality — retired, never soft-deleted.
    assert retired.deleted_at is None


async def test_a_document_going_unidentified_again_revives_the_same_row(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    [minted] = r1.minted
    await _reconcile(db_session, lf, [_ordinary("AS-1", "dep1")])  # retires it

    r3 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])

    assert r3.minted == []
    [revived] = r3.revived
    assert revived.id == minted.id
    assert revived.evaluation_outcome is EvaluationOutcome.COULDNT_CHECK
    assert await _event_types(db_session, minted.id) == [
        FindingEventType.CREATED,
        FindingEventType.RETIRED,
        FindingEventType.REVIVED,
    ]


# --------------------------------------------------------------------------- #
# What must NOT be swept in
# --------------------------------------------------------------------------- #


async def test_zero_unidentified_documents_creates_no_row_at_all(
    db_session: AsyncSession,
) -> None:
    """Not a satisfied "all documents identified" row — there is nothing to action."""
    lf = await _loan_file_id(db_session)
    result = await _reconcile(db_session, lf, [_ordinary("AS-1", "dep1")])

    assert all(f.rule_id != _CONSOLIDATED for f in result.detected)


async def test_an_unrelated_finding_keeps_its_own_row(db_session: AsyncSession) -> None:
    lf = await _loan_file_id(db_session)
    result = await _reconcile(db_session, lf, [_blocked("AS-1", "docA"), _ordinary("IN-8", "dep1")])

    by_rule = {f.rule_id: f for f in result.minted}
    assert set(by_rule) == {_CONSOLIDATED, "IN-8"}
    assert by_rule["IN-8"].subject_key == "dep1"


async def test_a_degraded_run_does_not_false_close_the_consolidated_finding(
    db_session: AsyncSession,
) -> None:
    """A run that could not SEE the documents must not retire the row that describes them.

    ``retire_eligible_rule_ids`` exists precisely so a DEGRADED run is not read as "the subject is
    gone". The consolidated finding's subject domain IS the documents section, so it is the most
    document-derived row there is — and the one whose false-close costs most, because after LP-640 it
    is the ONLY row carrying a signal that used to be spread over 22 rules per document.
    """
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    [minted] = r1.minted

    # Run 2, DEGRADED: the documents section failed to build, so no document subject enumerated and
    # nothing consolidated — NOT because docA got typed.
    r2 = await reconcile_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        run_id=uuid4(),
        results=[],
        evaluated_rule_ids=_RULES,
        category_by_rule=_CATS,
        retire_eligible_rule_ids=frozenset(),  # nothing was healthily enumerated
    )

    assert r2.retired == [], "a degraded run false-closed the unidentified-documents finding"
    assert minted.evaluation_outcome is EvaluationOutcome.COULDNT_CHECK


# --------------------------------------------------------------------------- #
# The READ path — a rule id with no spec file
# --------------------------------------------------------------------------- #


async def test_the_read_path_renders_a_finding_whose_rule_has_no_spec(
    db_session: AsyncSession,
) -> None:
    """``UNIDENTIFIED-DOCUMENTS`` carries no spec file BY DESIGN, so the read path must tolerate one.

    ``_rule_spec`` promised that tolerance in its docstring and did not have it: ``load_rule_spec``
    raises ``RuleSpecNotFound``, which derives from ``Exception`` — not from ``OSError`` / ``KeyError``
    / ``ValueError`` — so it escaped the ``except`` and 500'd the whole verification-status response
    for any file holding one of these findings.
    """
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_blocked("AS-1", "docA")])
    [minted] = r1.minted

    public = RuleFindingPublic.from_model(minted, subject_label="This loan file")

    assert public.rule_id == _CONSOLIDATED
    assert public.rule_name is None  # no spec — the UI falls back to the id
    assert public.guideline is None
    # It still reports the DOCUMENTATION category the finding row carries.
    assert public.category == FindingCategory.DOCUMENTATION.value


# --------------------------------------------------------------------------- #
# The DIRECT persist path (no reconciliation) files it the same way
# --------------------------------------------------------------------------- #


async def test_the_direct_persist_path_also_files_it_under_documentation(
    db_session: AsyncSession,
) -> None:
    """``persist_evaluation_findings`` takes ONE category for the whole batch, so without a per-row
    override the consolidated finding lands under the caller's default while the reconciler files the
    identical row under DOCUMENTATION — the same finding in two categories depending on the path."""
    lf = await _loan_file_id(db_session)

    findings = await persist_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        results=[_blocked("AS-1", "docA"), _ordinary("IN-8", "dep1")],
        category=FindingCategory.ASSETS,  # the caller's batch default
    )

    by_rule = {f.rule_id: f for f in findings}
    assert by_rule[_CONSOLIDATED].category is FindingCategory.DOCUMENTATION
    assert by_rule["IN-8"].category is FindingCategory.ASSETS  # untouched


# --------------------------------------------------------------------------- #
# The per-rule collapse must not eat the rows LP-640 consolidates
# --------------------------------------------------------------------------- #


def _unresolved(rule_id: str, subject: str) -> RuleEvaluation:
    """A genuine uniform-unresolved abstention — the case ``collapse_uniform`` was written for."""
    return RuleEvaluation(
        rule_id=rule_id,
        subject_id=subject,
        verdict=Verdict.COULDNT_CHECK,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=False,
        reasoning="identify which statement matches the disclosed liability",
        how_to_fix="Say which one.",
    )


def test_a_collapsing_rule_still_reaches_consolidation() -> None:
    """RE-1 is the rule where the two mechanisms collide, and the collapse runs FIRST.

    RE-1 is ``per_document`` with a ``document.document_type`` predicate AND declares
    ``collapse_uniform: {unresolved: true}``, so N unidentified documents give it N uniform
    ``couldnt_check`` results with byte-identical reasoning — which the per-rule collapse folds into
    one loan-level row whose constructor never carries ``unidentified_document``. LP-640 then never
    sees them, and RE-1 keeps a second queue row asking the same question the consolidated row asks.
    """
    results = [_blocked("RE-1", d) for d in ("docA", "docB", "docC")]

    final = consolidate_unidentified_documents(_collapse_uniform_passes(results))

    assert [(r.rule_id, r.subject_id) for r in final] == [(_CONSOLIDATED, "loan")]


def test_the_collapse_still_fires_for_that_rule_s_genuine_unresolved_subjects() -> None:
    """The exclusion is narrow: only the identity-blocked subjects leave the collapse.

    A rule can have both at once — two documents it cannot identify and two it can but still cannot
    resolve. The first pair belongs to the consolidated row; the second pair is exactly what
    ``collapse_uniform`` exists for and must still collapse.
    """
    results = [
        _blocked("RE-1", "docA"),
        _blocked("RE-1", "docB"),
        _unresolved("RE-1", "docC"),
        _unresolved("RE-1", "docD"),
    ]

    final = consolidate_unidentified_documents(_collapse_uniform_passes(results))

    assert sorted((r.rule_id, r.subject_id) for r in final) == [
        ("RE-1", "loan"),  # the genuine pair, collapsed as before
        (_CONSOLIDATED, "loan"),  # the identity-blocked pair
    ]


def test_an_ordinary_uniform_pass_still_collapses() -> None:
    """The guard must not disturb the collapse's own reason for existing (bug-005)."""
    passes = [
        RuleEvaluation(
            rule_id="CR-12",
            subject_id=f"tradeline{i}",
            verdict=Verdict.SATISFIED,
            verdict_confidence=None,
            load_bearing_tags=(),
            threshold_used=None,
            priya_validated=False,
            gated_pending_signoff=False,
            reasoning="this account is not under dispute",
            how_to_fix=None,
        )
        for i in range(3)
    ]

    assert [(r.rule_id, r.subject_id) for r in _collapse_uniform_passes(passes)] == [
        ("CR-12", "loan")
    ]
