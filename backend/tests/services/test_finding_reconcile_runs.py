"""Cross-run finding reconciliation (LP-322).

Match this run's evaluations against the prior run's by the stable identity (rule_id, subject_key)
and reconcile: carry-forward / mint / retire / resolve / revive — with IMMORTALITY (never
soft-delete) and an append-only cross-run event log. DB-backed via the rollback fixture; no AI.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.models import (
    Company,
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingEvent,
    FindingEventType,
    FindingResolutionStatus,
)
from app.services.loan_files import create_loan_file
from app.services.rule_findings import ReconcileRunResult, reconcile_evaluation_findings
from app.verification.rule_engine.result import LoadBearingTag, RuleEvaluation, Verdict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_RULE = "AS-1"
_RULES = frozenset({_RULE})
_CATS = {_RULE: FindingCategory.ASSETS}


def _lb(tag_id: str, value: object, *, reasoning: str = "because") -> LoadBearingTag:
    return LoadBearingTag(tag_id, value, 0.9, reasoning, ("sub",))


def _as1(
    subject: str,
    verdict: Verdict,
    *,
    has_source: str | None = None,
    source_strength: str | None = None,
    reasoning: str = "the verdict reasoning",
) -> RuleEvaluation:
    tags: list[LoadBearingTag] = [_lb("txn.is_money_in", "in"), _lb("txn.amount", "20000.00")]
    if has_source is not None:
        tags.append(_lb("txn.has_identified_source", has_source))
    if source_strength is not None:
        tags.append(_lb("txn.source_strength", source_strength))
    return RuleEvaluation(
        rule_id=_RULE,
        subject_id=subject,
        verdict=verdict,
        verdict_confidence=0.9,
        load_bearing_tags=tuple(tags),
        threshold_used=Decimal("5000"),
        priya_validated=False,
        gated_pending_signoff=True,
        reasoning=reasoning,
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


async def _events(db: AsyncSession, finding_id: UUID) -> list[FindingEvent]:
    rows = await db.execute(
        select(FindingEvent)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.occurred_at)
    )
    return list(rows.scalars().all())


async def _event_types(db: AsyncSession, finding_id: UUID) -> list[FindingEventType]:
    return [e.event_type for e in await _events(db, finding_id)]


# --------------------------------------------------------------------------- #
# Carry-forward / mint
# --------------------------------------------------------------------------- #


async def test_carry_forward_keeps_one_finding_across_runs(db_session: AsyncSession) -> None:
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    [minted] = r1.minted
    original_id = minted.id

    r2 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    # SAME finding (id + history preserved), not a duplicate.
    assert r2.minted == []
    [carried] = r2.carried_forward
    assert carried.id == original_id
    assert carried.evaluation_outcome is EvaluationOutcome.OPEN
    # Event log append-only across runs: created (run 1) then carried_forward (run 2).
    assert await _event_types(db_session, original_id) == [
        FindingEventType.CREATED,
        FindingEventType.CARRIED_FORWARD,
    ]


async def test_mint_creates_a_new_finding_for_a_new_subject(db_session: AsyncSession) -> None:
    lf = await _loan_file_id(db_session)
    await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    r2 = await _reconcile(
        db_session,
        lf,
        [
            _as1("dep1", Verdict.FIRED, has_source="no"),
            _as1("dep2", Verdict.FIRED, has_source="no"),  # new subject this run
        ],
    )
    assert {f.subject_key for f in r2.minted} == {"dep2"}
    assert {f.subject_key for f in r2.carried_forward} == {"dep1"}


# --------------------------------------------------------------------------- #
# Retire (immortality — never silent-delete)
# --------------------------------------------------------------------------- #


async def test_retire_moves_undetected_finding_to_no_longer_applies(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    [f1] = r1.minted

    # Run 2: dep1 is GONE (not in this run's results at all).
    r2 = await _reconcile(db_session, lf, [_as1("dep2", Verdict.FIRED, has_source="no")])
    [retired] = r2.retired
    assert retired.id == f1.id
    assert retired.evaluation_outcome is EvaluationOutcome.NO_LONGER_APPLIES
    assert retired.deleted_at is None  # IMMORTALITY — visible, labeled, NOT soft-deleted
    types = await _event_types(db_session, f1.id)
    assert types == [FindingEventType.CREATED, FindingEventType.RETIRED]
    # The retire event names WHY + carries the run.
    retire_event = (await _events(db_session, f1.id))[-1]
    assert retire_event.to_outcome is EvaluationOutcome.NO_LONGER_APPLIES
    assert "no longer detected" in retire_event.detail["reason"]
    assert "run_id" in retire_event.detail


async def test_degraded_run_does_not_retire_findings_it_could_not_reevaluate(
    db_session: AsyncSession,
) -> None:
    # A degraded run (AS-1's documents domain absent → 0 results AND NOT retire-eligible) must NOT
    # flip a real open finding to no_longer_applies (that would be a false-green vector). Only a
    # HEALTHY run that genuinely didn't re-detect the subject retires it.
    lf = await _loan_file_id(db_session)
    [f1] = (await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])).minted

    degraded = await reconcile_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        run_id=uuid4(),
        results=[],  # the rule produced nothing this run…
        evaluated_rule_ids=_RULES,
        category_by_rule=_CATS,
        retire_eligible_rule_ids=frozenset(),  # …because its domain was not healthily enumerated
    )
    assert degraded.retired == []  # dep1's open finding is preserved, not retired
    await db_session.refresh(f1)
    assert f1.evaluation_outcome is EvaluationOutcome.OPEN  # still open, untouched

    # Contrast: a HEALTHY run with the same empty results DOES retire (subject genuinely gone).
    healthy = await reconcile_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        run_id=uuid4(),
        results=[],
        evaluated_rule_ids=_RULES,
        category_by_rule=_CATS,
        retire_eligible_rule_ids=_RULES,
    )
    assert {f.id for f in healthy.retired} == {f1.id}


async def test_retire_does_not_suppress_the_rule_firing_on_a_new_subject(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    await _reconcile(db_session, lf, [_as1("depX", Verdict.FIRED, has_source="no")])
    # depX gone, a NEW depY fires → depX retires, depY mints (retire never suppresses the rule class).
    r2 = await _reconcile(db_session, lf, [_as1("depY", Verdict.FIRED, has_source="no")])
    assert {f.subject_key for f in r2.retired} == {"depX"}
    assert {f.subject_key for f in r2.minted} == {"depY"}


# --------------------------------------------------------------------------- #
# Resolve (the gift-letter loop) — and resolve != retire
# --------------------------------------------------------------------------- #


async def test_resolve_open_becomes_satisfied_on_a_sourcing_tag_flip(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    # Run 1: AS-1 FIRES — unsourced large deposit (open).
    r1 = await _reconcile(
        db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no", source_strength="none")]
    )
    [f1] = r1.minted
    assert f1.evaluation_outcome is EvaluationOutcome.OPEN

    # Run 2: a gift letter produced a gift.* / matched source → has_identified_source flips no→yes →
    # the rule now PASSES → the SAME finding resolves open→satisfied.
    r2 = await _reconcile(
        db_session,
        lf,
        [_as1("dep1", Verdict.SATISFIED, has_source="yes", source_strength="verified")],
    )
    [resolved] = r2.resolved
    assert resolved.id == f1.id  # same identity + history
    assert resolved.evaluation_outcome is EvaluationOutcome.SATISFIED  # rule now passes
    assert r2.retired == []  # NOT retired — the subject is still here
    events = await _events(db_session, f1.id)
    assert [e.event_type for e in events] == [
        FindingEventType.CREATED,
        FindingEventType.RESOLVED,
    ]
    # The resolve event records WHY (the flipped sourcing tag).
    resolve_event = events[-1]
    assert resolve_event.from_outcome is EvaluationOutcome.OPEN
    assert resolve_event.to_outcome is EvaluationOutcome.SATISFIED
    flipped = {t["tag_id"]: t["value"] for t in resolve_event.detail["resolving_tags"]}
    assert flipped["txn.has_identified_source"] == "yes"


async def test_resolve_and_retire_are_distinct_states_and_events(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    # Two open findings in run 1.
    await _reconcile(
        db_session,
        lf,
        [
            _as1("stays", Verdict.FIRED, has_source="no"),
            _as1("leaves", Verdict.FIRED, has_source="no"),
        ],
    )
    # Run 2: "stays" now sourced (resolve → satisfied); "leaves" is gone (retire → no_longer_applies).
    r2 = await _reconcile(
        db_session,
        lf,
        [_as1("stays", Verdict.SATISFIED, has_source="yes", source_strength="verified")],
    )
    assert [f.subject_key for f in r2.resolved] == ["stays"]
    assert [f.subject_key for f in r2.retired] == ["leaves"]
    assert r2.resolved[0].evaluation_outcome is EvaluationOutcome.SATISFIED
    assert r2.retired[0].evaluation_outcome is EvaluationOutcome.NO_LONGER_APPLIES


async def test_still_firing_stays_open_no_observation_resolves_it(
    db_session: AsyncSession,
) -> None:
    # The boundary (LP-320): only a TAG flip resolves. If the rule STILL FIRES (has_source still no),
    # the finding stays OPEN — an observation alone never flips it (reconcile never reads observations).
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    assert len(r1.minted) == 1
    r2 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    assert r2.resolved == []
    assert r2.carried_forward[0].evaluation_outcome is EvaluationOutcome.OPEN


# --------------------------------------------------------------------------- #
# Revive
# --------------------------------------------------------------------------- #


async def test_revive_when_a_retired_subject_reappears(db_session: AsyncSession) -> None:
    lf = await _loan_file_id(db_session)
    r1 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    [f1] = r1.minted
    # Run 2: dep1 gone → retired.
    await _reconcile(db_session, lf, [_as1("other", Verdict.FIRED, has_source="no")])
    # Run 3: dep1 reappears (EXACT subject_key) → the SAME finding revives.
    r3 = await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    [revived] = r3.revived
    assert revived.id == f1.id  # original identity kept
    assert revived.evaluation_outcome is EvaluationOutcome.OPEN
    assert await _event_types(db_session, f1.id) == [
        FindingEventType.CREATED,
        FindingEventType.RETIRED,
        FindingEventType.REVIVED,
    ]


async def test_a_different_subject_is_a_new_finding_not_a_revive(
    db_session: AsyncSession,
) -> None:
    lf = await _loan_file_id(db_session)
    await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    await _reconcile(
        db_session, lf, [_as1("other", Verdict.FIRED, has_source="no")]
    )  # dep1 retired
    # A DIFFERENT subject reappears → a new finding, not a revive of dep1.
    r3 = await _reconcile(db_session, lf, [_as1("dep2", Verdict.FIRED, has_source="no")])
    assert r3.revived == []
    assert {f.subject_key for f in r3.minted} == {"dep2"}


# --------------------------------------------------------------------------- #
# Immortality + no-collision
# --------------------------------------------------------------------------- #


async def test_rerun_does_not_collide_on_the_uniqueness_index(db_session: AsyncSession) -> None:
    # The LP-321 re-run collision is REPLACED by reconcile: re-running the same subject carries it
    # forward (updates the same row) instead of inserting a duplicate → no IntegrityError.
    lf = await _loan_file_id(db_session)
    for _ in range(3):
        await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    # Exactly one finding for the identity, its history a created + two carried_forward.
    from app.models import Finding

    rows = await db_session.execute(
        select(Finding).where(Finding.loan_file_id == lf, Finding.subject_key == "dep1")
    )
    [finding] = rows.scalars().all()
    assert finding.deleted_at is None
    assert await _event_types(db_session, finding.id) == [
        FindingEventType.CREATED,
        FindingEventType.CARRIED_FORWARD,
        FindingEventType.CARRIED_FORWARD,
    ]


async def test_a_recategorised_rule_refiles_the_findings_it_already_has(
    db_session: AsyncSession,
) -> None:
    """LP-598 — THE HALF LP-595 MISSED, and it made that whole fix invisible.

    ``reconcile_run`` read the category map only when MINTING, so every finding that already existed
    kept whatever it was filed under. On LF-3CVT the category fix deployed, a verification run
    completed, and all thirty findings still read "assets" — the appraisal rule and every income rule
    among them. A fix that looks applied and is not is worse than one that visibly fails.

    Safe to overwrite because a category is DERIVED from the rule id rather than chosen by anyone —
    unlike ``resolution_status``, which the next test pins as untouched.
    """
    lf = await _loan_file_id(db_session)
    [minted] = (
        await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    ).minted
    assert minted.category is FindingCategory.ASSETS

    # The rule is re-filed — exactly what LP-595 did to sixty-nine rules at once.
    result = await reconcile_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        run_id=uuid4(),
        results=[_as1("dep1", Verdict.FIRED, has_source="no")],
        evaluated_rule_ids=_RULES,
        category_by_rule={"AS-1": FindingCategory.INCOME},
    )

    [carried] = result.carried_forward
    assert carried.id == minted.id, "identity must be unaffected by a re-filing"
    assert carried.category is FindingCategory.INCOME


async def test_refiling_does_not_disturb_a_humans_resolution(db_session: AsyncSession) -> None:
    """The line the category refresh must not cross. A processor's decision is theirs; a category is
    the engine's bookkeeping."""
    lf = await _loan_file_id(db_session)
    [minted] = (
        await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])
    ).minted
    minted.resolution_status = FindingResolutionStatus.ACCEPTED_RISK
    await db_session.flush()

    result = await reconcile_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        run_id=uuid4(),
        results=[_as1("dep1", Verdict.FIRED, has_source="no")],
        evaluated_rule_ids=_RULES,
        category_by_rule={"AS-1": FindingCategory.INCOME},
    )

    [carried] = result.carried_forward
    assert carried.category is FindingCategory.INCOME
    assert carried.resolution_status is FindingResolutionStatus.ACCEPTED_RISK


async def test_a_retired_finding_stops_reading_as_a_concern(db_session: AsyncSession) -> None:
    """bug-004 — retiring set the outcome, the status and the run id and left ``message`` alone, so a
    green row went on reading as the concern it no longer is.

    On LF-AWBB twenty CR-1 findings retired correctly and still said "the credit report reports this
    debt but the application does not state it — an undisclosed liability that changes the
    debt-to-income picture". A processor scanning the list saw twenty undisclosed liabilities on a file
    that has none. Same defect LP-625 fixed for ``reason``: a sentence that no longer describes the
    state is residue, and residue reading as an open problem is worse than none.

    The prior wording is not lost — it moves to the event detail, where a finding's history lives.
    """
    from app.services.rule_findings import _RETIRED_MESSAGE

    lf = await _loan_file_id(db_session)
    [f1] = (await _reconcile(db_session, lf, [_as1("dep1", Verdict.FIRED, has_source="no")])).minted
    original = f1.message
    assert original

    result = await reconcile_evaluation_findings(
        db_session,
        loan_file_id=lf,
        verification_id=None,
        run_id=uuid4(),
        results=[],
        evaluated_rule_ids=_RULES,
        category_by_rule=_CATS,
        retire_eligible_rule_ids=_RULES,
    )

    [retired] = result.retired
    assert retired.evaluation_outcome is EvaluationOutcome.NO_LONGER_APPLIES
    assert retired.message == _RETIRED_MESSAGE
    assert retired.message != original

    events = (
        await db_session.scalars(select(FindingEvent).where(FindingEvent.finding_id == retired.id))
    ).all()
    superseded = [e.detail.get("superseded_message") for e in events if e.detail]
    assert original in superseded, "the prior wording must survive in the event history"


# --------------------------------------------------------------------------- #
# bug-011 — a rule that produces findings without being ACTIVE
# --------------------------------------------------------------------------- #
_HELD_RULE = "PC-5"


def _held_result(subject: str = "loan", *, reasoning: str = "pending automation") -> RuleEvaluation:
    """A result from a rule the caller does NOT list as evaluated.

    PC-5 is BUILT AND HELD, so it is absent from `ACTIVE_RULE_IDS`, and it still reaches this table
    through LP-391's pending-checks path as a PENDING_AUTOMATION flag.
    """
    return RuleEvaluation(
        rule_id=_HELD_RULE,
        subject_id=subject,
        verdict=Verdict.PENDING_AUTOMATION,
        verdict_confidence=None,
        load_bearing_tags=(),
        threshold_used=None,
        priya_validated=False,
        gated_pending_signoff=True,
        reasoning=reasoning,
        how_to_fix=None,
    )


async def test_a_held_rule_can_be_reconciled_twice(db_session: AsyncSession) -> None:
    """THE REPORTED FAILURE. The first run MINTS the flag; the second must CARRY IT FORWARD.

    Before this, the prior row was never loaded — `evaluated_rule_ids` is the ACTIVE list and a held
    rule is not on it — so the second run minted a duplicate and
    `uq_findings_loan_file_rule_subject` refused it. That IntegrityError failed the persist step of a
    pass that had just spent thirteen minutes of model calls, and the retry restarted the whole pass:
    four attempts, four times the AI spend, and a progress bar the processor watched fall from step
    three back to step two.
    """
    lf_id = await _loan_file_id(db_session)

    first = await _reconcile(db_session, lf_id, [_held_result()])
    assert len(first.minted) == 1

    second = await _reconcile(db_session, lf_id, [_held_result(reasoning="still pending")])

    # Carried forward onto the SAME row, not minted again — which is what the unique index refused.
    assert len(second.minted) == 0
    rows = (
        (
            await db_session.execute(
                select(Finding).where(Finding.loan_file_id == lf_id, Finding.rule_id == _HELD_RULE)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the held rule minted a second row instead of updating its own"


async def test_a_held_rule_is_never_retired_by_a_run_that_did_not_produce_it(
    db_session: AsyncSession,
) -> None:
    """THE REGRESSION THE FIX MUST NOT CAUSE — and the protection is STRUCTURAL, not a guard.

    `_evaluate_pending_checks` is best-effort and isolated: it swallows every exception and returns
    `[]`. So a run where that path failed for its own reasons produces no PC-5 result, and if that
    could retire the existing flag it would turn a real one green — the false-closed that
    `retire_eligible_rule_ids` exists to prevent, reached from the other direction.

    WHAT ACTUALLY PREVENTS IT is that the load set is derived from THIS RUN'S RESULTS. A rule absent
    from the results is never loaded, so it never enters `prior_by_identity`, so the retire loop
    never sees it — whatever the retire gate says. Verified rather than assumed: this test still
    passes with `if prior_finding.rule_id not in retire_eligible` disabled entirely, while the
    pre-existing `test_degraded_run_does_not_retire_findings_it_could_not_reevaluate` fails. Two
    independent protections, and this one is the load's own shape.

    Stated because an earlier version of this docstring claimed the test guarded against widening
    `retire_eligible` alongside the load. It does not — widening it with the run's own result ids
    cannot reach a rule that produced no result — and a docstring naming the wrong mechanism is how
    the next person removes the right one.
    """
    lf_id = await _loan_file_id(db_session)
    await _reconcile(db_session, lf_id, [_held_result()])

    # A later run produces NOTHING for the held rule — exactly what a failed pending-checks pass looks
    # like from here.
    await _reconcile(db_session, lf_id, [_as1("txn_1", Verdict.SATISFIED)])

    row = (
        (
            await db_session.execute(
                select(Finding).where(Finding.loan_file_id == lf_id, Finding.rule_id == _HELD_RULE)
            )
        )
        .scalars()
        .one()
    )
    assert row.evaluation_outcome is not EvaluationOutcome.NO_LONGER_APPLIES, (
        "a run that never looked at the held rule retired its flag — a false green"
    )
