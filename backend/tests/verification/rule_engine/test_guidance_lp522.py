"""LP-522 — a judgment finding must tell a processor what to DO.

WHAT A PROCESSOR READ BEFORE THIS. On the first real file:

    the AI judged that this deposit does not appear to come from a borrowed source — an AI verdict a
    human must ratify (it never auto-ships); $2,000.00 is above the $1,316.67 (10% of $13,166.67
    qualifying income) materiality floor

It explains our engine, not their loan. It says the deposit looks fine while sitting in Needs
Attention, so a processor cannot tell why it is on their list, and it never says what to do — because
`judgment.py` hard-coded `how_to_fix=None`, leaving all 18 active judgment rules unable to carry one.
The fact they actually needed ("no matching withdrawal was found") was the fifth provenance entry,
about 400 words down.

THREE PARTS, action first. This REVERSES LP-376-B ("the message states the VERDICT") deliberately: for
a processor the verdict is the least useful part. It is not hidden — it selects the action, so a `yes`
and a `no` differ in the first six words.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.ai.rule_judgment import RuleJudgment, RuleJudgmentResult
from app.verification.rule_engine.judgment import evaluate_judgment_rule
from app.verification.rules.specs import JudgmentEval, load_rule_spec
from app.verification.snapshot.fields import Field, FieldSource
from app.verification.snapshot.model import (
    BorrowerRef,
    DocumentEntry,
    DocumentsSection,
    Snapshot,
    TagsSection,
    TransactionRecord,
)
from app.verification.snapshot.tag import Tag, TagProducedBy, TagRole, TagStage
from pydantic import ValidationError

pytestmark = pytest.mark.anyio

_LINE = "Online Transfer From Talluri A Way2Save Savings xxxxxx3627"


def _f(value: str) -> Field:
    return Field.present(value, source=FieldSource.EXTRACTED)


def _tag(value: str) -> Tag:
    return Tag(
        value=value,
        confidence=0.9,
        reasoning=f"fixture: {value}",
        source_facts=("raw",),
        produced_by=TagProducedBy.AI,
        tag_role=TagRole.STRUCTURAL_FACT,
        stage=TagStage.A,
    )


async def _evaluate(
    *, answer: str = "no", strength: str | None = "self_asserted", line: str = _LINE
):
    txn = TransactionRecord(
        content_id="t1",
        amount=_f("2000.00"),
        date=_f("2025-03-03"),
        direction=_f("credit"),
        description=_f(line),
    )
    doc = DocumentEntry(
        content_id="bs",
        document_type="bank_statement",
        belongs_to=(BorrowerRef(borrower_id=uuid4(), name="Sam"),),
        transactions=(txn,),
    )
    subject = {
        "txn.is_money_in": _tag("in"),
        "txn.apparent_category": _tag("transfer_own"),
        "txn.has_identified_source": _tag("yes"),
        "txn.amount": _tag("2000.00"),
        "txn.date": _tag("2025-03-03"),
    }
    if strength is not None:
        subject["txn.source_strength"] = _tag(strength)
    snapshot = Snapshot(
        loan_file_id=uuid4(),
        run_id=uuid4(),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        documents=DocumentsSection.present([doc]),
        tags=TagsSection.present(
            {
                "t1": subject,
                "loan": {
                    "loan.purpose": _tag("refinance"),
                    "dti.qualifying_income_monthly": _tag("13166.67"),
                },
            }
        ),
    )

    async def _reason(_context: str) -> RuleJudgmentResult:
        return RuleJudgmentResult(RuleJudgment(answer, 0.9, "because"), 1, 1, "stub", False)

    [evaluation] = await evaluate_judgment_rule(load_rule_spec("AS-12"), snapshot, reasoner=_reason)
    return evaluation.evaluation


async def test_the_finding_now_says_what_to_do() -> None:
    """⚠️ THE HEADLINE DEFECT. `how_to_fix` was hard-coded None in judgment.py, so NO judgment rule had
    ever told anyone what to do — 18 active rules, every finding, since LP-324."""
    evaluation = await _evaluate()

    assert evaluation.how_to_fix is not None
    assert "Obtain the statement for the sending account" in evaluation.how_to_fix


async def test_the_message_leads_with_the_action_not_the_verdict() -> None:
    """The reversal of LP-376-B, asserted: the first thing a processor reads is an instruction, and the
    engine's own vocabulary ("the AI judged", "never auto-ships") is gone from the message entirely."""
    evaluation = await _evaluate()

    assert evaluation.reasoning.startswith("Document the source of the $2,000.00 deposit on 3/3.")
    assert "the AI judged" not in evaluation.reasoning
    assert "auto-ships" not in evaluation.reasoning
    assert "ratify" not in evaluation.reasoning


async def test_the_verdict_shapes_the_headline_instead_of_being_a_bare_chip() -> None:
    """⚠️ WHY THE yes/no CHIP CAN GO. The verdict is not hidden — it changes the instruction. A
    processor skimming a bare `yes` reads it as "yes, fine"; it actually means "yes, this may be
    borrowed funds", the worst finding on the file read as its opposite."""
    cleared = await _evaluate(answer="no")
    flagged = await _evaluate(answer="yes")
    undetermined = await _evaluate(answer="unknown")

    assert cleared.reasoning.startswith("Document the source")
    assert flagged.reasoning.startswith(
        "Confirm the $2,000.00 deposit on 3/3 is not borrowed funds."
    )
    assert undetermined.reasoning.startswith("Establish where")


async def test_the_statement_line_is_quoted_exactly() -> None:
    """Quoting the line beats summarising it: no model call, no calibration hold, and the processor can
    string-match it against the actual document. `txn.source_reference` — the vocabulary's tag for a
    summarised source — is declared and produced by nothing."""
    evaluation = await _evaluate()

    assert f'"{_LINE}"' in evaluation.reasoning


@pytest.mark.parametrize(
    ("strength", "expected"),
    [
        ("self_asserted", "no matching withdrawal appears in any document on file"),
        ("none", "no source for it could be established from the documents on file"),
        ("verified", "its paper trail is complete"),
        ("intrinsic", "sourced by its own nature"),
    ],
)
async def test_the_why_keys_on_the_evidence_not_the_verdict(strength: str, expected: str) -> None:
    """⚠️ THE REASON `why` IS TAG-KEYED. Every case here has the SAME verdict ("no"); only the evidence
    differs. One template per verdict would have to assume a situation and would be FALSE in the others
    — "the statement line reads X, but no matching withdrawal appears" is simply wrong for a deposit
    whose source was verified."""
    evaluation = await _evaluate(strength=strength)

    assert expected in evaluation.reasoning


async def test_the_none_wording_never_contradicts_the_line_it_quotes() -> None:
    """⚠️ REGRESSION. `source_strength: none` is about CORROBORATION, not about whether the description
    has words in it. The first wording said "nothing in it identifies where the money came from" and
    rendered on a real file directly above `Online Transfer From Digital Federal Credit Union Sav
    xxxx0433 A. Talluri` — a sentence contradicting the quote beside it, which reads as a system that
    cannot read. Two of that file's five findings looked like this."""
    line = "Online Transfer From Digital Federal Credit Union Sav xxxx0433 A. Talluri"
    evaluation = await _evaluate(strength="none", line=line)

    assert f'"{line}"' in evaluation.reasoning
    assert "nothing in it identifies" not in evaluation.reasoning
    assert "no source for it could be established" in evaluation.reasoning


async def test_an_absent_strength_tag_takes_the_default_rather_than_going_wordless() -> None:
    """Stage B may not have run. A finding with no explanation is the wordless card this ticket exists
    to remove, so `default` is required at load and used here."""
    evaluation = await _evaluate(strength=None)

    assert "could not be established" in evaluation.reasoning
    assert evaluation.how_to_fix is not None


async def test_the_materiality_arithmetic_survives_demoted_from_the_headline() -> None:
    """LP-518's auditability requirement must not be lost while shortening — it moves out of the
    opening sentence and into the why, where it answers "why THIS deposit"."""
    evaluation = await _evaluate()

    assert "10% of $13,166.67 qualifying income" in evaluation.reasoning
    assert not evaluation.reasoning.startswith("$2,000.00 is above")


def test_a_rule_without_guidance_is_untouched() -> None:
    """ADDITIVE — the judgment rules not yet written keep their LP-520 text until each gets
    domain-accurate wording. OC-2 / CR-8 / DT-7 have since been written (LP-522 phase 2, the three that
    appear on LF-WCHG), so this now checks rules from further down the list."""
    for rule_id in ("ID-8", "ID-9", "IN-7"):
        judgment = load_rule_spec(rule_id).judgment
        assert judgment is not None
        assert judgment.guidance is None


# --------------------------------------------------------------------------------------------- #
# LOAD-TIME VALIDATION — every way guidance can be silently wrong
# --------------------------------------------------------------------------------------------- #
def _judgment(guidance: dict[str, object]) -> JudgmentEval:
    return JudgmentEval(
        subject="per_deposit",
        load_bearing_tags=("txn.apparent_category",),
        reasoned_over=("txn.apparent_category", "txn.amount"),
        output_tag="as.borrowed_funds",
        value_domain=("yes", "no", "unknown"),
        system_prompt="x",
        guidance=guidance,  # type: ignore[arg-type]
    )


_CASE = {"why": "w", "how_to_fix": "f"}


def test_a_verdict_with_no_action_is_rejected_at_load() -> None:
    """A partial map leaves exactly one answer with no headline — the defect, surviving on the rarest
    verdict where nobody would notice."""
    with pytest.raises(ValidationError, match=r"guidance.action is missing verdict\(s\)"):
        _judgment(
            {
                "action": {"yes": "a", "no": "b"},
                "explain_by": "txn.apparent_category",
                "explain": {"default": _CASE},
            }
        )


def test_explain_without_a_default_is_rejected_at_load() -> None:
    with pytest.raises(ValidationError, match="needs a `default` case"):
        _judgment(
            {
                "action": {"yes": "a", "no": "b", "unknown": "c"},
                "explain_by": "txn.apparent_category",
                "explain": {"payroll": _CASE},
            }
        )


def test_an_explain_by_tag_the_rule_never_reads_is_rejected_at_load() -> None:
    """⚠️ The silent one. A tag outside `reasoned_over` is absent on every subject, so every finding
    would quietly take the `default` case and the per-situation wording would never appear."""
    with pytest.raises(ValidationError, match="is not in `reasoned_over`"):
        _judgment(
            {
                "action": {"yes": "a", "no": "b", "unknown": "c"},
                "explain_by": "txn.source_strength",
                "explain": {"default": _CASE},
            }
        )


def test_an_unknown_placeholder_is_rejected_at_load() -> None:
    """A stray placeholder raises at format time — inside a Celery task, six minutes into an AI
    pipeline, after every model call has been paid for."""
    with pytest.raises(ValidationError, match=r"unknown placeholder\(s\)"):
        _judgment(
            {
                "action": {"yes": "{nope}", "no": "b", "unknown": "c"},
                "explain_by": "txn.apparent_category",
                "explain": {"default": _CASE},
            }
        )


def test_as12_declares_guidance_for_every_answer_and_every_evidence_state() -> None:
    judgment = load_rule_spec("AS-12").judgment
    assert judgment is not None and judgment.guidance is not None
    assert set(judgment.guidance.action) == set(judgment.value_domain)
    # The four SourceStrength values plus the required fallback.
    assert set(judgment.guidance.explain) == {
        "self_asserted",
        "none",
        "verified",
        "intrinsic",
        "default",
    }
    assert judgment.guidance.explain_by in judgment.reasoned_over
