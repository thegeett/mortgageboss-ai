"""LP-391 — pending-check surfacing: a blocked-but-applicable rule flags manual review instead of silence.

These pin the third rule state (applicable-but-manual, between live/trusted and inert/silent): a blocked rule
that reaches a VERDICT (applicable + data present, but untrusted) surfaces a ``PENDING_AUTOMATION`` flag — never
its verdict; a blocked rule that ``couldnt_check`` (data absent) or ``not_applicable`` stays honestly DARK; the
flag is a DISTINCT outcome (Tab 1), never mistakable for a trusted pass/fail; and the mechanism is generic
(bars minus the active set), never a per-rule branch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.models.finding import EvaluationOutcome
from app.services.rule_findings import outcome_for_verdict
from app.verification.rule_engine.activation_bars import load_activation_bars
from app.verification.rule_engine.pending_checks import (
    blocked_candidate_rule_ids,
    evaluate_pending_checks,
)
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS
from app.verification.rule_engine.result import Verdict
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_A = UUID("11111111-1111-4111-8111-111111111111")
_B = UUID("22222222-2222-4222-8222-222222222222")


def _f(v: str) -> Field:
    return Field.present(v, source=FieldSource.EXTRACTED)


def _tag(v: str) -> Tag:
    return Tag(
        value=v,
        confidence=0.9,
        reasoning="fixture",
        source_facts=("r",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


def _w2(cid: str, owner: UUID) -> DocumentEntry:
    # a document each borrower OWNS — the per_borrower enumerator derives borrowers from belongs_to refs
    return DocumentEntry(
        content_id=cid,
        document_type="w2",
        belongs_to=(BorrowerRef(borrower_id=owner, name="X"),),
        fields={"tax_year": _f("2024")},
    )


def _snap(
    by_subject: dict[str, dict[str, Tag]], extra_docs: tuple[DocumentEntry, ...] = ()
) -> Snapshot:
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 22, tzinfo=UTC),
        documents=DocumentsSection.present([_w2("wA", _A), _w2("wB", _B), *extra_docs]),
        mismo=MismoSection.present(
            {"borrower.1.borrower_id": _f(str(_A)), "borrower.2.borrower_id": _f(str(_B))}
        ),
        tags=TagsSection.present(by_subject),
    )


# --------------------------------------------------------------------------- #
# GENERIC — the blocked set is bars minus the active set, never a hand-list
# --------------------------------------------------------------------------- #
def test_blocked_candidates_are_exactly_bars_minus_active() -> None:
    blocked = set(blocked_candidate_rule_ids())
    assert blocked == set(load_activation_bars()) - set(ACTIVE_RULE_IDS)
    assert not (
        blocked & set(ACTIVE_RULE_IDS)
    )  # a live rule is NEVER a pending candidate (disjoint)
    # the calibratable-but-signed-off rules are live, so NOT pending candidates
    for live in ("AS-2", "AS-12", "IN-3"):
        assert live not in blocked


# --------------------------------------------------------------------------- #
# APPLICABLE + DATA → a manual-review flag, never the verdict
# --------------------------------------------------------------------------- #
def _gift(cid: str, owner: UUID) -> DocumentEntry:
    # a gift_letter document (AS-5's applicability type) attributed to a borrower.
    # (Was a bank_statement for AS-6, which went live in LP-429 — AS-5 is now the standing blocked per_document
    # example; it reads txn.apparent_category, still uncalibrated.)
    return DocumentEntry(
        content_id=cid,
        document_type="gift_letter",
        belongs_to=(BorrowerRef(borrower_id=owner, name="X"),),
        fields={"donor": _f("Aunt May")},
    )


async def test_a_blocked_rule_that_reaches_a_verdict_surfaces_pending_never_the_verdict() -> None:
    # AS-5 (blocked: txn.apparent_category uncalibrated) is per_document on a gift_letter. The document carries
    # apparent_category="payroll" (present, so it clears the gate) != "gift" → the rule WOULD 'fire' an
    # incomplete-gift-chain finding (an untrusted verdict). Still BLOCKED, so the would-be fire surfaces as
    # PENDING, never the verdict. (AS-6 demonstrated this before LP-429 activated it; IN-8 before LP-428.)
    snap = _snap(
        {"giftA": {"txn.apparent_category": _tag("payroll")}},
        extra_docs=(_gift("giftA", _A),),
    )
    pending = await evaluate_pending_checks(snap)
    as5 = [p for p in pending if p.rule_id == "AS-5"]
    # LP-549 — keyed at the LOAN, not the subject that matched. A pending flag says "this FILE has
    # something in scope and nothing looked at it", which is a statement about the file; keying it per
    # subject put SEVEN identical rows in front of a processor the first time a per-TRANSACTION rule was
    # blocked. Still exactly one flag, which is what this assertion was really protecting.
    assert len(as5) == 1 and as5[0].subject_id == "loan"
    flag = as5[0]
    # THE NO-LEAK GUARANTEE: the would-be 'fired' is discarded — never shipped.
    assert flag.verdict is Verdict.PENDING_AUTOMATION
    assert flag.load_bearing_tags == ()  # the uncalibrated tag VALUE never rides along
    assert flag.verdict_confidence is None
    assert "manual review" in flag.reasoning.lower()
    # every surfaced flag across ALL blocked rules is a pending flag — no satisfied/fired/needs_review escapes
    assert all(p.verdict is Verdict.PENDING_AUTOMATION and not p.load_bearing_tags for p in pending)


async def test_a_blocked_rule_with_no_data_stays_dark_no_fabricated_flag() -> None:
    # AS-5 is APPLICABLE (a gift_letter is present) but has NO txn.apparent_category tag → couldnt_checks →
    # NOTHING surfaces (honest silence, not a fabricated "manual review" the rule cannot support).
    snap = _snap({}, extra_docs=(_gift("giftA", _A),))
    pending = await evaluate_pending_checks(snap)
    assert [p for p in pending if p.rule_id == "AS-5"] == []


async def test_a_blocked_JUDGMENT_rule_surfaces_through_the_stub_no_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The judgment path (the reason `_discarded_judgment_stub` exists).

    LP-495c — THE DEMO RULE RAN OUT. This example moved IN-7 -> IN-13 -> DT-7 as each went live, and
    DT-7 was the last BLOCKED judgment rule; its enum gained an abstain and it activated, so there is
    now NO blocked judgment rule to demonstrate with. That is the ticket series working as intended,
    not a gap — and it is asserted below so this comment cannot go stale silently.

    The path itself is still live code and must stay covered, so DT-7's prior BLOCKED state is
    simulated by removing it from the active set that `blocked_candidate_rule_ids()` subtracts. The
    machinery under test — the stub binding, the discarded verdict, the no-leak guarantee — is entirely
    real; only the "which rules are blocked" input is varied. No real model call: evaluate_pending_checks
    binds the discarded stub for every blocked judgment rule.

    DT-7 is LOAN-subject, so the "A surfaces / B stays dark" pair is proven across two snapshots rather
    than two borrowers: the tag present -> applicable + gate-passes -> the stub drives it to
    needs_review (a judgment rule ALWAYS reaches needs_review when applicable, never auto) -> surfaces
    as PENDING; the tag absent -> couldnt_check -> DARK.
    """
    from app.verification.rule_engine import pending_checks as pc
    from app.verification.rules.kinds import RuleKindName, kind_for

    # The state this test used to rely on is gone, and that is the point.
    still_blocked_judgment = [
        rid
        for rid in pc.blocked_candidate_rule_ids()
        if (k := kind_for(rid)) is not None and k.kind is RuleKindName.JUDGMENTAL
    ]
    # LP-547 made this real for one ticket — FR-5 was a built-but-blocked judgment rule — and LP-551
    # activated it, which is exactly the case the message below anticipates. The blocked set is now
    # AS-3 / AS-5 / AS-7 / CO-5 / CR-5 / PC-5, none of them judgmental, so the simulation is once again
    # the only way to exercise this path.
    assert still_blocked_judgment == [], (
        "a blocked judgment rule exists again — prefer it over the simulation below and update this test"
    )

    monkeypatch.setattr(pc, "ACTIVE_RULE_IDS", tuple(r for r in ACTIVE_RULE_IDS if r != "DT-7"))
    assert "DT-7" in pc.blocked_candidate_rule_ids()

    snap = _snap({"loan": {"dti.atr_factors_documented": _tag("complete")}})
    pending = await pc.evaluate_pending_checks(snap)
    dt7 = [p for p in pending if p.rule_id == "DT-7"]
    assert len(dt7) == 1
    assert dt7[0].verdict is Verdict.PENDING_AUTOMATION
    assert dt7[0].load_bearing_tags == () and dt7[0].verdict_confidence is None  # no-leak
    assert "manual review" in dt7[0].reasoning.lower()

    # The dark half: no tag -> the rule couldnt_checks and never surfaces as pending.
    dark = await pc.evaluate_pending_checks(_snap({}))
    assert [p for p in dark if p.rule_id == "DT-7"] == []


# --------------------------------------------------------------------------- #
# DISTINCT — the pending flag is its own outcome, never a trusted pass/fail
# --------------------------------------------------------------------------- #
def test_pending_maps_to_a_distinct_outcome_not_satisfied_or_open() -> None:
    outcome = outcome_for_verdict(Verdict.PENDING_AUTOMATION)
    assert outcome is EvaluationOutcome.PENDING_AUTOMATION
    assert outcome not in (EvaluationOutcome.SATISFIED, EvaluationOutcome.OPEN)
    # satisfied/open (trusted verdicts) map to their OWN distinct outcomes — no aliasing with pending.
    assert outcome_for_verdict(Verdict.SATISFIED) is EvaluationOutcome.SATISFIED
    assert outcome_for_verdict(Verdict.FIRED) is EvaluationOutcome.OPEN
