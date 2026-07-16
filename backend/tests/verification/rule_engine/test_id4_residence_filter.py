"""LP-335 — the id.current_address_type fix, seen through its CONSUMER (ID-4).

LP-334 FINDING-1: the id_address prompt presumed a driver's-licence address is `prior`, so ID-4's
residence FILTER excluded it → fewer residence sources → couldnt_check, or — worse — a DL that would
DISAGREE with the 1003 got pre-filtered away, turning a real discrepancy into a clean pass. The prompt fix
makes a DL's stated address `residence` unless the document marks it otherwise.

These keyless tests exercise the CONSUMER with the (now-correct) tag values set directly — the AI's
production of those values is measured live (the LP-334 calibration re-measure). The most important test
is that a DL-vs-1003 residence DISAGREEMENT now SURFACES (the signal the old bias could silently destroy);
the over-correction guard — a mailing-only borrower still couldnt_checks, not a false discrepancy — is
asserted too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.consistency import evaluate_consistency_rule
from app.verification.rule_engine.result import Verdict
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage

pytestmark = pytest.mark.anyio

_B = uuid4()


def _tag(value: str, *, conf: float | None = 0.9) -> Tag:
    return Tag(
        value=value,
        confidence=conf,
        reasoning="fixture",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


class _Reasoner:
    """Keyless fuzzy-leg stub — records whether the AI was consulted (the LP-325 no-AI cost property)."""

    def __init__(self, value: str = "disagree") -> None:
        self.value = value
        self.calls = 0

    async def __call__(self, _ctx: str) -> RuleJudgmentResult:
        self.calls += 1
        return RuleJudgmentResult(RuleJudgment(self.value, 0.9, "because"), 1, 1, "stub", False)


def _snap(docs: list[tuple[str, str, str, str]]):
    """docs = [(content_id, document_type, address, current_address_type)] — the DL/1003 sources,
    each co-locating id.address_normalized + id.current_address_type on its own document subject (LP-325/326)."""
    entries = [
        DocumentEntry(
            content_id=cid, document_type=dt, belongs_to=(BorrowerRef(borrower_id=_B, name="Sam"),)
        )
        for cid, dt, _, _ in docs
    ]
    by_subject = {
        cid: {"id.address_normalized": _tag(addr), "id.current_address_type": _tag(atype)}
        for cid, _dt, addr, atype in docs
    }
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        documents=DocumentsSection.present(entries),
        tags=TagsSection.present(by_subject),
    )


async def _id4(docs, reasoner):
    return await evaluate_consistency_rule(load_rule_spec("ID-4"), _snap(docs), reasoner=reasoner)


# --------------------------------------------------------------------------- #
# THE FIX'S DOWNSTREAM VALUE — the DL is no longer excluded, so ID-4 can do its job
# --------------------------------------------------------------------------- #
async def test_dl_and_1003_residence_that_agree_satisfy() -> None:
    # Both now typed 'residence' (the fix) and identical → exact bookend → satisfied, NO AI call.
    stub = _Reasoner("disagree")
    r = await _id4(
        [
            ("dl", "drivers_license", "123 Main St", "residence"),
            ("app", "loan_application_1003", "123 Main St", "residence"),
        ],
        stub,
    )
    assert [x.verdict for x in r] == [Verdict.SATISFIED] and stub.calls == 0


async def test_dl_and_1003_residence_that_DISAGREE_surfaces() -> None:
    # THE MOST IMPORTANT TEST. With the DL correctly typed 'residence' (the fix), a DL address that
    # DIFFERS from the 1003 residence is COMPARED → the discrepancy SURFACES (fired). Under the old
    # prior-presumption the DL was excluded → only the 1003 residence → <2 → couldnt_check, and the
    # discrepancy was SILENTLY DESTROYED.
    r = await _id4(
        [
            (
                "dl",
                "drivers_license",
                "500 Oak Ave",
                "residence",
            ),  # a DIFFERENT residence on the DL
            ("app", "loan_application_1003", "123 Main St", "residence"),
        ],
        _Reasoner("disagree"),
    )
    assert [x.verdict for x in r] == [Verdict.FIRED] and r[
        0
    ].reasoning  # the signal is no longer masked


async def test_the_old_bias_would_have_masked_it() -> None:
    # Documents the counterfactual: had the DL been (wrongly) typed 'prior', it is filtered out → only the
    # 1003 residence remains → <2 → couldnt_check (the discrepancy hidden). This is what the fix prevents.
    r = await _id4(
        [
            ("dl", "drivers_license", "500 Oak Ave", "prior"),  # the OLD (buggy) type
            ("app", "loan_application_1003", "123 Main St", "residence"),
        ],
        _Reasoner("disagree"),
    )
    assert [x.verdict for x in r] == [
        Verdict.COULDNT_CHECK
    ]  # masked — exactly the bug LP-335 fixes


# --------------------------------------------------------------------------- #
# THE OVER-CORRECTION GUARD — the filter still works; mailing is not a false discrepancy
# --------------------------------------------------------------------------- #
async def test_mailing_only_borrower_still_couldnt_check_not_a_discrepancy() -> None:
    # A residence + a MAILING address → only 1 residence source → couldnt_check (LP-325/LP-323-ID-A §4).
    # The fix must NOT relabel the PO box as residence (which would fabricate a discrepancy).
    stub = _Reasoner("disagree")
    r = await _id4(
        [
            ("app", "loan_application_1003", "123 Main St", "residence"),
            ("bank", "bank_statement", "PO Box 88", "mailing"),
        ],
        stub,
    )
    assert [x.verdict for x in r] == [Verdict.COULDNT_CHECK] and stub.calls == 0
    assert "residence" in r[0].reasoning  # the mailing source was correctly excluded


async def test_document_marked_prior_is_still_excluded() -> None:
    # A residence + a document-marked PRIOR address → only 1 residence → couldnt_check (a prior address is
    # genuinely not the current residence — the guard the filter exists for is intact).
    r = await _id4(
        [
            ("app", "loan_application_1003", "123 Main St", "residence"),
            ("dl", "drivers_license", "10 Old Farm Rd", "prior"),
        ],
        _Reasoner("disagree"),
    )
    assert [x.verdict for x in r] == [Verdict.COULDNT_CHECK]
