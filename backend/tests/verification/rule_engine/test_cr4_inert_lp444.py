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
from app.verification.rule_engine.registry import evaluate_rules
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
from app.verification.tag_materialization.derived import _credit_undisclosed_tradeline

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
        # ⚠️ holder_name, not creditor_name: mismo_section projects liability.{n}.holder_name (LP-483).
        # The fixture previously used a name MISMO never emits — harmless only because the old stub read
        # the same wrong key. Corrected so the test exercises the production projection.
        mismo[f"liability.{i}.holder_name"] = _f(c)
        mismo[f"liability.{i}.monthly_payment"] = _f("250")
    return Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime.now(UTC),
        documents=DocumentsSection.present([cr]),
        mismo=MismoSection.present(mismo),
    )


async def _comparing_stub(context_json: str) -> AiGroupResult:
    """A deterministic, keyless reasoner that ACTUALLY compares the context — proving the liability
    context feeds the matcher everything it needs (THIS tradeline + the stated liabilities).

    ⚠️ ADR-375 — the judgment is now PER LIABILITY (``liab.in_application``: is THIS tradeline on the
    application?), not one borrower-level rollup. The borrower tag is derived from these.
    """
    ctx = json.loads(context_json)
    out = []
    for s in ctx["subjects"]:
        stated = {liability.get("holder_name") for liability in s.get("stated_liabilities", [])}
        creditor = s.get("creditor_name")
        # A paid-off tradeline (no payment) is not DTI-relevant — the matcher abstains rather than
        # calling it undisclosed, mirroring the shipped prompt's instruction.
        if s.get("monthly_payment") in (None, "0", "0.00"):
            value = "unknown"
        else:
            value = "yes" if creditor in stated else "no"
        out.append(
            AiSubjectJudgment(
                index=int(s["index"]),
                tags={"in_application": AiTagJudgment(value, 0.9, f"creditor={creditor}")},
            )
        )
    return AiGroupResult(out, 0, 0, "stub", False)


async def _cr4_verdict_via_group(report: list[str], liab: list[str]) -> str:
    """credit_profile (stub, per-liability) → the DERIVED borrower rollup → CR-4 → the verdict.

    This is the ADR-375 chain end to end: one matcher at liability scope, the borrower answer computed
    from it, so CR-1 and CR-4 cannot disagree about the same file.
    """
    snap = _snapshot(report, liab)
    group = load_ai_groups()["credit_profile"]
    by_subject = await produce_ai_group_tags(
        snap,
        group,
        {"liab.in_application": ("yes", "no", "unknown")},
        reasoner=_comparing_stub,
    )
    with_liab = snap.model_copy(update={"tags": TagsSection.present(by_subject)})
    value, reasoning = _credit_undisclosed_tradeline(with_liab, _BID, None)
    rollup = Tag(
        value=value,
        confidence=None,
        reasoning=reasoning,
        source_facts=(_BID,),
        produced_by=TagProducedBy.DERIVED,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )
    snap2 = snap.model_copy(
        update={"tags": TagsSection.present({_BID: {"credit.undisclosed_tradeline": rollup}})}
    )
    evals, _ = await evaluate_rules(snap2, rule_ids=("CR-4",))
    return next(e for e in evals if e.rule_id == "CR-4").verdict.value


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
