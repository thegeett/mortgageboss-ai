"""LP-444 — CR-4 (undisclosed tradeline, report vs app): the FIRST consumer of list visibility, built INERT.

The credit_profile borrower group compares a credit report's TRADELINES (a generic list, now visible via
LP-444) against the app's file-level STATED LIABILITIES (MISMO), producing credit.undisclosed_tradeline;
CR-4 reads that verdict. These pin: CR-4 is INERT (not in ACTIVE_RULE_IDS, priya_validated:false — a new AI
judgment is never activated on arrival); the group opts into lists + liabilities; and the verdict shape —
an undisclosed tradeline → fired, all disclosed → satisfied, cannot-compare (truncation / missing) →
couldnt_check, NEVER a finding on a missing document.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.verification.rule_engine.registry import ACTIVE_RULE_IDS, evaluate_rules
from app.verification.rules.specs import load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    ListRow,
    MismoSection,
    Snapshot,
    TagsSection,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from app.verification.tag_materialization.ai import (
    AiGroupResult,
    AiSubjectJudgment,
    AiTagJudgment,
    produce_ai_group_tags,
)
from app.verification.tag_materialization.declarations import load_ai_groups

pytestmark = pytest.mark.anyio

_E = FieldSource.EXTRACTED
_BID = "11111111-1111-1111-1111-111111111111"


def _f(v: str) -> Field:
    return Field.present(v, source=_E)


def _tradeline(creditor: str, payment: str) -> ListRow:
    return ListRow(
        fields={
            "creditor_name": _f(creditor),
            "account_number_masked": _f("4471000012345"),
            "monthly_payment": _f(payment),
            "account_status": _f("open"),
        }
    )


def _snapshot(report_creditors: list[str], liability_creditors: list[str]) -> Snapshot:
    rows = tuple(_tradeline(c, "250") for c in report_creditors)
    cr = DocumentEntry(
        content_id="docCR",
        document_type="credit_report",
        belongs_to=(BorrowerRef(borrower_id=_BID, name="J. Rivera"),),
        fields={"report_date": _f("2026-05-01")},
        lists={"tradelines": rows},
    )
    mismo: dict[str, Field] = {
        "borrower.1.borrower_id": _f(_BID),
        "borrower.1.first_name": _f("Jordan"),
    }
    for i, c in enumerate(liability_creditors, 1):
        mismo[f"liability.{i}.creditor_name"] = _f(c)
        mismo[f"liability.{i}.monthly_payment"] = _f("250")
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        documents=DocumentsSection.present([cr]),
        mismo=MismoSection.present(mismo),
    )


async def _comparing_stub(context_json: str) -> AiGroupResult:
    """A deterministic, keyless reasoner that ACTUALLY compares the context — proving the list-visibility
    mechanism feeds CR-4 everything it needs (tradelines + liabilities) to reach the verdict."""
    ctx = json.loads(context_json)
    out = []
    for s in ctx["subjects"]:
        tradelines = [
            r
            for d in s.get("documents", [])
            for r in d.get("lists", {}).get("tradelines", {}).get("rows", [])
            if r.get("monthly_payment") not in (None, "0", "0.00")
        ]
        liab = {liability.get("creditor_name") for liability in s.get("stated_liabilities", [])}
        unmatched = [r["creditor_name"] for r in tradelines if r.get("creditor_name") not in liab]
        out.append(
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={
                    "undisclosed_tradeline": AiTagJudgment(
                        "yes" if unmatched else "no", 0.9, f"unmatched={unmatched}"
                    )
                },
            )
        )
    return AiGroupResult(out, 0, 0, "stub", False)


async def _cr4_verdict_via_group(report: list[str], liab: list[str]) -> str:
    """Run credit_profile (stub) → the tag → CR-4 (evaluated directly, since it is inert) → the verdict."""
    snap = _snapshot(report, liab)
    group = load_ai_groups()["credit_profile"]
    by_subject = await produce_ai_group_tags(
        snap,
        group,
        {"credit.undisclosed_tradeline": ("yes", "no", "unknown")},
        reasoner=_comparing_stub,
    )
    tag = by_subject[_BID]["credit.undisclosed_tradeline"]
    snap2 = snap.model_copy(
        update={"tags": TagsSection.present({_BID: {"credit.undisclosed_tradeline": tag}})}
    )
    evals, _ = await evaluate_rules(snap2, rule_ids=("CR-4",))
    return next(e for e in evals if e.rule_id == "CR-4").verdict.value


# --------------------------------------------------------------------------- #
# INERT — a new AI judgment ships un-activated
# --------------------------------------------------------------------------- #
def test_cr4_is_inert() -> None:
    assert "CR-4" not in ACTIVE_RULE_IDS  # not evaluated on a live file
    assert len(ACTIVE_RULE_IDS) == 36  # the 36 live rules are unmoved
    spec = load_rule_spec("CR-4")  # but the spec exists (loadable, verdict-shaped)
    assert spec.reference_values.priya_validated is False  # awaits calibration + Priya's bar


def test_credit_profile_group_opts_into_lists_and_liabilities() -> None:
    group = load_ai_groups()["credit_profile"]
    assert group.subject == "borrower" and group.include_lists and group.include_stated_liabilities
    assert group.list_row_cap == 50
    assert group.tag_ids == ("credit.undisclosed_tradeline",)


# --------------------------------------------------------------------------- #
# The verdict shape (reported end-to-end through the mechanism)
# --------------------------------------------------------------------------- #
async def test_cr4_fires_on_a_deliberate_undisclosed_tradeline() -> None:
    # Amex is on the credit report (payment > 0) but NOT in the stated liabilities → undisclosed → fired.
    verdict = await _cr4_verdict_via_group(["Chase", "Amex"], ["Chase"])
    assert verdict == "fired"


async def test_cr4_satisfied_when_every_tradeline_is_disclosed() -> None:
    verdict = await _cr4_verdict_via_group(["Chase", "Amex"], ["Chase", "Amex"])
    assert verdict == "satisfied"


async def test_cr4_unknown_verdict_is_couldnt_check_never_a_finding() -> None:
    # A truncated/uncomparable context → the AI answers "unknown" → CR-4 couldnt_check (NOT a finding).
    snap = _snapshot(["Chase"], ["Chase"])
    unknown = Tag(
        value="unknown",
        confidence=None,
        reasoning="tradelines truncated",
        source_facts=(_BID,),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )
    snap2 = snap.model_copy(
        update={"tags": TagsSection.present({_BID: {"credit.undisclosed_tradeline": unknown}})}
    )
    evals, _ = await evaluate_rules(snap2, rule_ids=("CR-4",))
    assert next(e for e in evals if e.rule_id == "CR-4").verdict.value == "couldnt_check"
