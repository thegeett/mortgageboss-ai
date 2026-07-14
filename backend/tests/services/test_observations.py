"""The observation channel + graduation log (LP-320).

Keyless (the Reasoner stub for the AI step). Proves: unmapped -> a structured observation (never a
fabricated tag, never dropped); the INFORM-not-RESOLVE boundary (an observation cannot flip a
finding's verdict); fail-closed-to-human-review; a novel document ALWAYS yields an observation; and
the graduation tally + ranking. DB-backed via the rollback fixture.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.ai.observation import AIClientError, ObservationRead, ObservationResult
from app.models import (
    Company,
    EvaluationOutcome,
    Finding,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
)
from app.services.loan_files import create_loan_file
from app.services.observations import (
    observations_for_finding,
    observe_unmapped,
    pending_review_observations,
    record_observation,
    top_graduation_candidates,
)
from sqlalchemy.ext.asyncio import AsyncSession

_RUN = uuid4()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _StubReasoner:
    """Replays a canned observation read (or a failure)."""

    def __init__(
        self,
        *,
        read: ObservationRead | None = None,
        truncated: bool = False,
        raises: Exception | None = None,
    ) -> None:
        self._read = read
        self._truncated = truncated
        self._raises = raises

    async def __call__(self, context_json: str) -> ObservationResult:
        if self._raises is not None:
            raise self._raises
        return ObservationResult(
            read=self._read,
            input_tokens=0,
            output_tokens=0,
            model="stub",
            truncated=self._truncated,
        )


async def _loan_file_id(db: AsyncSession) -> UUID:
    company = Company(name="Acme", slug=f"acme-{uuid4().hex[:6]}")
    db.add(company)
    await db.flush()
    lf = await create_loan_file(db, company_id=company.id)
    return lf.id


async def _as1_finding(db: AsyncSession, loan_file_id: UUID) -> Finding:
    finding = Finding(
        loan_file_id=loan_file_id,
        rule_id="AS-1",
        origin=FindingOrigin.DETERMINISTIC_RULE,
        status=FindingStatus.RED,
        category=FindingCategory.ASSETS,
        message="unsourced large deposit",
        confidence=1.0,
        evaluation_outcome=EvaluationOutcome.OPEN,
    )
    db.add(finding)
    await db.flush()
    return finding


# --------------------------------------------------------------------------- #
# Unmapped -> a structured observation (never a tag, never dropped)
# --------------------------------------------------------------------------- #


async def test_unmapped_document_records_a_structured_observation(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    read = ObservationRead(
        observation_type="divorce_decree",
        value="a divorce decree assigning the property to the borrower",
        structured={"parties": ["borrower", "ex-spouse"], "asset": "subject property"},
        needs_tag=True,
        reasoning="not covered by any current tag",
        confidence=0.8,
    )
    obs = await observe_unmapped(
        db_session,
        loan_file_id=lf_id,
        run_id=_RUN,
        about="docabc0000000001",
        context={"document_type": "unknown", "text_excerpt": "..."},
        reasoner=_StubReasoner(read=read),
    )
    assert obs.observation_type == "divorce_decree"
    assert obs.value.startswith("a divorce decree")
    assert obs.structured["asset"] == "subject property"
    assert obs.produced_by == "ai"
    assert obs.needs_tag is True
    assert obs.reasoning == "not covered by any current tag"
    # It is an OBSERVATION, not a formal tag or a finding resolution.
    assert obs.relates_to_finding_id is None


async def test_novel_document_always_yields_an_observation_even_when_ai_fails(
    db_session: AsyncSession,
) -> None:
    # §7 discovery: a novel document is NEVER silently dropped. AI failure -> a fallback observation.
    lf_id = await _loan_file_id(db_session)
    for reasoner in (
        _StubReasoner(raises=AIClientError("boom")),
        _StubReasoner(read=None),  # malformed
        _StubReasoner(read=ObservationRead("x", "y"), truncated=True),  # truncated
    ):
        obs = await observe_unmapped(
            db_session,
            loan_file_id=lf_id,
            run_id=_RUN,
            about=f"doc{uuid4().hex[:12]}",
            context={"document_type": "unknown"},
            reasoner=reasoner,
        )
        assert obs.observation_type == "unclassified_document"
        assert obs.needs_tag is True  # flagged for a human — never dropped


# --------------------------------------------------------------------------- #
# The INFORM-not-RESOLVE boundary + fail-closed to human review
# --------------------------------------------------------------------------- #


async def test_observation_attached_to_finding_does_not_change_its_verdict(
    db_session: AsyncSession,
) -> None:
    lf_id = await _loan_file_id(db_session)
    finding = await _as1_finding(db_session, lf_id)
    outcome_before = finding.evaluation_outcome
    status_before = finding.status

    await record_observation(
        db_session,
        loan_file_id=lf_id,
        run_id=_RUN,
        about="txndeposit00000001",
        observation_type="gift_letter_asserted",
        value="document asserts a $10,000 gift related to the deposit",
        relates_to_finding_id=finding.id,
        needs_tag=True,
    )
    await db_session.refresh(finding)
    # The observation INFORMS but does not RESOLVE — the finding's verdict is untouched.
    assert finding.evaluation_outcome is outcome_before is EvaluationOutcome.OPEN
    assert finding.status is status_before
    assert finding.resolved_at is None


async def test_needs_tag_observation_surfaces_for_human_review(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    finding = await _as1_finding(db_session, lf_id)
    # A needs_tag observation attached to the finding — fails closed to human review.
    await record_observation(
        db_session,
        loan_file_id=lf_id,
        run_id=_RUN,
        about="txndeposit00000001",
        observation_type="gift_letter_asserted",
        value="document asserts a gift",
        relates_to_finding_id=finding.id,
        needs_tag=True,
    )
    # An unrelated, non-flagged observation should NOT surface.
    await record_observation(
        db_session,
        loan_file_id=lf_id,
        run_id=_RUN,
        about="docxyz",
        observation_type="document_purpose",
        value="a cover letter",
        needs_tag=False,
    )
    pending = await pending_review_observations(db_session, loan_file_id=lf_id)
    assert len(pending) == 1
    assert pending[0].relates_to_finding_id == finding.id
    # And the finding's attached observations are readable (the review context).
    attached = await observations_for_finding(db_session, finding.id)
    assert [o.observation_type for o in attached] == ["gift_letter_asserted"]


# --------------------------------------------------------------------------- #
# The gift-letter trace (the canonical example)
# --------------------------------------------------------------------------- #


async def test_gift_letter_fails_closed_and_does_not_auto_resolve_as1(
    db_session: AsyncSession,
) -> None:
    lf_id = await _loan_file_id(db_session)
    as1 = await _as1_finding(db_session, lf_id)  # AS-1 fired: unsourced large deposit

    obs = await record_observation(
        db_session,
        loan_file_id=lf_id,
        run_id=_RUN,
        about="txndeposit00000009",
        observation_type="gift_letter_asserted",
        value="document asserts a $20,000 gift related to deposit txndeposit00000009",
        structured={"amount": "20000", "relationship": "parent"},
        relates_to_finding_id=as1.id,
        relates_to_subject="txndeposit00000009",
        needs_tag=True,
    )
    await db_session.refresh(as1)
    # A gift letter is not yet a formal tag: the observation RELATES to the AS-1 finding and FAILS
    # CLOSED to human review — it does NOT auto-resolve AS-1 (only a governed gift.* tag+rule would).
    assert as1.evaluation_outcome is EvaluationOutcome.OPEN  # still open — NOT resolved
    assert obs.relates_to_subject == "txndeposit00000009"
    pending = await pending_review_observations(db_session, loan_file_id=lf_id)
    assert obs.id in {o.id for o in pending}


# --------------------------------------------------------------------------- #
# The graduation log
# --------------------------------------------------------------------------- #


async def test_recurring_type_increments_the_graduation_tally(db_session: AsyncSession) -> None:
    lf_id = await _loan_file_id(db_session)
    # "gift_letter_asserted" three times across runs; "trust_agreement" once; a case/space variant of
    # the first normalizes to the same signature.
    for run in (uuid4(), uuid4(), uuid4()):
        await record_observation(
            db_session,
            loan_file_id=lf_id,
            run_id=run,
            about="d",
            observation_type="gift_letter_asserted",
            value="a gift",
        )
    await record_observation(
        db_session,
        loan_file_id=lf_id,
        run_id=uuid4(),
        about="d",
        observation_type="  Gift_Letter_Asserted ",
        value="a gift (variant casing/space)",
    )
    await record_observation(
        db_session,
        loan_file_id=lf_id,
        run_id=uuid4(),
        about="d",
        observation_type="trust_agreement",
        value="a trust",
    )

    candidates = await top_graduation_candidates(db_session)
    by_sig = {c.signature: c for c in candidates}
    # 3 + 1 (normalized variant) = 4 for the gift signature; 1 for the trust.
    assert by_sig["gift_letter_asserted"].occurrences == 4
    assert by_sig["trust_agreement"].occurrences == 1
    # Ranked by frequency — the most-recurring unknown is what the vocabulary is missing most.
    assert candidates[0].signature == "gift_letter_asserted"
