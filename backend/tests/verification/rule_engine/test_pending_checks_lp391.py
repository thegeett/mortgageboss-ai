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


def _tax_return(cid: str, owner: UUID) -> DocumentEntry:
    # a tax_return doc — IN-12 (per_document, still BLOCKED after LP-393-6) only applies to this type; its
    # subject is the content_id, so its gated tag is read at ``cid`` (not the borrower).
    return DocumentEntry(
        content_id=cid,
        document_type="tax_return",
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
async def test_a_blocked_rule_that_reaches_a_verdict_surfaces_pending_never_the_verdict() -> None:
    # IN-12 (blocked after LP-393-6, per_document, tax_return only) reads income.has_2yr_history at the DOCUMENT
    # subject. Doc trA has it ("no" → the rule WOULD 'fire') — an untrusted verdict; trB has no tag (→
    # couldnt_check). (IN-10/IN-11 used to demo this but went live in LP-393-6; IN-12 stays blocked.)
    trA, trB = _tax_return("trA", _A), _tax_return("trB", _B)
    snap = _snap({"trA": {"income.has_2yr_history": _tag("no")}}, extra_docs=(trA, trB))
    pending = await evaluate_pending_checks(snap)
    in12 = [p for p in pending if p.rule_id == "IN-12"]
    assert (
        len(in12) == 1 and in12[0].subject_id == "trA"
    )  # trA surfaces; trB (couldnt_check) stays DARK
    flag = in12[0]
    # THE NO-LEAK GUARANTEE: the would-be 'fired' is discarded — never shipped.
    assert flag.verdict is Verdict.PENDING_AUTOMATION
    assert flag.load_bearing_tags == ()  # the uncalibrated tag VALUE never rides along
    assert flag.verdict_confidence is None
    assert "manual review" in flag.reasoning.lower()
    # every surfaced flag across ALL blocked rules is a pending flag — no satisfied/fired/needs_review escapes
    assert all(p.verdict is Verdict.PENDING_AUTOMATION and not p.load_bearing_tags for p in pending)


async def test_a_blocked_rule_with_no_data_stays_dark_no_fabricated_flag() -> None:
    # IN-12 is APPLICABLE (a tax_return doc is present) but has NO income.has_2yr_history tag → couldnt_checks →
    # NOTHING surfaces (honest silence, not a fabricated "manual review" the rule cannot support).
    trA = _tax_return("trA", _A)
    snap = _snap({}, extra_docs=(trA,))
    pending = await evaluate_pending_checks(snap)
    assert [p for p in pending if p.rule_id == "IN-12"] == []


async def test_a_blocked_JUDGMENT_rule_surfaces_through_the_stub_no_api_call() -> None:
    # The judgment path (the reason _discarded_judgment_stub exists): IN-13 is a BLOCKED per_borrower JUDGMENT
    # rule reading income.continuance_3yr. Borrower A has it → applicable + gate-passes → the stub drives it
    # to needs_review (a judgment rule ALWAYS reaches needs_review when applicable — never auto) → surfaces as
    # PENDING. No real model call: evaluate_pending_checks binds the discarded stub for every blocked judgment
    # rule (no reasoner is passed here). Borrower B has no tag → couldnt_check → DARK. If the judgment evaluator
    # ever routed an unknown/stubbed answer to couldnt_check, IN-13 would go dark and THIS test would fail.
    # (IN-7 used to demo this but went live in LP-393-6; IN-13 stays blocked.)
    snap = _snap({str(_A): {"income.continuance_3yr": _tag("yes")}})
    pending = await evaluate_pending_checks(snap)
    in13 = [p for p in pending if p.rule_id == "IN-13"]
    assert len(in13) == 1 and in13[0].subject_id == str(
        _A
    )  # A surfaces; B (couldnt_check) stays dark
    assert in13[0].verdict is Verdict.PENDING_AUTOMATION
    assert (
        in13[0].load_bearing_tags == () and in13[0].verdict_confidence is None
    )  # no-leak, same as IN-12
    assert "manual review" in in13[0].reasoning.lower()


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
